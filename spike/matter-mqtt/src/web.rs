//! REST API and the single-page UI.
//!
//! GET    /api/nodes                    nodes with online state and display name
//! GET    /api/nodes/{id}               values and recent events of one node
//! POST   /api/nodes                    {"code": "...", "label": "..."} commission
//! PUT    /api/nodes/{id}/fabric-label  {"label": "..."} our fabric's label on the device
//! DELETE /api/nodes/{id}[?local_only=true]  remove our fabric from the device
//! GET    /api/nodes/{id}/read?ep=&cluster=&attr=  debug read, omitted = wildcard
//! GET    /api/thread                   Thread neighbor/route tables of every node
//! POST   /api/nodes/{id}/ota           body: an .ota file; starts an OTA update
//! GET    /api/nodes/{id}/ota           status of the current or last update
//! DELETE /api/nodes/{id}/ota           cancels the running update
//! GET    /api/config                   topic prefix and MQTT WebSocket URL for the UI

use std::sync::Arc;

use axum::body::Bytes;
use axum::extract::{DefaultBodyLimit, Path, Query, State};
use axum::http::StatusCode;
use axum::response::{Html, IntoResponse, Response};
use axum::routing::{get, put};
use axum::{Json, Router};
use serde::{Deserialize, Serialize};
use serde_json::{Value as JsonValue, json};

use crate::hub::{Hub, NodeView};
use crate::ota::{OtaImage, OtaStatus};

/// Larger than any .ota for the 888 KB app area of the gateways.
const MAX_OTA_FILE: usize = 4 * 1024 * 1024;

pub fn router(hub: Arc<Hub>) -> Router {
    Router::new()
        .route("/", get(|| async { Html(include_str!("index.html")) }))
        .route("/api/nodes", get(list).post(commission))
        .route("/api/nodes/{id}", get(detail).delete(remove))
        .route("/api/nodes/{id}/fabric-label", put(fabric_label))
        .route("/api/nodes/{id}/read", get(read))
        .route("/api/thread", get(thread))
        .route(
            "/api/nodes/{id}/ota",
            get(ota_status).post(ota_start).delete(ota_cancel).layer(DefaultBodyLimit::max(MAX_OTA_FILE)),
        )
        .route("/api/config", get(config))
        .with_state(hub)
}

struct ApiError(StatusCode, String);

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        (self.0, Json(json!({ "error": self.1 }))).into_response()
    }
}

impl From<anyhow::Error> for ApiError {
    fn from(e: anyhow::Error) -> Self {
        Self(StatusCode::BAD_GATEWAY, format!("{e:#}"))
    }
}

impl From<matter_controller::Error> for ApiError {
    fn from(e: matter_controller::Error) -> Self {
        Self(StatusCode::BAD_GATEWAY, e.to_string())
    }
}

type ApiResult<T> = Result<T, ApiError>;

#[derive(Serialize)]
struct NodeSummary {
    node_id: u64,
    label: Option<String>,
    vendor_id: Option<u16>,
    product_id: Option<u16>,
    online: bool,
    /// BasicInformation NodeLabel, else ProductName.
    name: Option<JsonValue>,
    values: usize,
    /// The device's name in topics: `<prefix>/<device>/...`.
    device: Option<String>,
    /// BasicInformation SoftwareVersion and SoftwareVersionString.
    software_version: Option<JsonValue>,
    software_version_string: Option<JsonValue>,
    ota: Option<OtaStatus>,
}

async fn list(State(hub): State<Arc<Hub>>) -> ApiResult<Json<Vec<NodeSummary>>> {
    let nodes = hub.controller.nodes().await?;
    Ok(Json(
        nodes
            .into_iter()
            .map(|n| {
                let v = hub.view(n.node_id);
                let name = basic_name(&v).map(JsonValue::from);
                NodeSummary {
                    node_id: n.node_id,
                    label: n.label,
                    vendor_id: n.vendor_id,
                    product_id: n.product_id,
                    online: v.online,
                    name,
                    values: v.values.len(),
                    device: hub.device_name(n.node_id),
                    software_version: v.values.get("0/0028/0009").cloned(),
                    software_version_string: v.values.get("0/0028/000a").cloned(),
                    ota: hub.ota_status(n.node_id),
                }
            })
            .collect(),
    ))
}

/// BasicInformation NodeLabel, else ProductName.
fn basic_name(v: &NodeView) -> Option<String> {
    ["0/0028/0005", "0/0028/0003"]
        .iter()
        .filter_map(|k| v.values.get(*k)?.as_str())
        .find(|s| !s.is_empty())
        .map(str::to_owned)
}

async fn thread(State(hub): State<Arc<Hub>>) -> ApiResult<Json<Vec<crate::thread::ThreadNode>>> {
    let nodes = hub
        .controller
        .nodes()
        .await?
        .into_iter()
        .map(|n| {
            let name = n
                .label
                .or_else(|| basic_name(&hub.view(n.node_id)))
                .unwrap_or_else(|| format!("Node {}", n.node_id));
            (n.node_id, name)
        })
        .collect();
    Ok(Json(crate::thread::snapshot(&hub, nodes).await))
}

async fn detail(State(hub): State<Arc<Hub>>, Path(id): Path<u64>) -> ApiResult<Json<NodeView>> {
    known(&hub, id).await?;
    Ok(Json(hub.view(id)))
}

#[derive(Deserialize)]
struct CommissionReq {
    code: String,
    label: Option<String>,
}

async fn commission(
    State(hub): State<Arc<Hub>>,
    Json(req): Json<CommissionReq>,
) -> ApiResult<impl IntoResponse> {
    let code = req.code.trim().replace('-', "").replace(' ', "");
    let label = req.label.filter(|l| !l.trim().is_empty());
    let info = hub.commission(&code, label).await?;
    Ok((
        StatusCode::CREATED,
        Json(json!({ "node_id": info.node_id, "vendor_id": info.vendor_id, "product_id": info.product_id })),
    ))
}

#[derive(Deserialize)]
struct LabelReq {
    label: String,
}

async fn fabric_label(
    State(hub): State<Arc<Hub>>,
    Path(id): Path<u64>,
    Json(req): Json<LabelReq>,
) -> ApiResult<StatusCode> {
    known(&hub, id).await?;
    if req.label.len() > 32 {
        return Err(ApiError(StatusCode::BAD_REQUEST, "label is limited to 32 bytes".into()));
    }
    hub.node(id).update_fabric_label(&req.label).await?;
    Ok(StatusCode::NO_CONTENT)
}

#[derive(Deserialize)]
struct RemoveQuery {
    #[serde(default)]
    local_only: bool,
}

async fn remove(
    State(hub): State<Arc<Hub>>,
    Path(id): Path<u64>,
    Query(q): Query<RemoveQuery>,
) -> ApiResult<StatusCode> {
    known(&hub, id).await?;
    hub.remove(id, q.local_only).await?;
    Ok(StatusCode::NO_CONTENT)
}

async fn known(hub: &Hub, id: u64) -> ApiResult<()> {
    if hub.controller.nodes().await?.iter().any(|n| n.node_id == id) {
        Ok(())
    } else {
        Err(ApiError(StatusCode::NOT_FOUND, format!("unknown node {id}")))
    }
}

#[derive(Deserialize)]
struct ReadQuery {
    ep: Option<u16>,
    /// Decimal or 0x-prefixed hex.
    cluster: Option<String>,
    attr: Option<String>,
}

fn num(s: &Option<String>) -> ApiResult<Option<u32>> {
    s.as_deref()
        .map(|s| match s.strip_prefix("0x") {
            Some(h) => u32::from_str_radix(h, 16),
            None => s.parse(),
        })
        .transpose()
        .map_err(|e| ApiError(StatusCode::BAD_REQUEST, e.to_string()))
}

async fn read(
    State(hub): State<Arc<Hub>>,
    Path(id): Path<u64>,
    Query(q): Query<ReadQuery>,
) -> ApiResult<Json<serde_json::Map<String, JsonValue>>> {
    known(&hub, id).await?;
    let path = matter_controller::ReadPath::new(q.ep, num(&q.cluster)?, num(&q.attr)?);
    let values = hub.node(id).read(&[path]).await?;
    Ok(Json(
        values
            .into_iter()
            .map(|(p, v)| {
                (format!("{}/{:04x}/{:04x}", p.endpoint, p.cluster, p.attribute), crate::tlv::to_json(&v))
            })
            .collect(),
    ))
}

async fn ota_start(
    State(hub): State<Arc<Hub>>,
    Path(id): Path<u64>,
    body: Bytes,
) -> ApiResult<impl IntoResponse> {
    known(&hub, id).await?;
    let image = OtaImage::parse(body.to_vec()).map_err(|e| ApiError(StatusCode::BAD_REQUEST, format!("{e:#}")))?;
    let status = hub.start_ota(id, image).map_err(|e| ApiError(StatusCode::CONFLICT, format!("{e:#}")))?;
    Ok((StatusCode::ACCEPTED, Json(status)))
}

async fn ota_status(State(hub): State<Arc<Hub>>, Path(id): Path<u64>) -> ApiResult<Json<Option<OtaStatus>>> {
    known(&hub, id).await?;
    Ok(Json(hub.ota_status(id)))
}

async fn ota_cancel(State(hub): State<Arc<Hub>>, Path(id): Path<u64>) -> ApiResult<StatusCode> {
    known(&hub, id).await?;
    hub.cancel_ota(id).map_err(|e| ApiError(StatusCode::CONFLICT, format!("{e:#}")))?;
    Ok(StatusCode::NO_CONTENT)
}

async fn config(State(hub): State<Arc<Hub>>) -> Json<JsonValue> {
    Json(json!({ "prefix": hub.cfg.prefix, "mqtt_ws": hub.cfg.mqtt_ws }))
}
