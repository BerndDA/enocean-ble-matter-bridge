//! Matter OTA updates served to our own nodes (OTA_PLAN.md, phase 5): the
//! `.ota` file format and the status published per device under
//! `<prefix>/<device>/ota`. The update itself runs in [`crate::hub::Hub`].

use anyhow::{Context, Result, bail, ensure};
use matter_codec::{Tag, TlvReader, Value};
use serde::Serialize;

/// OTA Software Update Requestor cluster on endpoint 0 of a device.
pub const REQUESTOR: u32 = 0x002a;
pub const UPDATE_STATE: u32 = 0x0002;
pub const UPDATE_STATE_PROGRESS: u32 = 0x0003;

const MAGIC: u32 = 0x1bee_f11e;

/// A parsed `.ota` file (Matter Core §11.21.3).
pub struct OtaImage {
    pub vendor_id: u16,
    pub product_id: u16,
    pub version: u32,
    pub version_string: String,
    pub payload_size: u64,
    /// The whole file, header included: that's what BDX serves.
    pub bytes: Vec<u8>,
}

impl OtaImage {
    pub fn parse(bytes: Vec<u8>) -> Result<Self> {
        ensure!(bytes.len() >= 16, "not an .ota file (too short)");
        let u32_at = |o: usize| u32::from_le_bytes(bytes[o..o + 4].try_into().unwrap());
        ensure!(u32_at(0) == MAGIC, "not an .ota file (magic {:08x})", u32_at(0));
        let total = u64::from_le_bytes(bytes[4..12].try_into().unwrap());
        ensure!(total == bytes.len() as u64, "truncated .ota file: {} of {total} bytes", bytes.len());
        let header_len = u32_at(12) as usize;
        let header = bytes.get(16..16 + header_len).context("truncated .ota header")?;
        let (_, Value::Structure(fields)) = TlvReader::new(header).read_value().context(".ota header TLV")? else {
            bail!(".ota header is not a TLV structure");
        };
        let get = |n: u8| fields.iter().find(|(t, _)| *t == Tag::Context(n)).map(|(_, v)| v);
        let uint = |n: u8, what: &str| match get(n) {
            Some(Value::Uint(u)) => Ok(*u),
            _ => bail!(".ota header without {what}"),
        };
        let image = Self {
            vendor_id: u16::try_from(uint(0, "vendor id")?)?,
            product_id: u16::try_from(uint(1, "product id")?)?,
            version: u32::try_from(uint(2, "software version")?)?,
            version_string: match get(3) {
                Some(Value::Utf8(s)) => s.clone(),
                _ => String::new(),
            },
            payload_size: uint(4, "payload size")?,
            bytes,
        };
        ensure!(
            16 + header_len as u64 + image.payload_size == total,
            ".ota payload size doesn't match the file"
        );
        Ok(image)
    }
}

/// Published retained on `<prefix>/<device>/ota` while an update runs and
/// for a while after it ended.
#[derive(Clone, Serialize, PartialEq, Debug)]
pub struct OtaStatus {
    /// announcing, querying, downloading, applying, installing (the device is
    /// rebooting into the bootloader), applied, failed
    pub state: String,
    /// Announcement number (the device is asked again when it doesn't start).
    pub attempt: u8,
    /// Download progress in percent, from the device.
    pub progress: Option<u8>,
    /// Software versions: what the device ran when the update started, and
    /// what it is being updated to.
    pub from: Option<u32>,
    pub to: u32,
    pub to_string: String,
    pub error: Option<String>,
    /// Unix seconds when the update started.
    pub since: u64,
}

impl OtaStatus {
    pub fn finished(&self) -> bool {
        matches!(self.state.as_str(), "applied" | "failed")
    }
}

/// The device's UpdateStateEnum (Matter Core §11.20.7.4.15).
pub fn update_state_name(v: u64) -> &'static str {
    match v {
        1 => "idle",
        2 => "querying",
        3 => "delayed_on_query",
        4 => "downloading",
        5 => "applying",
        6 => "delayed_on_apply",
        7 => "rolling_back",
        8 => "delayed_on_user_consent",
        _ => "unknown",
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Header as connectedhomeip's ota_image_tool.py writes it.
    fn image(payload: &[u8]) -> Vec<u8> {
        let mut tlv = Vec::new();
        let mut w = matter_codec::TlvWriter::new(&mut tlv);
        w.start_structure(Tag::Anonymous).unwrap();
        w.put_uint(Tag::Context(0), 0xfff1).unwrap();
        w.put_uint(Tag::Context(1), 0x8003).unwrap();
        w.put_uint(Tag::Context(2), 0x10001).unwrap();
        w.put_utf8(Tag::Context(3), "0.1.0+1").unwrap();
        w.put_uint(Tag::Context(4), payload.len() as u64).unwrap();
        w.put_uint(Tag::Context(8), 1).unwrap();
        w.put_bytes(Tag::Context(9), &[0u8; 32]).unwrap();
        w.end_container().unwrap();
        let mut out = MAGIC.to_le_bytes().to_vec();
        out.extend_from_slice(&((16 + tlv.len() + payload.len()) as u64).to_le_bytes());
        out.extend_from_slice(&(tlv.len() as u32).to_le_bytes());
        out.extend_from_slice(&tlv);
        out.extend_from_slice(payload);
        out
    }

    #[test]
    fn parses_header() {
        let img = OtaImage::parse(image(&[1, 2, 3, 4, 5])).unwrap();
        assert_eq!((img.vendor_id, img.product_id, img.version), (0xfff1, 0x8003, 0x10001));
        assert_eq!(img.version_string, "0.1.0+1");
        assert_eq!(img.payload_size, 5);
    }

    #[test]
    fn rejects_bad_files() {
        assert!(OtaImage::parse(b"not an ota file at all".to_vec()).is_err());
        let mut truncated = image(&[1, 2, 3]);
        truncated.pop();
        assert!(OtaImage::parse(truncated).is_err());
    }
}
