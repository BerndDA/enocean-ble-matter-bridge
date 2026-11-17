//! One subscription per node, kept alive for the lifetime of the task.

use std::sync::Arc;
use std::time::Duration;

use anyhow::{Context, Result};
use matter_controller::{
    AttributePath, Error as MatterError, EventPath, EventReport, ReadPath, SubscriptionEvent,
    Value,
};
use serde_json::json;

use crate::hub::Hub;
use crate::tlv::to_json;

const DESCRIPTOR: u32 = 0x001d;
const DESCRIPTOR_PARTS_LIST: u32 = 0x0003;
const BASIC_INFORMATION: u32 = 0x0028;

pub struct Watcher {
    hub: Arc<Hub>,
    node_id: u64,
}

/// What one subscription covers.
struct Paths {
    attrs: Vec<ReadPath>,
    events: Vec<EventPath>,
    /// Endpoints the paths were built from; a PartsList change rebuilds them.
    parts: Vec<u64>,
}

impl Watcher {
    pub fn new(hub: Arc<Hub>, node_id: u64) -> Self {
        Self { hub, node_id }
    }

    pub async fn run(self) {
        // Highest event number already emitted; survives restarts so the
        // device's event buffer is not replayed on every subscribe.
        let mut watermark: Option<u64> = std::fs::read_to_string(self.hub.watermark_file(self.node_id))
            .ok()
            .and_then(|s| s.trim().parse().ok());
        let mut backoff = Duration::from_secs(2);
        let mut wildcard = self.hub.cfg.all;
        loop {
            match self.session(&mut watermark, &mut wildcard).await {
                Ok(()) => backoff = Duration::from_secs(2),
                Err(e) => self.log(&format!("{e:#}, retry in {backoff:?}")),
            }
            self.hub.online(self.node_id, false);
            tokio::time::sleep(backoff).await;
            backoff = (backoff * 2).min(Duration::from_secs(300));
        }
    }

    fn log(&self, msg: &str) {
        eprintln!("{}/{}: {msg}", self.hub.cfg.prefix, self.node_id);
    }

    /// One subscription lifetime. Returns Ok when it should simply be rebuilt
    /// (PartsList changed, stream ended).
    async fn session(&self, watermark: &mut Option<u64>, wildcard: &mut bool) -> Result<()> {
        let node = self.hub.node(self.node_id);
        let paths = self.paths(*wildcard).await?;
        if watermark.is_none() {
            // First contact: the subscribe replays the device's event buffer,
            // so take its newest event number as the starting point.
            let history = node
                .read_events(&paths.events, &[])
                .await
                .context("reading event history")?;
            let newest = history
                .iter()
                .filter_map(|r| match r {
                    EventReport::Data(e) => Some(e.event_number),
                    _ => None,
                })
                .max()
                .unwrap_or(0);
            self.store_watermark(watermark, newest);
        }
        let mut sub = match node
            .subscribe(&paths.attrs, &paths.events, 0, self.hub.cfg.max_interval)
            .await
        {
            Ok(s) => s,
            Err(MatterError::SubscribeRejected(status)) if !*wildcard => {
                // Too many paths for the device; one wildcard path always fits.
                self.log(&format!(
                    "subscription with {} paths rejected (0x{status:02x}), using wildcard",
                    paths.attrs.len()
                ));
                *wildcard = true;
                return Ok(());
            }
            Err(e) => return Err(e).context("subscribe"),
        };
        // The priming report cannot be trusted to be complete: besides the
        // 256-report buffer (signalled as Lagged), the library silently drops
        // the head of a notification spanning more than 64 chunks, which a
        // Thread device's priming report easily does. So every (re)established
        // subscription starts with a per-path read.
        let mut resync = true;
        let mut established = false;

        while let Some(ev) = sub.next().await {
            match ev {
                SubscriptionEvent::Report(r) => {
                    let p = r.path;
                    if p.endpoint == 0
                        && p.cluster == DESCRIPTOR
                        && p.attribute == DESCRIPTOR_PARTS_LIST
                        && !*wildcard
                        && parts_of(&r.value) != paths.parts
                    {
                        self.log("endpoint list changed, resubscribing");
                        return Ok(());
                    }
                    self.emit_attr(p, &r.value);
                }
                SubscriptionEvent::Event(EventReport::Data(e)) => {
                    if watermark.is_some_and(|w| e.event_number <= w) {
                        continue;
                    }
                    self.store_watermark(watermark, e.event_number);
                    let p = e.path;
                    self.hub.event(
                        self.node_id,
                        p.endpoint.unwrap_or_default(),
                        p.cluster.unwrap_or_default(),
                        p.event.unwrap_or_default(),
                        json!({
                            "number": e.event_number,
                            "priority": format!("{:?}", e.priority),
                            "timestamp": format!("{:?}", e.timestamp),
                            "data": to_json(&e.value),
                        }),
                    );
                }
                SubscriptionEvent::Established { subscription_id, max_interval, .. } => {
                    self.log(&format!(
                        "subscribed, {} paths (id 0x{subscription_id:08x}, max interval {max_interval}s)",
                        paths.attrs.len()
                    ));
                    self.hub.online(self.node_id, true);
                    established = true;
                }
                SubscriptionEvent::Resubscribing { cause } => {
                    self.log(&format!("resubscribing: {cause}"));
                    self.hub.online(self.node_id, false);
                    established = false;
                    resync = true;
                }
                SubscriptionEvent::Lagged { dropped } => {
                    // The report buffer (256, fixed in the library) overflowed,
                    // typically during priming. A read has no such limit.
                    self.log(&format!("{dropped} reports dropped, resyncing by read"));
                    resync = true;
                }
                other => self.log(&format!("{other:?}")),
            }
            // During priming wait for Established, so the read sees the final state.
            if resync && established {
                resync = false;
                self.resync(&paths.attrs).await;
                self.hub.ready(self.node_id);
            }
        }
        self.log("subscription ended");
        Ok(())
    }

    fn store_watermark(&self, watermark: &mut Option<u64>, n: u64) {
        *watermark = Some(n);
        std::fs::write(self.hub.watermark_file(self.node_id), n.to_string()).ok();
    }

    /// Endpoint 0 is infrastructure (certificates, ACLs, diagnostics): only
    /// BasicInformation and the endpoint list are of interest there. Every
    /// other endpoint is subscribed completely.
    async fn paths(&self, wildcard: bool) -> Result<Paths> {
        if wildcard {
            return Ok(Paths {
                attrs: vec![ReadPath::all()],
                events: vec![EventPath::default()],
                parts: Vec::new(),
            });
        }
        let read = self
            .hub
            .node(self.node_id)
            .read(&[ReadPath::concrete(0, DESCRIPTOR, DESCRIPTOR_PARTS_LIST)])
            .await
            .context("reading endpoint list")?;
        let parts = read.first().map(|(_, v)| parts_of(v)).unwrap_or_default();

        let mut attrs = vec![
            ReadPath::cluster(0, BASIC_INFORMATION),
            ReadPath::concrete(0, DESCRIPTOR, DESCRIPTOR_PARTS_LIST),
        ];
        let mut events = vec![EventPath::cluster(0, BASIC_INFORMATION)];
        for &ep in &parts {
            let ep = u16::try_from(ep)?;
            attrs.push(ReadPath::new(Some(ep), None, None));
            let mut e = EventPath::default();
            e.endpoint = Some(ep);
            events.push(e);
        }
        Ok(Paths { attrs, events, parts })
    }

    /// One read per path keeps each response far below the library's chunk
    /// and size limits.
    async fn resync(&self, attrs: &[ReadPath]) {
        let node = self.hub.node(self.node_id);
        for path in attrs {
            match node.read(std::slice::from_ref(path)).await {
                Ok(values) => {
                    for (p, v) in values {
                        self.emit_attr(p, &v);
                    }
                }
                Err(e) => self.log(&format!("resync read of {path:?} failed: {e}")),
            }
        }
    }

    fn emit_attr(&self, p: AttributePath, v: &Value) {
        // Global attributes: attribute/command/feature lists, revision.
        if !self.hub.cfg.all && (0xfff8..=0xfffd).contains(&p.attribute) {
            return;
        }
        self.hub.attribute(self.node_id, p, to_json(v));
    }
}

fn parts_of(v: &Value) -> Vec<u64> {
    let mut out: Vec<u64> = match v {
        Value::Array(items) => items
            .iter()
            .filter_map(|i| if let Value::Uint(u) = i { Some(*u) } else { None })
            .collect(),
        _ => Vec::new(),
    };
    out.sort_unstable();
    out
}
