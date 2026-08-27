//! Replays a real, previously-recorded EEG file through the broker's
//! normal `AuraEvent::Sample` stream, so `storage.rs` and
//! `dashboard.rs` can be exercised against real human EEG before Cyton
//! hardware exists (design doc section 9) — the concrete answer to "is
//! there any way to make progress without the hardware." This is real
//! recorded data (CHB-MIT, exported by
//! `pipeline/tools/export_replay_csv.py` using the same filtering and
//! channel montage `pipeline/validation` already validated), not
//! synthetic/simulated data.
//!
//! It is emphatically NOT live, and a dashboard tab must never be able
//! to mistake it for a real-time patient stream — a mixup like that in
//! a real seizure-detection tool would be a genuine safety problem, not
//! just a labeling nitpick. `AuraEvent::ReplayStatus` is broadcast once
//! at the start of a replay and then again every
//! `REPLAY_STATUS_INTERVAL` samples for as long as replay runs, so any
//! dashboard connection — including one that opens mid-replay and would
//! otherwise miss a one-time startup message — sees a persistent
//! "not live" banner within a couple of seconds (see dashboard/index.html).
//!
//! CHB-MIT has no accelerometer channels. Samples here always carry
//! `accel: [0.0, 0.0, 0.0]` — a real, honestly-surfaced gap, not
//! fabricated motion data standing in for the real thing.
//!
//! CSV format (see export_replay_csv.py): header row, then
//! `t_seconds,ch0,ch1,...,ch7` per line, already bandpass+notch filtered,
//! in microvolts. `t_seconds` is the offset into the *original* source
//! recording (matches the dataset's own annotation times directly) —
//! used below to detect annotation crossings, but pacing itself uses
//! wall-clock `sample_rate_hz`/`speed` rather than trying to resync to
//! it, since drift between the two would only matter if this were
//! claiming to be a precise real-time reproduction, which it isn't.
//!
//! ## Real ground-truth annotations, not a live detector
//!
//! If `AURA_REPLAY_ANNOTATIONS_CSV` names a sidecar file (written by
//! `export_replay_csv.py` from the dataset's own clinician-verified
//! seizure times via `aura_pipeline.datasets.parse_chbmit_summary` — the
//! same parser `pipeline/validation` already trusts, not hand-typed
//! here), this broadcasts a real `AuraEvent::Annotation` the moment
//! playback's `t_seconds` crosses into or out of each interval. This is
//! dataset ground truth being replayed alongside the signal that
//! produced it — it must never be presented as something the system
//! detected. `is_start`/`is_start:false` distinguish entering vs leaving
//! an interval so the dashboard can render "seizure start" / "seizure
//! end" distinctly rather than one ambiguous event.

use std::path::Path;
use std::time::{Duration, SystemTime};

use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::sync::broadcast;

use crate::{cyton::Sample, AuraEvent};

const REPLAY_STATUS_INTERVAL: usize = 500; // resend the "not live" banner roughly every couple seconds

fn parse_replay_row(line: &str) -> anyhow::Result<(f64, [f32; 8])> {
    let mut parts = line.split(',');
    let t_raw = parts.next().ok_or_else(|| anyhow::anyhow!("empty replay row"))?;
    let t_seconds: f64 = t_raw
        .trim()
        .parse()
        .map_err(|e| anyhow::anyhow!("replay row's t_seconds column ({t_raw:?}) is not a float: {e}"))?;

    let mut channels = [0.0f32; 8];
    for (i, c) in channels.iter_mut().enumerate() {
        let raw = parts
            .next()
            .ok_or_else(|| anyhow::anyhow!("replay row has fewer than 8 channel columns (missing column {i})"))?;
        *c = raw
            .trim()
            .parse()
            .map_err(|e| anyhow::anyhow!("replay row column {i} ({raw:?}) is not a float: {e}"))?;
    }
    Ok((t_seconds, channels))
}

#[derive(Debug, Clone, PartialEq)]
struct AnnotationInterval {
    start: f64,
    end: f64,
    label: String,
}

/// Parses export_replay_csv.py's `*_annotations.csv` sidecar:
/// `start_seconds,end_seconds,label` — `splitn(3, ',')` because `label`
/// (e.g. "seizure (chb01_16.edf, CHB-MIT ground-truth annotation)") can
/// itself legitimately contain commas; only the first two fields are
/// fixed-format.
fn parse_annotations_csv(path: &Path) -> anyhow::Result<Vec<AnnotationInterval>> {
    let content = std::fs::read_to_string(path)?;
    let mut lines = content.lines();
    lines.next(); // header

    let mut intervals = Vec::new();
    for line in lines {
        if line.trim().is_empty() {
            continue;
        }
        let mut parts = line.splitn(3, ',');
        let start: f64 = parts
            .next()
            .ok_or_else(|| anyhow::anyhow!("annotation row missing start_seconds: {line:?}"))?
            .trim()
            .parse()?;
        let end: f64 = parts
            .next()
            .ok_or_else(|| anyhow::anyhow!("annotation row missing end_seconds: {line:?}"))?
            .trim()
            .parse()?;
        let label = parts
            .next()
            .ok_or_else(|| anyhow::anyhow!("annotation row missing label: {line:?}"))?
            .trim()
            .to_string();
        anyhow::ensure!(start < end, "annotation interval start ({start}) must be before end ({end})");
        intervals.push(AnnotationInterval { start, end, label });
    }
    Ok(intervals)
}

pub async fn run(
    csv_path: &str,
    sample_rate_hz: f64,
    speed: f64,
    label: String,
    annotations_csv_path: Option<String>,
    tx: broadcast::Sender<AuraEvent>,
) -> anyhow::Result<()> {
    let path = Path::new(csv_path);
    anyhow::ensure!(
        path.exists(),
        "replay CSV not found: {csv_path} — generate it with \
         pipeline/tools/export_replay_csv.py first"
    );
    anyhow::ensure!(sample_rate_hz > 0.0, "sample_rate_hz must be positive");
    anyhow::ensure!(speed > 0.0, "speed must be positive");

    let annotations = match &annotations_csv_path {
        Some(p) => {
            let intervals = parse_annotations_csv(Path::new(p))?;
            println!("aura-broker: loaded {} real annotation interval(s) from {p}", intervals.len());
            intervals
        }
        None => Vec::new(),
    };
    // Tracks which intervals we're currently "inside," so a crossing is
    // only announced once (on entry/exit), not on every sample while
    // inside — indices into `annotations`.
    let mut inside: Vec<bool> = vec![false; annotations.len()];

    println!(
        "aura-broker: REPLAY MODE ACTIVE — streaming real recorded EEG from {csv_path} \
         ({label}) at {speed}x real-time speed. THIS IS NOT A LIVE SIGNAL."
    );

    let file = tokio::fs::File::open(path).await?;
    let mut lines = BufReader::new(file).lines();
    lines.next_line().await?; // header row

    let period = Duration::from_secs_f64(1.0 / (sample_rate_hz * speed));
    let mut interval = tokio::time::interval(period);
    let mut n: usize = 0;

    let _ = tx.send(AuraEvent::ReplayStatus { label: label.clone() });

    while let Some(line) = lines.next_line().await? {
        interval.tick().await;
        let (t_seconds, channels) = parse_replay_row(&line)?;
        let host_received_at = SystemTime::now();
        let sample = Sample {
            host_received_at,
            channels,
            accel: [0.0, 0.0, 0.0],
        };
        // A lagging/absent subscriber is fine here for the same reason
        // it's fine in cyton.rs's (unwired) sketch — send() failing just
        // means nobody's currently subscribed, not that replay should stop.
        let _ = tx.send(AuraEvent::Sample(sample));

        for (i, ann) in annotations.iter().enumerate() {
            let now_inside = t_seconds >= ann.start && t_seconds < ann.end;
            if now_inside && !inside[i] {
                let _ = tx.send(AuraEvent::Annotation {
                    label: ann.label.clone(),
                    is_start: true,
                    at_recording_seconds: t_seconds,
                    host_received_at,
                });
            } else if !now_inside && inside[i] {
                let _ = tx.send(AuraEvent::Annotation {
                    label: ann.label.clone(),
                    is_start: false,
                    at_recording_seconds: t_seconds,
                    host_received_at,
                });
            }
            inside[i] = now_inside;
        }

        n += 1;
        if n.is_multiple_of(REPLAY_STATUS_INTERVAL) {
            let _ = tx.send(AuraEvent::ReplayStatus { label: label.clone() });
        }
    }

    println!("aura-broker: replay of {csv_path} finished ({n} samples).");
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_a_well_formed_row() {
        let row = "1.234500,1.0,-2.5,3.25,0.0,-1.0,42.0,-42.0,7.5";
        let (t, channels) = parse_replay_row(row).unwrap();
        assert!((t - 1.2345).abs() < 1e-9);
        assert_eq!(channels, [1.0, -2.5, 3.25, 0.0, -1.0, 42.0, -42.0, 7.5]);
    }

    #[test]
    fn rejects_a_short_row() {
        let row = "1.234500,1.0,-2.5";
        assert!(parse_replay_row(row).is_err());
    }

    #[test]
    fn rejects_a_non_numeric_column() {
        let row = "1.234500,1.0,-2.5,3.25,0.0,-1.0,42.0,-42.0,not_a_number";
        assert!(parse_replay_row(row).is_err());
    }

    #[test]
    fn parses_annotations_csv_with_commas_in_the_label() {
        let dir = std::env::temp_dir();
        let path = dir.join(format!("aura_test_annotations_{}.csv", std::process::id()));
        std::fs::write(
            &path,
            "start_seconds,end_seconds,label\n\
             1015.000,1066.000,seizure (chb01_16.edf, CHB-MIT ground-truth annotation)\n",
        )
        .unwrap();

        let intervals = parse_annotations_csv(&path).unwrap();
        std::fs::remove_file(&path).ok();

        assert_eq!(intervals.len(), 1);
        assert_eq!(intervals[0].start, 1015.0);
        assert_eq!(intervals[0].end, 1066.0);
        assert_eq!(intervals[0].label, "seizure (chb01_16.edf, CHB-MIT ground-truth annotation)");
    }

    #[test]
    fn rejects_an_interval_where_start_is_not_before_end() {
        let dir = std::env::temp_dir();
        let path = dir.join(format!("aura_test_bad_annotations_{}.csv", std::process::id()));
        std::fs::write(&path, "start_seconds,end_seconds,label\n100.0,50.0,bad interval\n").unwrap();

        let result = parse_annotations_csv(&path);
        std::fs::remove_file(&path).ok();
        assert!(result.is_err());
    }
}
