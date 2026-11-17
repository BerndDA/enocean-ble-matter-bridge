//! Which Matter attributes and events are published, under which name, and
//! how their values are converted. Everything not listed here is only visible
//! in the web UI (and under `<prefix>/raw/...` with `--raw`).

use serde_json::{Map, Value as Json, json};

/// How a raw value becomes the published one.
#[derive(Clone, Copy)]
pub enum Conv {
    Bool,
    /// Integer percent or other plain number.
    Plain,
    /// Divide by the factor and round to the decimals (°C in 0.01, % in 0.5, W in mW).
    Scale(f64, u32),
    /// Enum value -> name; unknown values stay numbers.
    Enum(&'static [(u64, &'static str)]),
}

pub struct Prop {
    pub name: &'static str,
    pub conv: Conv,
}

const LOCK_STATE: &[(u64, &str)] =
    &[(0, "not_fully_locked"), (1, "locked"), (2, "unlocked"), (3, "unlatched")];
const DOOR_STATE: &[(u64, &str)] = &[
    (0, "open"),
    (1, "closed"),
    (2, "jammed"),
    (3, "forced_open"),
    (4, "error"),
    (5, "ajar"),
];
const SYSTEM_MODE: &[(u64, &str)] = &[
    (0, "off"),
    (1, "auto"),
    (3, "cool"),
    (4, "heat"),
    (5, "emergency_heat"),
    (6, "precooling"),
    (7, "fan_only"),
    (8, "dry"),
    (9, "sleep"),
];
const BAT_CHARGE_LEVEL: &[(u64, &str)] = &[(0, "ok"), (1, "warning"), (2, "critical")];

pub fn attribute(cluster: u32, attribute: u32) -> Option<Prop> {
    use Conv::*;
    let (name, conv) = match (cluster, attribute) {
        (0x0006, 0x0000) => ("on", Bool),
        (0x0101, 0x0000) => ("lock_state", Enum(LOCK_STATE)),
        (0x0101, 0x0003) => ("door_state", Enum(DOOR_STATE)),
        (0x0201, 0x0000) => ("temperature", Scale(100.0, 1)),
        (0x0201, 0x0008) => ("heating_demand", Plain),
        (0x0201, 0x0012) => ("setpoint", Scale(100.0, 1)),
        (0x0201, 0x001c) => ("mode", Enum(SYSTEM_MODE)),
        (0x0402, 0x0000) => ("temperature", Scale(100.0, 1)),
        (0x0405, 0x0000) => ("humidity", Scale(100.0, 1)),
        (0x002f, 0x000c) => ("battery", Scale(2.0, 0)),
        (0x002f, 0x000e) => ("battery_level", Enum(BAT_CHARGE_LEVEL)),
        (0x0039, 0x0011) => ("reachable", Bool),
        (0x0090, 0x0004) => ("voltage", Scale(1000.0, 1)),
        (0x0090, 0x0005) => ("current", Scale(1000.0, 3)),
        (0x0090, 0x0008) => ("power", Scale(1000.0, 1)),
        _ => return None,
    };
    Some(Prop { name, conv })
}

pub fn convert(conv: Conv, v: &Json) -> Json {
    match (conv, v) {
        (_, Json::Null) => Json::Null,
        (Conv::Scale(f, decimals), Json::Number(n)) => {
            let x = n.as_f64().unwrap_or_default() / f;
            if decimals == 0 {
                json!(x.round() as i64)
            } else {
                let p = 10f64.powi(decimals as i32);
                json!((x * p).round() / p)
            }
        }
        (Conv::Enum(names), Json::Number(n)) => n
            .as_u64()
            .and_then(|i| names.iter().find(|(k, _)| *k == i))
            .map_or_else(|| v.clone(), |(_, s)| json!(s)),
        _ => v.clone(),
    }
}

const LOCK_OPERATION: &[(u64, &str)] = &[
    (0, "lock"),
    (1, "unlock"),
    (2, "non_access_user_event"),
    (3, "forced_user_event"),
    (4, "unlatch"),
];
const OPERATION_SOURCE: &[(u64, &str)] = &[
    (0, "unspecified"),
    (1, "manual"),
    (2, "proprietary_remote"),
    (3, "keypad"),
    (4, "auto"),
    (5, "button"),
    (6, "schedule"),
    (7, "remote"),
    (8, "rfid"),
    (9, "biometric"),
    (10, "aliro"),
];
const OPERATION_ERROR: &[(u64, &str)] = &[
    (0, "unspecified"),
    (1, "invalid_credential"),
    (2, "disabled_user_denied"),
    (3, "restricted"),
    (4, "insufficient_battery"),
];
const LOCK_ALARM: &[(u64, &str)] = &[
    (0, "lock_jammed"),
    (1, "lock_factory_reset"),
    (3, "lock_radio_power_cycled"),
    (4, "wrong_code_entry_limit"),
    (5, "front_escutcheon_removed"),
    (6, "door_forced_open"),
    (7, "door_ajar"),
    (8, "forced_user"),
];

/// A mapped event: its topic name and payload, built from the raw event data
/// (struct fields keyed by field id, see `tlv::to_json`).
pub fn event(cluster: u32, event: u32, data: &Json) -> Option<(&'static str, Json)> {
    let f = |id: &str, names: &'static [(u64, &'static str)]| {
        convert(Conv::Enum(names), data.get(id).unwrap_or(&Json::Null))
    };
    let raw = |id: &str| data.get(id).cloned().unwrap_or(Json::Null);
    let mut out = Map::new();
    let name = match (cluster, event) {
        (0x0028, 0x0000) => {
            out.insert("software_version".into(), raw("0"));
            "startup"
        }
        (0x0028, 0x0001) => "shutdown",
        (0x0101, 0x0000) => {
            out.insert("alarm".into(), f("0", LOCK_ALARM));
            "alarm"
        }
        (0x0101, 0x0001) => {
            out.insert("door_state".into(), f("0", DOOR_STATE));
            "door_state_change"
        }
        (0x0101, 0x0002) => {
            out.insert("operation".into(), f("0", LOCK_OPERATION));
            out.insert("source".into(), f("1", OPERATION_SOURCE));
            out.insert("user".into(), raw("2"));
            "lock_operation"
        }
        (0x0101, 0x0003) => {
            out.insert("operation".into(), f("0", LOCK_OPERATION));
            out.insert("source".into(), f("1", OPERATION_SOURCE));
            out.insert("error".into(), f("2", OPERATION_ERROR));
            "lock_operation_error"
        }
        _ => return None,
    };
    Some((name, Json::Object(out)))
}

pub fn device_type(id: u64) -> String {
    match id {
        0x000a => "door_lock",
        0x000e => "aggregator",
        0x0011 => "power_source",
        0x0013 => "bridged_node",
        0x0016 => "root_node",
        0x0100 => "on_off_light",
        0x0101 => "dimmable_light",
        0x010a => "on_off_plug",
        0x010b => "dimmable_plug",
        0x0301 => "thermostat",
        0x0302 => "temperature_sensor",
        0x0307 => "humidity_sensor",
        0x0510 => "electrical_sensor",
        _ => return format!("0x{id:04x}"),
    }
    .to_owned()
}

/// "Küche links 1" -> "kueche-links-1"
pub fn slug(s: &str) -> String {
    let mut out = String::new();
    for c in s.trim().to_lowercase().chars() {
        match c {
            'ä' => out.push_str("ae"),
            'ö' => out.push_str("oe"),
            'ü' => out.push_str("ue"),
            'ß' => out.push_str("ss"),
            c if c.is_ascii_alphanumeric() => out.push(c),
            _ if !out.ends_with('-') => out.push('-'),
            _ => {}
        }
    }
    out.trim_matches('-').to_owned()
}
