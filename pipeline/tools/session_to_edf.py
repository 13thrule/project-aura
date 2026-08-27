"""Converts one broker/src/storage.rs session (samples.csv) into a
standard EDF file, loadable by MNE (or any other EEG tool) like any other
recording — closing the loop the replay path opened: real/replayed EEG
now flows broker -> storage.rs's chained CSV, but until this script
existed there was no way to get it back into an analysis-ready format.
Explicitly NOT the BIDS/anonymization export design doc section 5 calls
for (that's flagged there as "its own deliverable with its own
validation pass," not a quick script) — this is the smaller, honest
first step: a correct, round-trip-tested CSV -> EDF converter, nothing
more.

Verifies the session's hash chain (aura_pipeline.chain_verify) before
exporting by default and refuses to export a broken chain — silently
exporting tampered/corrupted data as if it were trustworthy would defeat
the entire point of storage.rs's chain (design doc section 2.5).

## Channel mapping — a real, stated assumption, not a fact

`ch1..ch8` in samples.csv are mapped positionally to the design doc
section 2.1 montage (Fp1, Fp2, F7, F8, T3, T4, O1, O2). No Cyton hardware
exists yet to confirm the physical channel1->Fp1 wiring will actually
match this order — re-verify against the real acquisition setup once
hardware exists, the same way T8-P8-0 vs -1 had to be verified against
real CHB-MIT files rather than assumed (see validation/README.md).
`accel_x/y/z` are exported as `misc` channels with no unit conversion —
the Cyton's real accelerometer units aren't defined anywhere in this
repo yet (no hardware to define them against), so this deliberately does
NOT guess a unit like "g" and silently mislabel the data.

## Sample-rate handling

samples.csv doesn't store a nominal sample rate — only per-row wall-clock
timestamps (`host_received_at_unix`). EDF requires one fixed rate, so
this computes an effective rate from total duration / sample count and
WARNS (loudly, does not silently proceed) if inter-sample timing jitter
is high enough that a fixed rate is a poor description of the data —
relevant today because replay.rs's pacing runs on `tokio::time::interval`
over a non-realtime OS scheduler, not a hardware clock.
"""

from __future__ import annotations

import sys
from pathlib import Path

import mne
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))
from aura_pipeline.chain_verify import verify_chained_csv  # noqa: E402

EEG_CHANNEL_NAMES = ["Fp1", "Fp2", "F7", "F8", "T3", "T4", "O1", "O2"]
ACCEL_CHANNEL_NAMES = ["accel_x", "accel_y", "accel_z"]

# Jitter here means "how much does the actual per-sample interval vary
# around the mean," as a fraction of the mean interval. 10% is a
# deliberately loose bar — real wall-clock delivery always has some
# scheduling noise — meant to catch a genuinely irregular stream (e.g. a
# stalled/resumed broker), not to complain about normal jitter.
JITTER_WARN_FRACTION = 0.10


def _load_samples_csv(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Returns (timestamps, eeg_uv[8, n], accel[3, n]). Parses the row
    text directly rather than via a generic CSV/pandas reader — the file
    has a known fixed 12-column shape (see storage.rs) plus a trailing
    chain_hash column this function ignores."""
    timestamps, eeg, accel = [], [], []
    with path.open("r", newline="") as f:
        header = f.readline().rstrip("\n").split(",")
        expected = ["host_received_at_unix"] + [f"ch{i}" for i in range(1, 9)] + \
            ["accel_x", "accel_y", "accel_z", "chain_hash"]
        if header != expected:
            raise ValueError(f"unexpected samples.csv header: {header}")

        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            parts = line.split(",")
            values = [float(v) for v in parts[:-1]]  # drop the trailing hex chain_hash
            timestamps.append(values[0])
            eeg.append(values[1:9])
            accel.append(values[9:12])

    return (
        np.array(timestamps, dtype=np.float64),
        np.array(eeg, dtype=np.float64).T,   # (8, n)
        np.array(accel, dtype=np.float64).T,  # (3, n)
    )


def _effective_sample_rate(timestamps: np.ndarray) -> int:
    """Returns a whole-number Hz. EDF stores data in fixed-duration
    records each holding an integer number of samples — feeding it a
    noisy inferred float rate (e.g. 1280.0807939...Hz, what
    `1/mean(diff(timestamps))` actually produces from real wall-clock
    timestamps) makes total-duration-vs-record-duration divisibility
    fail in ways that depend on floating-point noise, not anything
    meaningful about the recording. Rounding to the nearest integer Hz
    is the honest fix: real acquisition hardware (including the Cyton
    this format targets) reports a nominal integer rate, and wall-clock
    timestamp noise around that nominal rate isn't signal worth
    preserving in the sample-rate field — it's scheduling jitter,
    reported separately below instead.
    """
    if len(timestamps) < 2:
        raise ValueError("need at least 2 samples to infer a sample rate")

    intervals = np.diff(timestamps)
    mean_interval = float(np.mean(intervals))
    if mean_interval <= 0:
        raise ValueError("non-increasing timestamps in samples.csv — cannot infer a sample rate")

    jitter = float(np.std(intervals)) / mean_interval
    raw_sfreq = 1.0 / mean_interval
    sfreq = round(raw_sfreq)
    if jitter > JITTER_WARN_FRACTION:
        print(
            f"WARNING: inter-sample timing jitter is {jitter:.1%} of the mean interval "
            f"(rounded to {sfreq}Hz from a raw estimate of {raw_sfreq:.1f}Hz — a fixed rate "
            "is a poor fit here, likely broadcast-channel backpressure or scheduling delay, "
            "not real acquisition jitter) — treat the exported EDF's timing as approximate.",
            file=sys.stderr,
        )
    return sfreq


def convert(session_dir: Path, out_path: Path, verify_chain: bool = True) -> Path:
    samples_path = session_dir / "samples.csv"
    if not samples_path.exists():
        raise SystemExit(f"not found: {samples_path}")

    if verify_chain:
        ok, msg = verify_chained_csv(samples_path)
        if not ok:
            raise SystemExit(
                f"refusing to export — chain verification failed for {samples_path}: {msg}"
            )
        print(f"chain verification: {msg}")

    timestamps, eeg_uv, accel = _load_samples_csv(samples_path)
    if eeg_uv.shape[1] == 0:
        raise SystemExit(f"{samples_path} has no data rows — nothing to export")

    sfreq = _effective_sample_rate(timestamps)

    # EDF records hold an integer number of samples over a whole number
    # of seconds; trim any trailing partial second so total duration
    # divides evenly, rather than letting the export call fail on it.
    n_full = (eeg_uv.shape[1] // sfreq) * sfreq
    if n_full < eeg_uv.shape[1]:
        print(f"trimming {eeg_uv.shape[1] - n_full} trailing sample(s) so duration divides "
              f"evenly into whole seconds at {sfreq}Hz")
    eeg_uv = eeg_uv[:, :n_full]
    accel = accel[:, :n_full]
    if n_full == 0:
        raise SystemExit(f"{samples_path} has fewer than {sfreq} samples — nothing to export")

    ch_names = EEG_CHANNEL_NAMES + ACCEL_CHANNEL_NAMES
    ch_types = ["eeg"] * 8 + ["misc"] * 3
    info = mne.create_info(ch_names, sfreq=sfreq, ch_types=ch_types)

    data = np.vstack([eeg_uv * 1e-6, accel])  # MNE's internal EEG unit is volts
    raw = mne.io.RawArray(data, info, verbose=False)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    raw.export(str(out_path), fmt="edf", overwrite=True, verbose=False)
    print(f"wrote {out_path} ({eeg_uv.shape[1]} samples @ {sfreq:.2f}Hz = "
          f"{eeg_uv.shape[1] / sfreq:.1f}s, 8 EEG + 3 accel channels)")
    return out_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(
            "usage: session_to_edf.py <path/to/session_dir> [out.edf] [--skip-verify]"
        )
    session_dir = Path(sys.argv[1])
    positional = [a for a in sys.argv[2:] if not a.startswith("--")]
    out_path = Path(positional[0]) if positional else session_dir / "samples.edf"
    verify = "--skip-verify" not in sys.argv[2:]
    convert(session_dir, out_path, verify_chain=verify)
