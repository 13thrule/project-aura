//! Aura Trigger (Pico) serial ingestion.
//!
//! Reads JSON lines from the Pico's USB serial port and turns each into
//! an `AuraEvent::Trigger`, stamped with this host's own receipt time.
//! Handles BOTH firmware variants in hardware/pico_clicker/:
//!   - `main.py`         — `{"event", "ticks_ms", "device"}`
//!   - `provenance_main.py` — `{"seq", "event", "ticks_us", "chain_hash", "device"}`
//!
//! These two protocols disagree on the timestamp field name AND unit
//! (`ticks_ms` vs `ticks_us`) — an earlier version of this file required
//! `ticks_ms`, which meant every line from `provenance_main.py` failed
//! to deserialize and was silently dropped by the `Err(_) => continue`
//! branch below, not just missing its seq/chain_hash fields. Both fields
//! are optional here and reconciled to a single millisecond value before
//! publishing, specifically to not repeat that.
//!
//! The Pico's `rtc_time` field is deliberately dropped, not read — see
//! the caveat in hardware/pico_clicker/main.py: the Pico has no
//! battery-backed RTC, so its wall-clock is untrustworthy until a
//! sync-on-boot handshake exists. `ticks_ms`/`ticks_us` (monotonic) plus
//! this host's own receive timestamp is the trustworthy pairing for now.
//! `PicoEvent` below has no field for `rtc_time` on purpose.
//!
//! `chain_hash` is propagated through to `AuraEvent::Trigger` and on to
//! the dashboard (see broker/src/dashboard.rs) for DISPLAY only — this
//! file does not verify the hash chain. Verifying it requires
//! recomputing sha256(prev_chain_hash_bytes + payload_bytes) and
//! tracking prev_chain_hash across events, matching
//! provenance_main.py's exact payload format byte-for-byte — real,
//! doable work, just not done in this pass. Don't let "chain_hash is
//! displayed" get mistaken for "chain_hash is verified."

use std::io::BufRead;
use std::time::{Duration, SystemTime};

use serde::Deserialize;

use crate::AuraEvent;

const BAUD_RATE: u32 = 115200;

#[derive(Debug, Deserialize)]
struct PicoEvent {
    event: String,
    #[serde(default)]
    seq: Option<u32>,
    #[serde(default)]
    ticks_ms: Option<u64>,
    #[serde(default)]
    ticks_us: Option<u64>,
    #[serde(default)]
    chain_hash: Option<String>,
    #[serde(default)]
    #[allow(dead_code)] // not consumed yet; kept for future debug logging
    device: Option<String>,
    // NOTE: no `rtc_time` field — see module doc.
}

/// Parses one line of Pico serial output into an `AuraEvent::Trigger`,
/// or `None` for anything that isn't an accepted `AURA_TRIGGER` line
/// (malformed JSON, the Pico's own startup status line, or an event of
/// a different type).
fn parse_trigger_line(line: &str, host_received_at: SystemTime) -> Option<AuraEvent> {
    let parsed: PicoEvent = serde_json::from_str(line).ok()?;
    if parsed.event != "AURA_TRIGGER" {
        return None;
    }

    // main.py sends ticks_ms directly; provenance_main.py sends ticks_us
    // (integer-divided down to ms here — lossy, but every consumer
    // downstream of this point works in ms). A line with neither is
    // malformed; skip it rather than publish a bogus 0.
    let pico_ticks_ms = match (parsed.ticks_ms, parsed.ticks_us) {
        (Some(ms), _) => ms,
        (None, Some(us)) => us / 1000,
        (None, None) => return None,
    };

    Some(AuraEvent::Trigger {
        pico_ticks_ms,
        host_received_at,
        seq: parsed.seq,
        chain_hash: parsed.chain_hash,
        // The EXACT ticks_us value, not the /1000 conversion above —
        // chain-hash verification needs the same bytes the Pico actually
        // hashed (provenance_main.py's payload string is
        // "{seq}:{ticks_us}:AURA_TRIGGER", built from this raw value).
        // None for main.py's protocol, which has no chain to verify.
        chain_ticks_us: parsed.ticks_us,
    })
}

/// Reads lines from the Pico's serial port until the port closes or a
/// read error occurs, publishing one `AuraEvent::Trigger` per accepted
/// `AURA_TRIGGER` line.
///
/// Uses BLOCKING I/O (the plain `serialport` crate) on a dedicated OS
/// thread, bridged into the async broadcast channel via an mpsc channel
/// — deliberately NOT `tokio-serial`'s async API. Confirmed on real
/// hardware that the async approach opens the port without error but
/// then never receives a single byte (`next_line().await` hangs
/// forever). This is a real, documented limitation, not a config
/// mistake: modern Tokio (1.0+) removed the Windows-compatible async
/// polling primitive (`PollEvented`) that `tokio-serial` relied on, and
/// there is currently no Windows equivalent of the Unix-only `AsyncFd`
/// that replaced it — see berkowski/tokio-serial issues #29 and #37,
/// and tokio-rs/tokio issue #3396. Several other things were tried and
/// ruled out first by testing, not assumed: DTR/RTS state (toggled both
/// ways via a controlled pyserial test — data flowed regardless, so not
/// the cause) and explicit 8N1/no-flow-control parameters (matched
/// pyserial's defaults exactly — still zero bytes with the async API).
pub async fn run(
    port: &str,
    tx: tokio::sync::broadcast::Sender<AuraEvent>,
) -> anyhow::Result<()> {
    let (line_tx, mut line_rx) = tokio::sync::mpsc::unbounded_channel::<String>();
    let port_owned = port.to_string();

    std::thread::spawn(move || {
        let serial = match serialport::new(&port_owned, BAUD_RATE)
            .timeout(Duration::from_millis(500))
            .open()
        {
            Ok(p) => p,
            Err(e) => {
                eprintln!("[trigger] failed to open {port_owned}: {e}");
                return;
            }
        };
        let mut reader = std::io::BufReader::new(serial);
        loop {
            let mut line = String::new();
            match reader.read_line(&mut line) {
                Ok(0) => break, // port closed / EOF
                Ok(_) => {
                    let trimmed = line.trim();
                    if !trimmed.is_empty() && line_tx.send(trimmed.to_string()).is_err() {
                        break; // async side hung up
                    }
                }
                // A read timeout just means no data arrived in the
                // window — expected between button presses, not an
                // error. Anything else (device unplugged etc.) is fatal
                // to this thread.
                Err(e) if e.kind() == std::io::ErrorKind::TimedOut => continue,
                Err(e) => {
                    eprintln!("[trigger] read error on {port_owned}: {e}");
                    break;
                }
            }
        }
    });

    while let Some(line) = line_rx.recv().await {
        let host_received_at = SystemTime::now();
        if let Some(event) = parse_trigger_line(&line, host_received_at) {
            // A send error here just means no subscribers are listening
            // right now (e.g. storage not wired up yet) — not a reason
            // to stop reading the trigger stream.
            let _ = tx.send(event);
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn parse(json: &str) -> Option<PicoEvent> {
        serde_json::from_str(json).ok()
    }

    #[test]
    fn parses_main_py_protocol() {
        let json = r#"{"event":"AURA_TRIGGER","ticks_ms":12345,"device":"PICO_CLICKER_V1"}"#;
        let p = parse(json).expect("main.py protocol must parse");
        assert_eq!(p.ticks_ms, Some(12345));
        assert_eq!(p.ticks_us, None);
        assert_eq!(p.seq, None);
        assert_eq!(p.chain_hash, None);
    }

    #[test]
    fn parses_provenance_main_py_protocol() {
        let json = r#"{"seq":7,"event":"AURA_TRIGGER","ticks_us":9876543,"chain_hash":"abcd1234","device":"PICO_CLICKER_V1"}"#;
        let p = parse(json).expect("provenance_main.py protocol must parse — this is exactly the case that used to be silently dropped");
        assert_eq!(p.ticks_ms, None);
        assert_eq!(p.ticks_us, Some(9876543));
        assert_eq!(p.seq, Some(7));
        assert_eq!(p.chain_hash.as_deref(), Some("abcd1234"));
    }

    #[test]
    fn provenance_ticks_us_reconciles_to_ms() {
        let json = r#"{"seq":1,"event":"AURA_TRIGGER","ticks_us":9876543,"chain_hash":"x"}"#;
        let p = parse(json).unwrap();
        let ms = match (p.ticks_ms, p.ticks_us) {
            (Some(ms), _) => ms,
            (None, Some(us)) => us / 1000,
            (None, None) => panic!("neither field present"),
        };
        assert_eq!(ms, 9876); // 9876543us / 1000
    }

    #[test]
    fn startup_status_line_is_not_a_trigger() {
        let json = r#"{"status": "Aura Trigger initialized and waiting..."}"#;
        // No "event" field at all -> fails to deserialize into PicoEvent
        // (event: String is required) -> run()'s Err(_) => continue skips it.
        assert!(parse(json).is_none());
    }
}
