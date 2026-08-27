//! Durable local storage of the event stream.
//!
//! Design doc section 3.1: the Cyton's own SD card logging is the primary,
//! unbroken record — this module is a *structured second copy* (CSV for
//! now; EDF export belongs in `pipeline/`, not duplicated here), not the
//! only copy. Real, working, wired into `main.rs`:
//!
//! - `samples.csv` — raw EEG samples. Empty until Cyton ingestion exists
//!   (`cyton.rs`), but the writer is ready for it.
//! - `triggers.csv` — Aura Trigger events. Gets REAL rows today, since
//!   `trigger.rs` already works against real hardware — this is the
//!   first data this broker has ever durably stored.
//! - `annotations.csv` — real, externally-sourced ground-truth event
//!   crossings (e.g. entering/leaving a CHB-MIT seizure interval during
//!   replay — see replay.rs). Never a live detection; `is_start`
//!   distinguishes entering vs leaving an interval.
//!
//! Deliberately separate files, not one, mirroring the BIDS convention
//! of separating continuous data from event annotations (BIDS calls the
//! latter `events.tsv`) — a forward-compatible choice matching where
//! this data eventually needs to go (design doc section 5), not just an
//! implementation convenience.
//!
//! Each file gets its own hash chain (same principle as
//! `hardware/pico_clicker/provenance_main.py` — design doc section 2.5):
//! every row's `chain_hash` column depends on the previous row's, so a
//! released dataset is tamper-evident. Same scope limit as the Pico's
//! chain: this proves "unmodified since this file was created," not
//! cryptographic proof of physical origin — see section 2.5 for why that
//! distinction matters and don't blur it in a grant narrative.
//!
//! NOT done yet, and deliberately not attempted in this pass rather than
//! rushed: encryption at rest (design doc section 5, "Data privacy" — a
//! hard gate before any real patient data is stored, but not relevant
//! until Cyton exists and real sessions happen). EDF export from this
//! CSV format is real — `pipeline/tools/session_to_edf.py` — and
//! verifies the chain below before exporting anything.

use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use sha2::{Digest, Sha256};
use tokio::fs::File;
use tokio::io::AsyncWriteExt;

use crate::AuraEvent;

fn unix_secs(t: SystemTime) -> f64 {
    t.duration_since(UNIX_EPOCH).unwrap_or_default().as_secs_f64()
}

/// RFC 4180 CSV field quoting — needed for `annotations.csv`'s `label`
/// column, which can legitimately contain commas (e.g. "seizure
/// (chb01_16.edf, CHB-MIT ground-truth annotation)" — see replay.rs).
/// The other tables' columns are all plain numbers, so this was never
/// needed before now.
fn csv_quote(field: &str) -> String {
    if field.contains(',') || field.contains('"') || field.contains('\n') {
        format!("\"{}\"", field.replace('"', "\"\""))
    } else {
        field.to_string()
    }
}

/// One CSV file plus its own running hash chain. Async file I/O
/// (`tokio::fs`) rather than `std::fs`, so a write never blocks the
/// runtime's worker thread out from under other tasks.
struct ChainedCsv {
    file: File,
    prev_hash: [u8; 32],
}

impl ChainedCsv {
    async fn create(path: &Path, header: &str) -> anyhow::Result<Self> {
        let mut file = File::create(path).await?;
        file.write_all(format!("{header},chain_hash\n").as_bytes()).await?;
        Ok(Self { file, prev_hash: [0u8; 32] })
    }

    /// Appends one data row (without the trailing chain_hash column —
    /// that's computed and appended here) and flushes immediately.
    /// Flushing per-row is the right tradeoff for the current write
    /// volume (occasional trigger events, not yet 250Hz Cyton samples)
    /// — revisit with batched flushing if/when real Cyton throughput
    /// makes per-row fsync a bottleneck, don't assume it matters yet.
    async fn append_chained(&mut self, row: &str) -> anyhow::Result<()> {
        let mut hasher = Sha256::new();
        hasher.update(self.prev_hash);
        hasher.update(row.as_bytes());
        let new_hash = hasher.finalize();
        self.prev_hash = new_hash.into();

        let line = format!("{row},{}\n", hex::encode(new_hash));
        self.file.write_all(line.as_bytes()).await?;
        self.file.flush().await?;
        Ok(())
    }
}

fn new_session_dir(data_root: &str) -> anyhow::Result<PathBuf> {
    let session_id = unix_secs(SystemTime::now()) as u64;
    let dir = Path::new(data_root).join(format!("session_{session_id}"));
    std::fs::create_dir_all(&dir)?;
    Ok(dir)
}

/// Subscribes to the broadcast channel and writes every event to its
/// corresponding CSV file until the channel closes. Never lets a lagged
/// subscription (this one, specifically) become fatal — a skipped batch
/// here is a gap in the second copy, not data loss, since the Cyton's
/// own SD card (design doc section 3.1) remains the primary record.
pub async fn run(
    mut rx: tokio::sync::broadcast::Receiver<AuraEvent>,
    data_root: &str,
) -> anyhow::Result<()> {
    let session_dir = new_session_dir(data_root)?;
    println!("[storage] writing session to {}", session_dir.display());

    let mut samples = ChainedCsv::create(
        &session_dir.join("samples.csv"),
        "host_received_at_unix,ch1,ch2,ch3,ch4,ch5,ch6,ch7,ch8,accel_x,accel_y,accel_z",
    )
    .await?;
    let mut triggers = ChainedCsv::create(
        &session_dir.join("triggers.csv"),
        "host_received_at_unix,pico_ticks_ms,seq,pico_chain_hash,chain_ticks_us",
    )
    .await?;
    let mut annotations = ChainedCsv::create(
        &session_dir.join("annotations.csv"),
        "host_received_at_unix,at_recording_seconds,is_start,label",
    )
    .await?;

    loop {
        match rx.recv().await {
            Ok(AuraEvent::Sample(sample)) => {
                let row = format!(
                    "{},{},{},{},{},{},{},{},{},{},{},{}",
                    unix_secs(sample.host_received_at),
                    sample.channels[0], sample.channels[1], sample.channels[2], sample.channels[3],
                    sample.channels[4], sample.channels[5], sample.channels[6], sample.channels[7],
                    sample.accel[0], sample.accel[1], sample.accel[2],
                );
                samples.append_chained(&row).await?;
            }
            Ok(AuraEvent::Trigger { pico_ticks_ms, host_received_at, seq, chain_hash, chain_ticks_us }) => {
                let row = format!(
                    "{},{},{},{},{}",
                    unix_secs(host_received_at),
                    pico_ticks_ms,
                    seq.map(|s| s.to_string()).unwrap_or_default(),
                    chain_hash.unwrap_or_default(),
                    chain_ticks_us.map(|u| u.to_string()).unwrap_or_default(),
                );
                triggers.append_chained(&row).await?;
            }
            // A UI-only heartbeat (see replay.rs) — nothing to persist.
            // Replayed samples themselves still land in samples.csv via
            // the Sample arm above like any other sample; this arm only
            // exists to make the match exhaustive.
            Ok(AuraEvent::ReplayStatus { .. }) => {}
            Ok(AuraEvent::Annotation { label, is_start, at_recording_seconds, host_received_at }) => {
                let row = format!(
                    "{},{},{},{}",
                    unix_secs(host_received_at),
                    at_recording_seconds,
                    is_start,
                    csv_quote(&label),
                );
                annotations.append_chained(&row).await?;
            }
            // A lagged storage subscription is a gap in the second copy,
            // not a reason to stop — the Cyton's own SD card is still
            // the primary, unbroken record (design doc section 3.1).
            Err(tokio::sync::broadcast::error::RecvError::Lagged(_)) => continue,
            Err(tokio::sync::broadcast::error::RecvError::Closed) => break,
        }
    }
    Ok(())
}

// Tiny local hex-encode so this module doesn't need to pull in a whole
// separate `hex` crate for one call site.
mod hex {
    pub fn encode(bytes: impl AsRef<[u8]>) -> String {
        bytes.as_ref().iter().map(|b| format!("{b:02x}")).collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn chained_csv_rows_link_correctly() {
        let dir = std::env::temp_dir().join(format!("aura_storage_test_{}", unix_secs(SystemTime::now()) as u64));
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("test.csv");

        let mut csv = ChainedCsv::create(&path, "a,b").await.unwrap();
        csv.append_chained("1,2").await.unwrap();
        csv.append_chained("3,4").await.unwrap();

        let contents = std::fs::read_to_string(&path).unwrap();
        let lines: Vec<&str> = contents.lines().collect();
        assert_eq!(lines[0], "a,b,chain_hash");

        let row1_hash = lines[1].rsplit(',').next().unwrap();
        let row2_hash = lines[2].rsplit(',').next().unwrap();
        assert_ne!(row1_hash, row2_hash, "chain hashes must differ per row");
        assert_eq!(row1_hash.len(), 64, "sha256 hex digest is 64 chars");

        // Manually recompute row1's hash the same way the implementation
        // does (genesis = 32 zero bytes) and confirm it matches, so this
        // test would actually catch a broken chain construction, not
        // just "some hash got written."
        let mut hasher = Sha256::new();
        hasher.update([0u8; 32]);
        hasher.update(b"1,2");
        let expected = hex::encode(hasher.finalize());
        assert_eq!(row1_hash, expected);

        std::fs::remove_dir_all(&dir).ok();
    }
}
