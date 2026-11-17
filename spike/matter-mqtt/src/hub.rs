//! Shared state: the controller, one watcher task per node, the raw values per
//! node and what has been published. Raw values come in through
//! [`Hub::attribute`] / [`Hub::event`]; the hub maps them to readable topics
//! (see `mapping`) and hands them to [`Hub::publish`], which prints them
//! (later: publishes them to MQTT, retained).

use std::collections::{BTreeMap, HashMap, VecDeque};
use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use anyhow::{Context, Result, bail};
use matter_codec::Tag;
use matter_controller::{
    AttributePath, CommandPath, ImStatus, InvokeResult, MatterController, Node, NodeInfo,
    ReadPath, Value,
};
use serde::Serialize;
use serde_json::{Map, Value as Json, json};
use tokio::task::JoinHandle;

use crate::mapping;
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

pub struct Config {
    pub prefix: String,
    pub state_dir: PathBuf,
    pub max_interval: u16,
    pub all: bool,
    /// Also publish every raw value under `<prefix>/raw/<node>/...`.
    pub raw: bool,
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
}

pub struct Hub {
    pub controller: MatterController,
    pub cfg: Config,
    nodes: Mutex<HashMap<u64, NodeState>>,
    tasks: Mutex<HashMap<u64, JoinHandle<()>>>,
}

impl Hub {
    pub fn new(controller: MatterController, cfg: Config) -> Arc<Self> {
        Arc::new(Self {
            controller,
            cfg,
            nodes: Mutex::default(),
            tasks: Mutex::default(),
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
            NodeState { label, view: NodeView::default(), raw: HashMap::new() },
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
        // Events are never deduplicated: each one happened.
        if !topic.contains("/raw/") || self.cfg.raw {
            println!("{topic} {}", payload_text(&payload));
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
        if n.view.published.get(&topic) == Some(&payload) {
            return;
        }
        println!("{topic} {}", payload_text(&payload));
        n.view.published.insert(topic, payload);
    }

    fn publish_all(&self, node_id: u64, n: &mut NodeState) {
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
        self.nodes.lock().unwrap().remove(&node_id);
        std::fs::remove_file(self.watermark_file(node_id)).ok();
        eprintln!("removed node {node_id}{}", if local_only { " (local only)" } else { "" });
        Ok(())
    }
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
