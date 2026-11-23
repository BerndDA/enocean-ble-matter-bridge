//! Thread mesh snapshot for the web UI: every node's neighbor and route table
//! from Thread Network Diagnostics (0x0035), plus its own extended address
//! from General Diagnostics NetworkInterfaces (0x0033/0x0000, HardwareAddress).
//!
//! Extended addresses are sent as hex strings: they are u64 and would lose
//! precision as JSON numbers in the browser.

use std::sync::Arc;
use std::time::Duration;

use anyhow::{Context, Result};
use matter_controller::ReadPath;
use serde::Serialize;
use serde_json::Value as Json;

use crate::hub::Hub;

const GENERAL_DIAGNOSTICS: u32 = 0x0033;
const NETWORK_INTERFACES: u32 = 0x0000;
const INTERFACE_TYPE_THREAD: u64 = 4;

const THREAD_DIAGNOSTICS: u32 = 0x0035;
const CHANNEL: u32 = 0x0000;
const ROUTING_ROLE: u32 = 0x0001;
const NETWORK_NAME: u32 = 0x0002;
const NEIGHBOR_TABLE: u32 = 0x0007;
const ROUTE_TABLE: u32 = 0x0008;
const PARTITION_ID: u32 = 0x0009;
const LEADER_ROUTER_ID: u32 = 0x000d;

const READ_TIMEOUT: Duration = Duration::from_secs(20);

#[derive(Serialize, Default)]
pub struct ThreadNode {
    pub node_id: u64,
    pub name: String,
    pub online: bool,
    pub error: Option<String>,
    /// Own extended address (hex), from NetworkInterfaces.
    pub ext_address: Option<String>,
    /// unspecified, unassigned, sleepy_end_device, end_device, reed, router, leader
    pub role: Option<String>,
    /// Own RLOC16, from the route table's self entry (routers only).
    pub rloc16: Option<u64>,
    pub channel: Option<u64>,
    pub network_name: Option<String>,
    pub partition_id: Option<u64>,
    pub leader_router_id: Option<u64>,
    pub neighbors: Vec<Neighbor>,
    pub routes: Vec<Route>,
}

#[derive(Serialize)]
pub struct Neighbor {
    pub ext_address: String,
    pub rloc16: u64,
    pub age: Option<u64>,
    /// 0-3, as seen by this node.
    pub lqi: Option<u64>,
    pub avg_rssi: Option<i64>,
    pub last_rssi: Option<i64>,
    /// Percent.
    pub frame_error_rate: Option<u64>,
    pub message_error_rate: Option<u64>,
    pub rx_on_when_idle: bool,
    pub full_thread_device: bool,
    pub is_child: bool,
}

#[derive(Serialize)]
pub struct Route {
    pub ext_address: String,
    pub rloc16: u64,
    pub router_id: u64,
    pub next_hop: u64,
    pub path_cost: u64,
    pub lqi_in: u64,
    pub lqi_out: u64,
    pub age: u64,
    pub allocated: bool,
    pub link_established: bool,
}

/// Reads all nodes in parallel; a node that fails or times out keeps its
/// `error` and empty tables.
pub async fn snapshot(hub: &Arc<Hub>, nodes: Vec<(u64, String)>) -> Vec<ThreadNode> {
    let tasks: Vec<_> = nodes
        .into_iter()
        .map(|(id, name)| {
            let hub = hub.clone();
            tokio::spawn(async move {
                let online = hub.view(id).online;
                let mut t = ThreadNode { node_id: id, name, online, ..Default::default() };
                match tokio::time::timeout(READ_TIMEOUT, read(&hub, id, &mut t)).await {
                    Ok(Ok(())) => {}
                    Ok(Err(e)) => t.error = Some(format!("{e:#}")),
                    Err(_) => t.error = Some("timeout".into()),
                }
                t
            })
        })
        .collect();
    let mut out = Vec::new();
    for task in tasks {
        if let Ok(t) = task.await {
            out.push(t);
        }
    }
    out
}

async fn read(hub: &Hub, id: u64, t: &mut ThreadNode) -> Result<()> {
    let paths: Vec<ReadPath> = [
        (GENERAL_DIAGNOSTICS, NETWORK_INTERFACES),
        (THREAD_DIAGNOSTICS, CHANNEL),
        (THREAD_DIAGNOSTICS, ROUTING_ROLE),
        (THREAD_DIAGNOSTICS, NETWORK_NAME),
        (THREAD_DIAGNOSTICS, NEIGHBOR_TABLE),
        (THREAD_DIAGNOSTICS, ROUTE_TABLE),
        (THREAD_DIAGNOSTICS, PARTITION_ID),
        (THREAD_DIAGNOSTICS, LEADER_ROUTER_ID),
    ]
    .iter()
    .map(|&(c, a)| ReadPath::concrete(0, c, a))
    .collect();
    let values = hub.node(id).read(&paths).await.context("read")?;

    for (p, v) in values {
        let v = crate::tlv::to_json(&v);
        match (p.cluster, p.attribute) {
            (GENERAL_DIAGNOSTICS, NETWORK_INTERFACES) => {
                t.ext_address = v
                    .as_array()
                    .into_iter()
                    .flatten()
                    .find(|i| u(i, 7) == Some(INTERFACE_TYPE_THREAD))
                    .and_then(|i| i.get("4")?.as_str().map(str::to_owned));
            }
            (THREAD_DIAGNOSTICS, CHANNEL) => t.channel = v.as_u64(),
            (THREAD_DIAGNOSTICS, ROUTING_ROLE) => t.role = v.as_u64().map(role_name),
            (THREAD_DIAGNOSTICS, NETWORK_NAME) => t.network_name = v.as_str().map(str::to_owned),
            (THREAD_DIAGNOSTICS, PARTITION_ID) => t.partition_id = v.as_u64(),
            (THREAD_DIAGNOSTICS, LEADER_ROUTER_ID) => t.leader_router_id = v.as_u64(),
            (THREAD_DIAGNOSTICS, NEIGHBOR_TABLE) => {
                t.neighbors = v.as_array().into_iter().flatten().map(neighbor).collect();
            }
            (THREAD_DIAGNOSTICS, ROUTE_TABLE) => {
                t.routes = v.as_array().into_iter().flatten().map(route).collect();
            }
            _ => {}
        }
    }
    // The own entry in the route table: no next hop (63), no cost, no link.
    t.rloc16 = t
        .routes
        .iter()
        .find(|r| r.next_hop == 63 && r.path_cost == 0 && !r.link_established)
        .map(|r| r.rloc16);
    Ok(())
}

fn u(v: &Json, field: u8) -> Option<u64> {
    v.get(field.to_string())?.as_u64()
}

fn i(v: &Json, field: u8) -> Option<i64> {
    v.get(field.to_string())?.as_i64()
}

fn b(v: &Json, field: u8) -> bool {
    v.get(field.to_string()).and_then(Json::as_bool).unwrap_or(false)
}

fn ext(v: &Json) -> String {
    format!("{:016x}", u(v, 0).unwrap_or(0))
}

fn neighbor(v: &Json) -> Neighbor {
    Neighbor {
        ext_address: ext(v),
        age: u(v, 1),
        rloc16: u(v, 2).unwrap_or(0),
        lqi: u(v, 5),
        avg_rssi: i(v, 6),
        last_rssi: i(v, 7),
        frame_error_rate: u(v, 8),
        message_error_rate: u(v, 9),
        rx_on_when_idle: b(v, 10),
        full_thread_device: b(v, 11),
        is_child: b(v, 13),
    }
}

fn route(v: &Json) -> Route {
    Route {
        ext_address: ext(v),
        rloc16: u(v, 1).unwrap_or(0),
        router_id: u(v, 2).unwrap_or(0),
        next_hop: u(v, 3).unwrap_or(63),
        path_cost: u(v, 4).unwrap_or(0),
        lqi_in: u(v, 5).unwrap_or(0),
        lqi_out: u(v, 6).unwrap_or(0),
        age: u(v, 7).unwrap_or(0),
        allocated: b(v, 8),
        link_established: b(v, 9),
    }
}

fn role_name(r: u64) -> String {
    match r {
        0 => "unspecified",
        1 => "unassigned",
        2 => "sleepy_end_device",
        3 => "end_device",
        4 => "reed",
        5 => "router",
        6 => "leader",
        _ => "unknown",
    }
    .into()
}
