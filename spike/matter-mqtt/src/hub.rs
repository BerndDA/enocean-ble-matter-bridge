//! Shared state: the controller, one watcher task per node, the raw values per
//! node and what has been published. Raw values come in through
//! [`Hub::attribute`] / [`Hub::event`]; the hub maps them to readable topics
//! (see `mapping`) and hands them to [`Hub::publish`], which prints them
//! (later: publishes them to MQTT, retained).

use std::collections::{BTreeMap, HashMap, HashSet, VecDeque};
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use anyhow::{Context, Result, bail, ensure};
use matter_codec::Tag;
use matter_controller::{
    AttributePath, CommandPath, ImStatus, InvokeResult, MatterController, Node, NodeInfo,
    ReadPath, Value,
};
use serde::Serialize;
use serde_json::{Map, Value as Json, json};
use tokio::sync::Notify;
use tokio::task::JoinHandle;

use crate::mapping;
use crate::mqtt::Mqtt;
use crate::ota::{self, OtaImage, OtaStatus};
use crate::watcher::Watcher;

const OPERATIONAL_CREDENTIALS: u32 = 0x003e;
const CURRENT_FABRIC_INDEX: u32 = 0x0005;
const CMD_REMOVE_FABRIC: u32 = 0x0a;
const KEEP_EVENTS: usize = 50;

const DESCRIPTOR: u32 = 0x001d;
const BASIC_INFORMATION: u32 = 0x0028;
const BRIDGED_DEVICE: u32 = 0x0039;
const NODE_LABEL: u32 = 0x0005;
const UNIQUE_ID: u32 = 0x0012;
const SOFTWARE_VERSION: u32 = 0x0009;

/// BDX block size for OTA: 512 keeps a block within fewer 6LoWPAN fragments
/// than the library's Wi-Fi default of 960 (Thread: about 5 KB/s).
const OTA_BLOCK_SIZE: u16 = 512;
/// An update that hasn't finished by then is given up.
const OTA_TIMEOUT: Duration = Duration::from_secs(30 * 60);
/// Before the download has started: the device sat in Idle that long after
/// the announcement, so it gave up (typically a stale session or a pending
/// lookup of our node shortly after its reboot, see gateway_ota.cpp). The
/// provider is restarted and the update announced again.
const OTA_RETRY_IDLE: Duration = Duration::from_secs(60);
const OTA_ATTEMPTS: u8 = 3;
/// After the download has started: the device sat in Idle that long, so it
/// gave up, and the provider would wait forever.
const OTA_IDLE_LIMIT: Duration = Duration::from_secs(180);
/// How long a finished update's status stays on `<prefix>/<device>/ota`.
const OTA_KEEP: Duration = Duration::from_secs(10 * 60);

pub struct Config {
    pub prefix: String,
    pub state_dir: PathBuf,
    pub max_interval: u16,
    pub all: bool,
    /// Also publish every raw value under `<prefix>/raw/<node>/...`.
    pub raw: bool,
    /// Echo every message on stdout.
    pub print: bool,
    /// UDP port of the OTA provider (BDX).
    pub ota_port: u16,
    /// Where `<prefix>/<device>/ota/set` {"file": ...} looks for .ota files.
    pub ota_dir: PathBuf,
    /// MQTT over WebSockets for the web UI's OTA progress (read only).
    pub mqtt_ws: Option<String>,
}

#[derive(Default, Clone, Serialize)]
pub struct NodeView {
    pub online: bool,
    /// The first complete read is done; names can be resolved.
    pub ready: bool,
    /// `<endpoint>/<cluster>/<attribute>` (hex) -> raw value
    pub values: BTreeMap<String, Json>,
    /// Newest first.
    pub events: VecDeque<EventView>,
    /// Topic -> last published payload.
    pub published: BTreeMap<String, Json>,
}

#[derive(Clone, Serialize)]
pub struct EventView {
    pub topic: String,
    pub payload: Json,
}

struct NodeState {
    label: Option<String>,
    view: NodeView,
    /// Raw values by path, for name resolution and info payloads.
    raw: HashMap<(u16, u32, u32), Json>,
    /// While `publish_all` runs: every topic it produced, to find stale ones.
    touched: Option<HashSet<String>>,
    /// The current or last OTA update, published on `<prefix>/<device>/ota`.
    ota: Option<OtaStatus>,
}

/// How one announce-and-serve attempt of an OTA update ended.
enum Attempt {
    Done(std::result::Result<(), String>),
    /// The device didn't start: announce again.
    Again,
}

/// The one OTA update that may run at a time.
struct OtaJob {
    node_id: u64,
    /// Since when the device has been reporting Idle (None: busy).
    idle_since: Option<Instant>,
    /// The device has reported Downloading (or later) in this update.
    downloading: bool,
    /// Set by a cancel; the job's task then ends with this error.
    cancelled: Option<String>,
    cancel: Arc<Notify>,
}

pub struct Hub {
    pub controller: MatterController,
    pub cfg: Config,
    mqtt: Option<Mqtt>,
    nodes: Mutex<HashMap<u64, NodeState>>,
    tasks: Mutex<HashMap<u64, JoinHandle<()>>>,
    /// Lock order: `nodes` before `ota_job`.
    ota_job: Mutex<Option<OtaJob>>,
}

impl Hub {
    pub fn new(controller: MatterController, cfg: Config, mqtt: Option<Mqtt>) -> Arc<Self> {
        Arc::new(Self {
            controller,
            cfg,
            mqtt,
            nodes: Mutex::default(),
            tasks: Mutex::default(),
            ota_job: Mutex::default(),
        })
    }

    pub fn node(&self, node_id: u64) -> Node {
        self.controller.node(node_id)
    }

    pub fn watermark_file(&self, node_id: u64) -> PathBuf {
        self.cfg.state_dir.join(format!("events-{node_id}.txt"))
    }

    pub fn start(self: &Arc<Self>, node_id: u64, label: Option<String>) {
        self.nodes.lock().unwrap().insert(
            node_id,
            NodeState { label, view: NodeView::default(), raw: HashMap::new(), touched: None, ota: None },
        );
        let task = tokio::spawn(Watcher::new(self.clone(), node_id).run());
        if let Some(old) = self.tasks.lock().unwrap().insert(node_id, task) {
            old.abort();
        }
    }

    /// Stops the watcher; dropping its subscription cancels it on the device.
    pub fn stop(&self, node_id: u64) {
        if let Some(t) = self.tasks.lock().unwrap().remove(&node_id) {
            t.abort();
        }
        self.online(node_id, false);
    }

    /// Clean shutdown: every node goes offline (the broker's last will only
    /// covers `<prefix>/status`).
    pub fn shutdown(&self) {
        let ids: Vec<u64> = self.tasks.lock().unwrap().keys().copied().collect();
        for id in ids {
            self.stop(id);
        }
    }

    pub fn view(&self, node_id: u64) -> NodeView {
        self.nodes
            .lock()
            .unwrap()
            .get(&node_id)
            .map(|n| n.view.clone())
            .unwrap_or_default()
    }

    // ---- input from the watcher -------------------------------------------

    pub fn online(&self, node_id: u64, online: bool) {
        let mut nodes = self.nodes.lock().unwrap();
        let Some(n) = nodes.get_mut(&node_id) else { return };
        n.view.online = online;
        let topic = format!("{}/{}/online", self.cfg.prefix, device_name(node_id, n));
        self.publish(n, topic, json!(online));
        // Applying, then gone: the device is rebooting into the bootloader, which installs the image
        if !online && n.ota.as_ref().is_some_and(|o| o.state == "applying") {
            self.update_ota(node_id, n, |o| o.state = "installing".into());
        }
    }

    pub fn attribute(&self, node_id: u64, p: AttributePath, value: Json) {
        let mut nodes = self.nodes.lock().unwrap();
        let Some(n) = nodes.get_mut(&node_id) else { return };
        let key = (p.endpoint, p.cluster, p.attribute);
        if n.raw.get(&key) == Some(&value) {
            return;
        }
        n.raw.insert(key, value.clone());
        n.view
            .values
            .insert(format!("{}/{:04x}/{:04x}", p.endpoint, p.cluster, p.attribute), value.clone());
        if p.endpoint == 0
            && p.cluster == ota::REQUESTOR
            && matches!(p.attribute, ota::UPDATE_STATE | ota::UPDATE_STATE_PROGRESS)
        {
            self.ota_device_report(node_id, n);
        }
        if self.cfg.raw {
            let topic = format!(
                "{}/raw/{node_id}/{}/{:04x}/{:04x}",
                self.cfg.prefix, p.endpoint, p.cluster, p.attribute
            );
            self.publish(n, topic, value.clone());
        }
        if !n.view.ready {
            return;
        }
        let renames = p.cluster == BRIDGED_DEVICE && matches!(p.attribute, NODE_LABEL | UNIQUE_ID);
        if renames {
            // Topics depend on endpoint names: publish everything under the new names.
            self.publish_all(node_id, n);
        } else if is_info(p) {
            self.publish_info(node_id, n, p.endpoint);
        } else if let Some(prop) = mapping::attribute(p.cluster, p.attribute) {
            let topic = format!("{}/{}", endpoint_topic(&self.cfg.prefix, node_id, n, p.endpoint), prop.name);
            self.publish(n, topic, mapping::convert(prop.conv, &value));
        }
    }

    pub fn event(&self, node_id: u64, endpoint: u16, cluster: u32, event: u32, raw: Json) {
        let mut nodes = self.nodes.lock().unwrap();
        let Some(n) = nodes.get_mut(&node_id) else { return };
        let data = raw.get("data").cloned().unwrap_or(Json::Null);
        let (topic, payload) = match mapping::event(cluster, event, &data) {
            Some((name, payload)) => {
                let base = if endpoint == 0 {
                    format!("{}/{}", self.cfg.prefix, device_name(node_id, n))
                } else {
                    endpoint_topic(&self.cfg.prefix, node_id, n, endpoint)
                };
                (format!("{base}/event/{name}"), payload)
            }
            None => (
                format!("{}/raw/{node_id}/{endpoint}/{cluster:04x}/event/{event:04x}", self.cfg.prefix),
                raw,
            ),
        };
        n.view.events.push_front(EventView { topic: topic.clone(), payload: payload.clone() });
        n.view.events.truncate(KEEP_EVENTS);
        // Events are never deduplicated (each one happened) nor retained.
        if !topic.contains("/raw/") || self.cfg.raw {
            self.send(&topic, payload_text(&payload), false);
        }
    }

    /// The first complete read is done: from now on names are known.
    pub fn ready(&self, node_id: u64) {
        let mut nodes = self.nodes.lock().unwrap();
        let Some(n) = nodes.get_mut(&node_id) else { return };
        n.view.ready = true;
        self.publish_all(node_id, n);
    }

    // ---- publishing -------------------------------------------------------

    /// Only changes go out; the resync reads would otherwise repeat everything.
    fn publish(&self, n: &mut NodeState, topic: String, payload: Json) {
        if let Some(t) = &mut n.touched {
            t.insert(topic.clone());
        }
        if n.view.published.get(&topic) == Some(&payload) {
            return;
        }
        self.send(&topic, payload_text(&payload), true);
        n.view.published.insert(topic, payload);
    }

    fn send(&self, topic: &str, payload: String, retain: bool) {
        if self.cfg.print {
            println!("{topic} {payload}");
        }
        if let Some(m) = &self.mqtt {
            m.publish(topic, payload, retain);
        }
    }

    /// Deletes retained topics on the broker.
    fn clear(&self, n: &mut NodeState, topics: Vec<String>) {
        for topic in topics {
            self.send(&topic, String::new(), true);
            n.view.published.remove(&topic);
        }
    }

    /// After an MQTT (re)connect: send the complete retained state again.
    pub fn republish(&self) {
        for n in self.nodes.lock().unwrap().values() {
            for (topic, payload) in &n.view.published {
                self.send(topic, payload_text(payload), true);
            }
        }
    }

    /// Publishes everything of a node and deletes retained topics it no
    /// longer produces (a renamed device or endpoint).
    fn publish_all(&self, node_id: u64, n: &mut NodeState) {
        n.touched = Some(HashSet::new());
        self.publish_all_inner(node_id, n);
        let touched = n.touched.take().unwrap_or_default();
        let stale: Vec<String> = n
            .view
            .published
            .keys()
            .filter(|t| !t.contains("/raw/") && !touched.contains(*t))
            .cloned()
            .collect();
        self.clear(n, stale);
    }

    fn publish_all_inner(&self, node_id: u64, n: &mut NodeState) {
        let mut endpoints: Vec<u16> = n.raw.keys().map(|k| k.0).collect();
        endpoints.sort_unstable();
        endpoints.dedup();
        for ep in endpoints {
            self.publish_info(node_id, n, ep);
        }
        let mut mapped: Vec<(String, Json)> = n
            .raw
            .iter()
            .filter_map(|(&(ep, cl, at), v)| {
                let prop = mapping::attribute(cl, at)?;
                Some((
                    format!("{}/{}", endpoint_topic(&self.cfg.prefix, node_id, n, ep), prop.name),
                    mapping::convert(prop.conv, v),
                ))
            })
            .collect();
        mapped.sort_by(|a, b| a.0.cmp(&b.0));
        for (topic, payload) in mapped {
            self.publish(n, topic, payload);
        }
        let online = n.view.online;
        let topic = format!("{}/{}/online", self.cfg.prefix, device_name(node_id, n));
        self.publish(n, topic, json!(online));
        if let Some(status) = n.ota.clone() {
            self.publish(n, ota_topic(&self.cfg.prefix, node_id, n), json!(status));
        }
    }

    /// Retained metadata: BasicInformation for the device (endpoint 0),
    /// BridgedDeviceBasicInformation + device types for an endpoint that has
    /// at least one mapped attribute.
    fn publish_info(&self, node_id: u64, n: &mut NodeState, ep: u16) {
        let get = |cl: u32, at: u32| n.raw.get(&(ep, cl, at)).cloned();
        let mut info = Map::new();
        let mut put = |k: &str, v: Option<Json>| {
            if let Some(v) = v.filter(|v| !v.is_null() && v != &json!("")) {
                info.insert(k.into(), v);
            }
        };
        let topic = if ep == 0 {
            put("node", Some(json!(node_id)));
            put("vendor", get(BASIC_INFORMATION, 0x0001));
            put("vendor_id", get(BASIC_INFORMATION, 0x0002));
            put("product", get(BASIC_INFORMATION, 0x0003));
            put("product_id", get(BASIC_INFORMATION, 0x0004));
            put("name", get(BASIC_INFORMATION, NODE_LABEL));
            put("hardware_version", get(BASIC_INFORMATION, 0x0008));
            put("software_version", get(BASIC_INFORMATION, 0x000a));
            put("serial", get(BASIC_INFORMATION, 0x000f));
            put("unique_id", get(BASIC_INFORMATION, UNIQUE_ID));
            format!("{}/{}/info", self.cfg.prefix, device_name(node_id, n))
        } else {
            let has_mapped = |e: u16| {
                n.raw.keys().any(|&(x, cl, at)| x == e && mapping::attribute(cl, at).is_some())
            };
            if !has_mapped(ep) {
                return;
            }
            // Endpoints of one physical device share a topic (see endpoint_topic):
            // one info for all of them.
            let topic = endpoint_topic(&self.cfg.prefix, node_id, n, ep);
            let mut group: Vec<u16> = n.raw.keys().map(|k| k.0).collect();
            group.sort_unstable();
            group.dedup();
            group.retain(|&e| has_mapped(e) && endpoint_topic(&self.cfg.prefix, node_id, n, e) == topic);
            let mut types: Vec<String> = Vec::new();
            for &e in &group {
                let list = n.raw.get(&(e, DESCRIPTOR, 0x0000)).and_then(Json::as_array);
                for t in list.into_iter().flatten().filter_map(|t| t.get("0")?.as_u64()) {
                    // bridged_node says nothing about the device itself
                    let t = mapping::device_type(t);
                    if t != "bridged_node" && !types.contains(&t) {
                        types.push(t);
                    }
                }
            }
            let first = |at: u32| group.iter().find_map(|&e| n.raw.get(&(e, BRIDGED_DEVICE, at)).cloned());
            put("endpoints", Some(json!(group)));
            put("device_types", Some(json!(types)));
            put("name", first(NODE_LABEL));
            put("vendor", first(0x0001));
            put("product", first(0x0003));
            put("hardware_version", first(0x0008));
            put("software_version", first(0x000a));
            put("serial", first(0x000f));
            put("unique_id", first(UNIQUE_ID));
            format!("{topic}/info")
        };
        self.publish(n, topic, Json::Object(info));
    }

    // ---- management -------------------------------------------------------

    pub async fn commission(self: &Arc<Self>, code: &str, label: Option<String>) -> Result<NodeInfo> {
        let info = self.controller.commission(code, label).await.context("commissioning")?;
        eprintln!("commissioned node {}", info.node_id);
        self.start(info.node_id, info.label.clone());
        Ok(info)
    }

    /// Removes our fabric from the device (it stays paired with every other
    /// ecosystem) and forgets the node. `local_only` skips the device, for one
    /// that is gone for good.
    pub async fn remove(self: &Arc<Self>, node_id: u64, local_only: bool) -> Result<()> {
        let label = self.nodes.lock().unwrap().get(&node_id).and_then(|n| n.label.clone());
        self.stop(node_id);
        if !local_only {
            if let Err(e) = remove_own_fabric(&self.node(node_id)).await {
                self.start(node_id, label);
                return Err(e);
            }
        }
        self.controller.forget_node(node_id).await?;
        if let Some(mut n) = self.nodes.lock().unwrap().remove(&node_id) {
            let topics = n.view.published.keys().cloned().collect();
            self.clear(&mut n, topics);
        }
        std::fs::remove_file(self.watermark_file(node_id)).ok();
        eprintln!("removed node {node_id}{}", if local_only { " (local only)" } else { "" });
        Ok(())
    }
}

impl Hub {
    // ---- OTA updates (OTA_PLAN.md phase 5) ---------------------------------

    /// The device name used in topics.
    pub fn device_name(&self, node_id: u64) -> Option<String> {
        self.nodes.lock().unwrap().get(&node_id).map(|n| device_name(node_id, n))
    }

    pub fn ota_status(&self, node_id: u64) -> Option<OtaStatus> {
        self.nodes.lock().unwrap().get(&node_id).and_then(|n| n.ota.clone())
    }

    /// Starts serving `image` to the node. Checks first that the device is
    /// online, has an OTA requestor, is the image's vendor and product, and
    /// runs an older version. Only one update runs at a time.
    pub fn start_ota(self: &Arc<Self>, node_id: u64, image: OtaImage) -> Result<OtaStatus> {
        let mut nodes = self.nodes.lock().unwrap();
        let n = nodes.get_mut(&node_id).with_context(|| format!("unknown node {node_id}"))?;
        let mut job = self.ota_job.lock().unwrap();
        if let Some(j) = job.as_ref() {
            bail!("an update is already running (node {})", j.node_id);
        }
        ensure!(n.view.online, "the device is offline");
        let num = |at: u32| n.raw.get(&(0, BASIC_INFORMATION, at)).and_then(Json::as_u64);
        let (vid, pid) = (num(0x0002), num(0x0004));
        ensure!(
            vid == Some(image.vendor_id.into()) && pid == Some(image.product_id.into()),
            "the image is for {:04x}:{:04x}, the device is {}:{}",
            image.vendor_id,
            image.product_id,
            vid.map_or("?".into(), |v| format!("{v:04x}")),
            pid.map_or("?".into(), |v| format!("{v:04x}")),
        );
        let from = num(SOFTWARE_VERSION).and_then(|v| u32::try_from(v).ok());
        if let Some(current) = from {
            ensure!(
                image.version > current,
                "the device already runs version {current}, the image is {} (it must be higher)",
                image.version
            );
        }
        ensure!(
            n.raw.contains_key(&(0, ota::REQUESTOR, ota::UPDATE_STATE)),
            "the device has no OTA Software Update Requestor (cluster 0x002A on endpoint 0)"
        );

        let since = SystemTime::now().duration_since(UNIX_EPOCH).map_or(0, |d| d.as_secs());
        let status = OtaStatus {
            state: "announcing".into(),
            attempt: 1,
            progress: None,
            from,
            to: image.version,
            to_string: image.version_string.clone(),
            error: None,
            since,
        };
        self.put_ota(node_id, n, Some(status.clone()));
        let cancel = Arc::new(Notify::new());
        *job = Some(OtaJob {
            node_id,
            idle_since: Some(Instant::now()),
            downloading: false,
            cancelled: None,
            cancel: cancel.clone(),
        });
        drop(job);
        drop(nodes);
        eprintln!(
            "{}/{node_id}: OTA to version {} ({}), {} bytes",
            self.cfg.prefix,
            image.version,
            image.version_string,
            image.bytes.len()
        );

        let hub = self.clone();
        tokio::spawn(async move {
            let deadline = tokio::time::Instant::now() + OTA_TIMEOUT;
            let mut attempt = 1;
            let result = loop {
                if let Some(j) = hub.ota_job.lock().unwrap().as_mut() {
                    j.idle_since = Some(Instant::now());
                }
                let serve = hub.controller.serve_ota_with_block_size(
                    node_id,
                    image.bytes.clone(),
                    image.version,
                    hub.cfg.ota_port,
                    OTA_BLOCK_SIZE,
                );
                let outcome = tokio::select! {
                    r = serve => Attempt::Done(r.map_err(|e| e.to_string())),
                    () = cancel.notified() => Attempt::Done(Err(hub.cancel_reason())),
                    a = hub.ota_watchdog(node_id) => a,
                    () = tokio::time::sleep_until(deadline) => Attempt::Done(Err("timed out".into())),
                };
                match outcome {
                    Attempt::Done(r) => break r,
                    Attempt::Again if attempt >= OTA_ATTEMPTS => {
                        break Err(format!(
                            "the device didn't start the download after {attempt} announcements (see its log)"
                        ));
                    }
                    Attempt::Again => {
                        attempt += 1;
                        eprintln!("{}/{node_id}: OTA: the device stays idle, announcing again ({attempt})", hub.cfg.prefix);
                        hub.ota_attempt(node_id, attempt);
                        tokio::select! {
                            () = tokio::time::sleep(Duration::from_secs(10)) => {}
                            () = cancel.notified() => break Err(hub.cancel_reason()),
                        }
                    }
                }
            };
            hub.finish_ota(node_id, since, result);
        });
        Ok(status)
    }

    fn cancel_reason(&self) -> String {
        let job = self.ota_job.lock().unwrap();
        job.as_ref().and_then(|j| j.cancelled.clone()).unwrap_or_else(|| "cancelled".into())
    }

    /// Ends an attempt once the device has stayed idle too long: announce
    /// again before the download has started, give up after. Idle as far as
    /// the subscription knows is confirmed by a read first: the device drops
    /// our sessions before it queries the provider (gateway_ota.cpp), so its
    /// reports stop until the watcher has resubscribed.
    async fn ota_watchdog(&self, node_id: u64) -> Attempt {
        loop {
            tokio::time::sleep(Duration::from_secs(5)).await;
            let (downloading, idle) = {
                let job = self.ota_job.lock().unwrap();
                let Some(j) = job.as_ref() else { continue };
                (j.downloading, j.idle_since.map(|t| t.elapsed()))
            };
            let limit = if downloading { OTA_IDLE_LIMIT } else { OTA_RETRY_IDLE };
            if !idle.is_some_and(|i| i > limit) {
                continue;
            }
            match self.read_update_state(node_id).await {
                Some(1) => {}
                state => {
                    // Busy (or no answer): it isn't idle, count again from now
                    let name = state.map_or("no answer", ota::update_state_name);
                    eprintln!("{}/{node_id}: OTA: the device is not idle ({name})", self.cfg.prefix);
                    if let Some(j) = self.ota_job.lock().unwrap().as_mut() {
                        j.idle_since = Some(Instant::now());
                        j.downloading |= matches!(state, Some(4..=6));
                    }
                    continue;
                }
            }
            return if downloading {
                Attempt::Done(Err("the device stopped the update (see its log)".into()))
            } else {
                Attempt::Again
            };
        }
    }

    /// UpdateState straight from the device; None if it doesn't answer in time.
    async fn read_update_state(&self, node_id: u64) -> Option<u64> {
        let paths = [ReadPath::concrete(0, ota::REQUESTOR, ota::UPDATE_STATE)];
        let node = self.node(node_id);
        match tokio::time::timeout(Duration::from_secs(20), node.read(&paths)).await {
            Ok(Ok(values)) => values.iter().find_map(|(_, v)| match v {
                Value::Uint(u) => Some(*u),
                _ => None,
            }),
            _ => None,
        }
    }

    fn ota_attempt(&self, node_id: u64, attempt: u8) {
        let mut nodes = self.nodes.lock().unwrap();
        if let Some(n) = nodes.get_mut(&node_id) {
            self.update_ota(node_id, n, |o| {
                o.state = "announcing".into();
                o.attempt = attempt;
            });
        }
    }

    /// Stops the running update of a node (the device may need a moment to
    /// notice: its download then times out).
    pub fn cancel_ota(&self, node_id: u64) -> Result<()> {
        let mut job = self.ota_job.lock().unwrap();
        let j = job.as_mut().filter(|j| j.node_id == node_id).context("no update running for this node")?;
        j.cancelled = Some("cancelled".into());
        j.cancel.notify_one();
        Ok(())
    }

    fn finish_ota(self: &Arc<Self>, node_id: u64, since: u64, result: Result<(), String>) {
        let mut nodes = self.nodes.lock().unwrap();
        *self.ota_job.lock().unwrap() = None;
        let Some(n) = nodes.get_mut(&node_id) else { return };
        // The device runs the new version although the provider saw no NotifyUpdateApplied
        let to = n.ota.as_ref().map(|o| u64::from(o.to));
        let running = n.raw.get(&(0, BASIC_INFORMATION, SOFTWARE_VERSION)).and_then(Json::as_u64);
        let result = if result.is_err() && to.is_some() && running == to { Ok(()) } else { result };
        match &result {
            Ok(()) => eprintln!("{}/{node_id}: OTA applied", self.cfg.prefix),
            Err(e) => eprintln!("{}/{node_id}: OTA failed: {e}", self.cfg.prefix),
        }
        self.update_ota(node_id, n, |o| match result {
            Ok(()) => {
                o.state = "applied".into();
                o.progress = Some(100);
            }
            Err(e) => {
                o.state = "failed".into();
                o.error = Some(e);
            }
        });
        drop(nodes);
        self.expire_ota(node_id, since);
    }

    /// A finished update's status disappears after a while, unless a newer
    /// update has replaced it.
    fn expire_ota(self: &Arc<Self>, node_id: u64, since: u64) {
        let hub = self.clone();
        tokio::spawn(async move {
            tokio::time::sleep(OTA_KEEP).await;
            let mut nodes = hub.nodes.lock().unwrap();
            let Some(n) = nodes.get_mut(&node_id) else { return };
            if n.ota.as_ref().is_some_and(|o| o.since == since && o.finished()) {
                hub.put_ota(node_id, n, None);
            }
        });
    }

    /// The device's requestor reported UpdateState / UpdateStateProgress.
    fn ota_device_report(&self, node_id: u64, n: &mut NodeState) {
        let running = n.ota.as_ref().is_some_and(|o| !o.finished());
        if !running {
            return;
        }
        let state = n.raw.get(&(0, ota::REQUESTOR, ota::UPDATE_STATE)).and_then(Json::as_u64);
        let progress = n
            .raw
            .get(&(0, ota::REQUESTOR, ota::UPDATE_STATE_PROGRESS))
            .and_then(Json::as_u64)
            .and_then(|p| u8::try_from(p).ok());
        let name = state.map_or("unknown", ota::update_state_name);
        if let Some(j) = self.ota_job.lock().unwrap().as_mut().filter(|j| j.node_id == node_id) {
            j.idle_since = if name == "idle" { j.idle_since.or(Some(Instant::now())) } else { None };
            j.downloading |= matches!(name, "downloading" | "applying" | "delayed_on_apply");
        }
        self.update_ota(node_id, n, |o| {
            // Before the device starts, it's still Idle: keep "announcing"
            if name != "idle" && name != "unknown" {
                o.state = name.into();
            }
            if name == "downloading" || progress.is_some() {
                o.progress = progress;
            }
        });
    }

    fn update_ota(&self, node_id: u64, n: &mut NodeState, f: impl FnOnce(&mut OtaStatus)) {
        let Some(mut status) = n.ota.clone() else { return };
        f(&mut status);
        self.put_ota(node_id, n, Some(status));
    }

    /// Sets (retained) or clears the node's OTA status.
    fn put_ota(&self, node_id: u64, n: &mut NodeState, status: Option<OtaStatus>) {
        let topic = ota_topic(&self.cfg.prefix, node_id, n);
        n.ota = status.clone();
        match status {
            Some(s) => self.publish(n, topic, json!(s)),
            None => self.clear(n, vec![topic]),
        }
    }

    /// `<prefix>/<device>/ota/set` {"file": "name.ota"}: an update from the
    /// OTA directory. Retained messages are ignored, so a forgotten one can't
    /// start an update on every reconnect.
    pub fn mqtt_message(self: &Arc<Self>, topic: &str, payload: &[u8], retain: bool) {
        let Some(device) = topic
            .strip_prefix(&format!("{}/", self.cfg.prefix))
            .and_then(|t| t.strip_suffix("/ota/set"))
        else {
            return;
        };
        if retain {
            eprintln!("mqtt: ignoring retained {topic} (send it without the retain flag)");
            return;
        }
        let node_id = {
            let nodes = self.nodes.lock().unwrap();
            nodes.iter().find(|(id, n)| device_name(**id, n) == device).map(|(id, _)| *id)
        };
        let Some(node_id) = node_id else {
            eprintln!("mqtt: {topic}: no device named {device}");
            return;
        };
        let result = (|| -> Result<OtaStatus> {
            let req: serde_json::Value = serde_json::from_slice(payload).context("payload is not JSON")?;
            let file = req.get("file").and_then(Json::as_str).context(r#"expected {"file": "name.ota"}"#)?;
            ensure!(
                !file.is_empty() && !file.starts_with('.') && !file.contains(['/', '\\']),
                "file must be a plain name in the OTA directory"
            );
            let path = self.cfg.ota_dir.join(file);
            let bytes = std::fs::read(&path).with_context(|| format!("reading {}", path.display()))?;
            self.start_ota(node_id, OtaImage::parse(bytes)?)
        })();
        if let Err(e) = result {
            eprintln!("mqtt: {topic}: {e:#}");
            // Report it where the update's status would be, unless one is running
            let busy = self.ota_job.lock().unwrap().as_ref().is_some_and(|j| j.node_id == node_id);
            if !busy {
                let since = SystemTime::now().duration_since(UNIX_EPOCH).map_or(0, |d| d.as_secs());
                let mut nodes = self.nodes.lock().unwrap();
                if let Some(n) = nodes.get_mut(&node_id) {
                    let status = OtaStatus {
                        state: "failed".into(),
                        attempt: 0,
                        progress: None,
                        from: None,
                        to: 0,
                        to_string: String::new(),
                        error: Some(format!("{e:#}")),
                        since,
                    };
                    self.put_ota(node_id, n, Some(status));
                }
                drop(nodes);
                self.expire_ota(node_id, since);
            }
        }
    }
}

fn ota_topic(prefix: &str, node_id: u64, n: &NodeState) -> String {
    format!("{prefix}/{}/ota", device_name(node_id, n))
}

fn is_info(p: AttributePath) -> bool {
    p.cluster == BASIC_INFORMATION
        || p.cluster == BRIDGED_DEVICE && mapping::attribute(p.cluster, p.attribute).is_none()
        || (p.cluster, p.attribute) == (DESCRIPTOR, 0x0000)
}

/// Commissioning label, else the device's own NodeLabel / ProductName.
fn device_name(node_id: u64, n: &NodeState) -> String {
    let from_device = [NODE_LABEL, 0x0003]
        .iter()
        .filter_map(|&at| n.raw.get(&(0, BASIC_INFORMATION, at))?.as_str())
        .find(|s| !s.is_empty());
    let name = n.label.as_deref().or(from_device).map(mapping::slug).unwrap_or_default();
    if name.is_empty() { format!("node-{node_id}") } else { name }
}

/// `<prefix>/<device>/<endpoint name>`. The endpoint name is the bridged
/// device's NodeLabel; endpoints of one physical device (same UniqueID, e.g. a
/// sensor split into temperature and humidity endpoints) share it. Different
/// devices with the same label get the endpoint number appended.
fn endpoint_topic(prefix: &str, node_id: u64, n: &NodeState, ep: u16) -> String {
    let label = |e: u16| {
        n.raw
            .get(&(e, BRIDGED_DEVICE, NODE_LABEL))
            .and_then(Json::as_str)
            .map(mapping::slug)
            .filter(|s| !s.is_empty())
    };
    let uid = |e: u16| n.raw.get(&(e, BRIDGED_DEVICE, UNIQUE_ID)).cloned();
    let name = match label(ep) {
        None => format!("ep{ep}"),
        Some(name) => {
            let clash = n.raw.keys().any(|&(e, cl, at)| {
                e != ep
                    && (cl, at) == (BRIDGED_DEVICE, NODE_LABEL)
                    && label(e).as_deref() == Some(name.as_str())
                    && (uid(e).is_none() || uid(e) != uid(ep))
            });
            if clash { format!("{name}-{ep}") } else { name }
        }
    };
    format!("{prefix}/{}/{name}", device_name(node_id, n))
}

/// MQTT payload text: strings without quotes, everything else as JSON.
pub fn payload_text(v: &Json) -> String {
    match v {
        Json::String(s) => s.clone(),
        other => other.to_string(),
    }
}

/// `RemoveFabric` with our own fabric index. The library's
/// `Node::remove_fabric` deliberately refuses that, it is meant for removing
/// *other* admins.
async fn remove_own_fabric(node: &Node) -> Result<()> {
    let cur = node
        .read(&[ReadPath::concrete(0, OPERATIONAL_CREDENTIALS, CURRENT_FABRIC_INDEX)])
        .await
        .context("reading our fabric index")?;
    let Some((_, Value::Uint(index))) = cur.first() else {
        bail!("device did not report CurrentFabricIndex");
    };
    let fields = Value::Structure(vec![(Tag::Context(0), Value::Uint(*index))]);
    let path = CommandPath {
        endpoint: 0,
        cluster: OPERATIONAL_CREDENTIALS,
        command: CMD_REMOVE_FABRIC,
    };
    match node.invoke(path, fields).await.context("RemoveFabric")? {
        // NOCResponse: StatusCode (tag 0), 0 = OK.
        InvokeResult::Data { fields, .. } => match noc_status(&fields) {
            Some(0) => Ok(()),
            status => bail!("device rejected RemoveFabric (NOC status {status:?})"),
        },
        InvokeResult::Status(ImStatus::Success) => Ok(()),
        other => bail!("unexpected RemoveFabric result: {other:?}"),
    }
}

fn noc_status(v: &Value) -> Option<u64> {
    let Value::Structure(m) = v else { return None };
    m.iter().find_map(|(t, v)| match (t, v) {
        (Tag::Context(0), Value::Uint(s)) => Some(*s),
        _ => None,
    })
}
