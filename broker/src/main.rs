//! aura-broker — local data broker for Project Aura.
//!
//! Design doc: docs/DESIGN_DOCUMENT.md section 3.1.
//!
//! Responsibilities, in priority order:
//!   1. Read the Cyton's 250Hz serial stream without dropping frames.
//!   2. Fan that stream out to (a) local storage and (b) the dashboard,
//!      without either consumer's slowness affecting ingestion.
//!   3. Read Aura Trigger timestamps from the Pico's serial port and merge
//!      them into the same event stream.
//!
//! Wiring status: `trigger.rs`, `dashboard.rs`, and `storage.rs` all have
//! real, tested implementations and are wired up below — verified
//! end-to-end against a real Pico (2026-08-27): a real button press flows
//! through trigger ingestion, gets durably written by storage, and shows
//! up live in a real browser dashboard, all three at once. `cyton.rs`
//! (blocked on a local BrainFlow build — see broker/README.md) is the
//! only piece still not wired in.

mod cyton;
mod trigger;
mod storage;
mod dashboard;
mod replay;

use std::env;

use tokio::sync::broadcast;

/// A single decoded sample tick from the Cyton, or a trigger event from
/// the Pico. Kept as one enum so storage and dashboard consume one
/// ordered stream rather than reconciling two.
#[derive(Debug, Clone)]
pub enum AuraEvent {
    Sample(cyton::Sample),
    Trigger {
        pico_ticks_ms: u64,
        host_received_at: std::time::SystemTime,
        // All three below are only present for
        // hardware/pico_clicker/provenance_main.py's richer protocol —
        // None for the plain main.py firmware. See trigger.rs's module
        // doc. chain_ticks_us is the raw value the Pico actually hashed
        // into chain_hash — needed to verify it, distinct from
        // pico_ticks_ms above which is derived/lossy for that purpose.
        seq: Option<u32>,
        chain_hash: Option<String>,
        chain_ticks_us: Option<u64>,
    },
    /// Broadcast by `replay.rs` while (and only while) it's streaming a
    /// recorded file instead of live hardware — see its module doc for
    /// why this exists and why it repeats rather than firing once.
    ReplayStatus { label: String },
    /// A real, externally-sourced ground-truth annotation crossing —
    /// e.g. entering/leaving a clinician-verified seizure interval from
    /// a CHB-MIT recording, per `AURA_REPLAY_ANNOTATIONS_CSV` (see
    /// replay.rs). NOT a live detection: `is_start` distinguishes
    /// entering vs leaving the interval, `at_recording_seconds` is the
    /// timestamp within the source recording (matches the dataset's own
    /// summary file), and `label` names what kind of annotation this is
    /// and where it came from, so the dashboard can never present this
    /// as if the system detected it live.
    Annotation {
        label: String,
        is_start: bool,
        at_recording_seconds: f64,
        host_received_at: std::time::SystemTime,
    },
}

const DEFAULT_DASHBOARD_ADDR: &str = "127.0.0.1:9001";
// Relative to the crate root (broker/), matching how `cargo run` is
// normally invoked from this directory — see broker/README.md. Override
// with AURA_DATA_DIR if running from somewhere else.
const DEFAULT_DATA_DIR: &str = "../data/raw";

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // Broadcast channel is the fan-out point: storage and dashboard each
    // get their own receiver, neither can block the other or block
    // ingestion. Capacity needs real tuning once we know actual bytes/sec
    // and dashboard consumption rate — 4096 is a placeholder.
    let (tx, _rx) = broadcast::channel::<AuraEvent>(4096);

    let dashboard_addr =
        env::var("AURA_DASHBOARD_ADDR").unwrap_or_else(|_| DEFAULT_DASHBOARD_ADDR.to_string());
    println!("aura-broker: dashboard will listen on ws://{dashboard_addr}");

    let dashboard_rx = tx.subscribe();
    let dashboard_handle = tokio::spawn(async move {
        if let Err(e) = dashboard::serve(dashboard_rx, &dashboard_addr).await {
            eprintln!("aura-broker: dashboard server exited with error: {e:#}");
        }
    });

    let data_dir = env::var("AURA_DATA_DIR").unwrap_or_else(|_| DEFAULT_DATA_DIR.to_string());
    let storage_rx = tx.subscribe();
    let storage_handle = tokio::spawn(async move {
        if let Err(e) = storage::run(storage_rx, &data_dir).await {
            eprintln!("aura-broker: storage exited with error: {e:#}");
        }
    });

    let trigger_handle = match env::var("AURA_PICO_SERIAL_PORT") {
        Ok(port) => {
            println!("aura-broker: Aura Trigger ingestion on {port}");
            let trigger_tx = tx.clone();
            Some(tokio::spawn(async move {
                if let Err(e) = trigger::run(&port, trigger_tx).await {
                    eprintln!("aura-broker: trigger ingestion exited with error: {e:#}");
                }
            }))
        }
        Err(_) => {
            println!(
                "aura-broker: AURA_PICO_SERIAL_PORT not set — Aura Trigger ingestion disabled \
                 (set it to e.g. COM5 or /dev/ttyACM0 once a Pico is connected)."
            );
            None
        }
    };

    // AURA_REPLAY_CSV streams a real recorded file (from
    // pipeline/tools/export_replay_csv.py) through the same Sample event
    // path cyton.rs will eventually use once BrainFlow is built — see
    // replay.rs's module doc. This is deliberately separate from cyton.rs
    // rather than a fake board id or mock: replaying real data and
    // acquiring live data are different enough operations (and different
    // enough safety postures — see replay.rs) that conflating them behind
    // one code path would be the wrong shape even once Cyton support lands.
    let replay_handle = match env::var("AURA_REPLAY_CSV") {
        Ok(csv_path) => {
            let sample_rate_hz: f64 = env::var("AURA_REPLAY_SAMPLE_RATE_HZ")
                .ok()
                .and_then(|v| v.parse().ok())
                .unwrap_or(256.0); // CHB-MIT's native rate
            let speed: f64 = env::var("AURA_REPLAY_SPEED")
                .ok()
                .and_then(|v| v.parse().ok())
                .unwrap_or(1.0);
            let label = env::var("AURA_REPLAY_LABEL").unwrap_or_else(|_| csv_path.clone());
            let annotations_csv = env::var("AURA_REPLAY_ANNOTATIONS_CSV").ok();
            let replay_tx = tx.clone();
            Some(tokio::spawn(async move {
                if let Err(e) = replay::run(&csv_path, sample_rate_hz, speed, label, annotations_csv, replay_tx).await {
                    eprintln!("aura-broker: replay exited with error: {e:#}");
                }
            }))
        }
        Err(_) => None,
    };

    println!(
        "aura-broker: Cyton ingestion (cyton.rs) is not wired up yet — see design doc sections \
         3.1 and 9, and broker/README.md for the BrainFlow local-build prerequisite. Aura \
         Trigger events, storage, and the dashboard socket are all live in this build. Set \
         AURA_REPLAY_CSV to a file from pipeline/tools/export_replay_csv.py to exercise the \
         pipeline with real recorded EEG in the meantime (see broker/README.md)."
    );

    let mut handles = vec![dashboard_handle, storage_handle];
    if let Some(h) = trigger_handle {
        handles.push(h);
    }
    if let Some(h) = replay_handle {
        handles.push(h);
    }
    futures_util::future::join_all(handles).await;

    Ok(())
}
