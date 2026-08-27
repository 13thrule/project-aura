//! WebSocket fan-out to the live dashboard (dashboard/).
//!
//! ## Wire format decision: binary for EEG samples, JSON text for events
//!
//! At 250Hz x 8 channels the EEG stream is ~2000 float values/sec.
//! JSON's per-message parsing and object-allocation overhead is real at
//! that rate, so `AuraEvent::Sample` is encoded as a fixed-layout binary
//! WebSocket frame (see `encode_sample_frame`) — the browser reads it
//! straight into a typed array with no JSON parse step. `AuraEvent`
//! trigger events are rare (a handful per session) and benefit far more
//! from being human-readable in devtools than from any perf gain, so
//! those stay JSON text frames (`encode_trigger_json`). A WebSocket
//! connection can freely mix binary and text frames — the JS client
//! branches on `typeof event.data` (see dashboard/index.html).
//!
//! Sample frame layout (little-endian, all fields explicit-endian via
//! `to_le_bytes`/`DataView.getFloat32(offset, true)` on the JS side —
//! deliberately not relying on host-native endianness matching, even
//! though in practice both sides are little-endian here):
//!
//! ```text
//! byte 0        : u8   frame tag = 0x01 (Sample)
//! byte 1        : u8   per-connection sequence number, wraps mod 256
//! bytes 2..10   : f64  host_received_at, unix epoch seconds
//! bytes 10..42  : f32 x 8  EEG channels
//! bytes 42..54  : f32 x 3  accelerometer
//! ```
//!
//! The sequence byte is per-WebSocket-connection (assigned by `serve`'s
//! per-connection loop below, not part of `Sample` itself) so the
//! dashboard can detect broker->browser network drops on its own
//! connection — a jump of more than 1 between consecutive sequence
//! numbers means that many frames were lost in transit. It wraps at 256,
//! which is fine for a UI health indicator; it is not a substitute for
//! `storage.rs`'s own unbroken record (design doc section 3.1).
//!
//! Not batched (one WS message per Sample event) — the natural next
//! optimization once real hardware exists and network chatter at 250
//! messages/sec is actually measured to matter, not before.

use futures_util::{SinkExt, StreamExt};
use tokio::net::TcpListener;
use tokio_tungstenite::tungstenite::Message;

use crate::{cyton::Sample, AuraEvent};

const SAMPLE_FRAME_TAG: u8 = 0x01;

pub fn encode_sample_frame(sample: &Sample, seq: u8) -> Vec<u8> {
    let mut buf = Vec::with_capacity(2 + 8 + 8 * 4 + 3 * 4);
    buf.push(SAMPLE_FRAME_TAG);
    buf.push(seq);

    let ts = sample
        .host_received_at
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs_f64();
    buf.extend_from_slice(&ts.to_le_bytes());

    for &c in &sample.channels {
        buf.extend_from_slice(&c.to_le_bytes());
    }
    for &a in &sample.accel {
        buf.extend_from_slice(&a.to_le_bytes());
    }

    debug_assert_eq!(buf.len(), 54);
    buf
}

/// Sent (repeatedly — see replay.rs) while a recorded file is being
/// streamed instead of live hardware, so the dashboard can show a
/// persistent "not live" banner rather than ever letting replayed data
/// look like a real-time patient stream.
pub fn encode_replay_status_json(label: &str) -> String {
    serde_json::json!({
        "type": "replay_status",
        "label": label,
    })
    .to_string()
}

/// A real, dataset-sourced ground-truth annotation crossing (see
/// replay.rs's module doc) — never a live detection. `is_start`
/// distinguishes entering vs leaving the interval.
pub fn encode_annotation_json(
    label: &str,
    is_start: bool,
    at_recording_seconds: f64,
    host_received_at: std::time::SystemTime,
) -> String {
    let host_ts = host_received_at
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs_f64();
    serde_json::json!({
        "type": "annotation",
        "label": label,
        "is_start": is_start,
        "at_recording_seconds": at_recording_seconds,
        "host_received_at": host_ts,
    })
    .to_string()
}

pub fn encode_trigger_json(
    pico_ticks_ms: u64,
    host_received_at: std::time::SystemTime,
    seq: Option<u32>,
    chain_hash: Option<String>,
    chain_ticks_us: Option<u64>,
) -> String {
    let host_ts = host_received_at
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs_f64();
    serde_json::json!({
        "type": "trigger",
        "pico_ticks_ms": pico_ticks_ms,
        "host_received_at": host_ts,
        // All three null for main.py's plain protocol. Present for
        // provenance_main.py's chained protocol — chain_ticks_us is
        // needed alongside seq/chain_hash for the dashboard to actually
        // recompute and verify the hash (see dashboard/index.html's
        // verifyChainedTrigger), not just display it.
        "seq": seq,
        "chain_hash": chain_hash,
        "chain_ticks_us": chain_ticks_us,
    })
    .to_string()
}

/// Accepts dashboard WebSocket connections and streams `AuraEvent`s to
/// each one until it disconnects. Each connection gets its own
/// broadcast subscription (`rx.resubscribe()`) so a slow dashboard tab
/// can lag or disconnect without affecting other consumers — per the
/// module doc in main.rs, this must never be able to block storage.
pub async fn serve(
    rx: tokio::sync::broadcast::Receiver<AuraEvent>,
    addr: &str,
) -> anyhow::Result<()> {
    let listener = TcpListener::bind(addr).await?;

    loop {
        let (stream, _peer_addr) = listener.accept().await?;
        let mut rx = rx.resubscribe();

        tokio::spawn(async move {
            let ws_stream = match tokio_tungstenite::accept_async(stream).await {
                Ok(s) => s,
                Err(_) => return,
            };
            let (mut write, _read) = ws_stream.split();
            // Per-connection frame counter for binary Sample frames only
            // (design doc / this file's wire-format doc comment) — not
            // to be confused with AuraEvent::Trigger's `seq`, which is
            // the Pico's own hash-chain sequence number, a different
            // thing entirely.
            let mut ws_frame_seq: u8 = 0;

            loop {
                match rx.recv().await {
                    Ok(AuraEvent::Sample(sample)) => {
                        let frame = encode_sample_frame(&sample, ws_frame_seq);
                        ws_frame_seq = ws_frame_seq.wrapping_add(1);
                        if write.send(Message::Binary(frame)).await.is_err() {
                            break;
                        }
                    }
                    Ok(AuraEvent::Trigger { pico_ticks_ms, host_received_at, seq, chain_hash, chain_ticks_us }) => {
                        let json = encode_trigger_json(pico_ticks_ms, host_received_at, seq, chain_hash, chain_ticks_us);
                        if write.send(Message::Text(json)).await.is_err() {
                            break;
                        }
                    }
                    Ok(AuraEvent::ReplayStatus { label }) => {
                        let json = encode_replay_status_json(&label);
                        if write.send(Message::Text(json)).await.is_err() {
                            break;
                        }
                    }
                    Ok(AuraEvent::Annotation { label, is_start, at_recording_seconds, host_received_at }) => {
                        let json = encode_annotation_json(&label, is_start, at_recording_seconds, host_received_at);
                        if write.send(Message::Text(json)).await.is_err() {
                            break;
                        }
                    }
                    // A lagged dashboard subscriber just missed some
                    // samples — that's fine, keep going. It must never
                    // affect storage's own subscription.
                    Err(tokio::sync::broadcast::error::RecvError::Lagged(_)) => continue,
                    Err(tokio::sync::broadcast::error::RecvError::Closed) => break,
                }
            }
        });
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sample_frame_round_trips() {
        let sample = Sample {
            host_received_at: std::time::UNIX_EPOCH + std::time::Duration::from_secs_f64(1_700_000_000.5),
            channels: [1.0, -2.5, 3.25, 0.0, -1.0, 42.0, -42.0, 7.5],
            accel: [0.1, -0.2, 0.3],
        };
        let buf = encode_sample_frame(&sample, 7);
        assert_eq!(buf.len(), 54);
        assert_eq!(buf[0], SAMPLE_FRAME_TAG);
        assert_eq!(buf[1], 7);

        let ts = f64::from_le_bytes(buf[2..10].try_into().unwrap());
        assert!((ts - 1_700_000_000.5).abs() < 1e-6);

        for (i, &expected) in sample.channels.iter().enumerate() {
            let offset = 10 + i * 4;
            let value = f32::from_le_bytes(buf[offset..offset + 4].try_into().unwrap());
            assert_eq!(value, expected);
        }
        for (i, &expected) in sample.accel.iter().enumerate() {
            let offset = 42 + i * 4;
            let value = f32::from_le_bytes(buf[offset..offset + 4].try_into().unwrap());
            assert_eq!(value, expected);
        }
    }

    #[test]
    fn trigger_json_has_expected_fields_basic_protocol() {
        let json = encode_trigger_json(
            12345,
            std::time::UNIX_EPOCH + std::time::Duration::from_secs(100),
            None,
            None,
            None,
        );
        let parsed: serde_json::Value = serde_json::from_str(&json).unwrap();
        assert_eq!(parsed["type"], "trigger");
        assert_eq!(parsed["pico_ticks_ms"], 12345);
        assert_eq!(parsed["host_received_at"], 100.0);
        assert!(parsed["seq"].is_null());
        assert!(parsed["chain_hash"].is_null());
        assert!(parsed["chain_ticks_us"].is_null());
    }

    #[test]
    fn trigger_json_has_expected_fields_provenance_protocol() {
        let json = encode_trigger_json(
            12345,
            std::time::UNIX_EPOCH + std::time::Duration::from_secs(100),
            Some(7),
            Some("abcd1234".to_string()),
            Some(9876543),
        );
        let parsed: serde_json::Value = serde_json::from_str(&json).unwrap();
        assert_eq!(parsed["seq"], 7);
        assert_eq!(parsed["chain_hash"], "abcd1234");
        assert_eq!(parsed["chain_ticks_us"], 9876543);
    }

    #[test]
    fn replay_status_json_has_expected_fields() {
        let json = encode_replay_status_json("chb01 / chb01_16.edf");
        let parsed: serde_json::Value = serde_json::from_str(&json).unwrap();
        assert_eq!(parsed["type"], "replay_status");
        assert_eq!(parsed["label"], "chb01 / chb01_16.edf");
    }

    #[test]
    fn annotation_json_has_expected_fields() {
        let json = encode_annotation_json(
            "seizure (chb01_16.edf, CHB-MIT ground-truth annotation)",
            true,
            1015.0,
            std::time::UNIX_EPOCH + std::time::Duration::from_secs(100),
        );
        let parsed: serde_json::Value = serde_json::from_str(&json).unwrap();
        assert_eq!(parsed["type"], "annotation");
        assert_eq!(parsed["label"], "seizure (chb01_16.edf, CHB-MIT ground-truth annotation)");
        assert_eq!(parsed["is_start"], true);
        assert_eq!(parsed["at_recording_seconds"], 1015.0);
        assert_eq!(parsed["host_received_at"], 100.0);
    }
}
