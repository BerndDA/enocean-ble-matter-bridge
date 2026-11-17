//! TLV -> JSON for MQTT payloads and the web UI.

use matter_codec::Tag;
use matter_controller::Value;
use serde_json::{Map, Value as Json, json};

/// Struct members are keyed by their field id (context tag) from the cluster
/// spec; octet strings become hex.
pub fn to_json(v: &Value) -> Json {
    match v {
        Value::Bool(b) => json!(b),
        Value::Uint(u) => json!(u),
        Value::Int(i) => json!(i),
        Value::Float(f) => json!(f),
        Value::Double(d) => json!(d),
        Value::Utf8(s) => json!(s),
        Value::Bytes(b) => json!(b.iter().map(|x| format!("{x:02x}")).collect::<String>()),
        Value::Array(items) => Json::Array(items.iter().map(to_json).collect()),
        Value::Structure(members) | Value::List(members) => {
            if members.iter().all(|(t, _)| matches!(t, Tag::Anonymous)) {
                return Json::Array(members.iter().map(|(_, v)| to_json(v)).collect());
            }
            let mut m = Map::new();
            for (i, (t, v)) in members.iter().enumerate() {
                let key = match t {
                    Tag::Anonymous => i.to_string(),
                    Tag::Context(n) => n.to_string(),
                    other => format!("{other:?}"),
                };
                m.insert(key, to_json(v));
            }
            Json::Object(m)
        }
        Value::Null => Json::Null,
        #[allow(unreachable_patterns)]
        other => json!(format!("{other:?}")),
    }
}
