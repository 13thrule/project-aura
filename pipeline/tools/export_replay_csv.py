"""Exports a real CHB-MIT recording to the flat CSV format
`broker/src/replay.rs` streams through the normal AuraEvent::Sample path —
this is the concrete answer to "is there any way to exercise the
broker/storage/dashboard pipeline with real human EEG before Cyton
hardware exists" (design doc section 9). It is real recorded data run
through the same filtering (`aura_pipeline.filters.preprocess`) and the
same 8-channel montage subset (`validate_chbmit_multifeature.CHANNELS`)
the validation scripts already use and have verified — reusing that
constant, not redefining it, so this can't silently drift from what's
actually been checked against real files.

CHB-MIT has no accelerometer channels, so replay.rs always sends
accel=[0,0,0] for these samples — that's a real gap being surfaced
honestly (see replay.rs's module doc), not something this script tries to
paper over with fabricated motion data.

Output: data/derivatives/replay/<subject>_<file>.csv (gitignored, per
data/README.md — a derivative, not raw data). Columns: t_seconds then
one column per channel in CHANNELS order, values in filtered microvolts.

Optional --start/--end (seconds) crop the recording to a time window
after filtering (filtering first, then cropping, so the bandpass filter
doesn't get a cold-start transient right at the window's start — that
would distort exactly the samples a short demo clip most wants to show
cleanly). Useful for e.g. a short demo clip centered on a real seizure's
documented onset/offset (see validation/README.md's seizure timing
tables) instead of replaying an entire hour.

Also writes a second sidecar file, `<...>_annotations.csv`
(start_seconds,end_seconds,label), whenever the source file has known
seizures per `aura_pipeline.datasets.parse_chbmit_summary` — the SAME
already-tested parser `validate_chbmit_multifeature.py` uses, not a
hand-typed or re-derived seizure time. `broker/src/replay.rs` reads this
file (via AURA_REPLAY_ANNOTATIONS_CSV) to broadcast real
AuraEvent::Annotation events when playback crosses into/out of a
seizure interval — real dataset ground truth, never a live detection.
Times are clipped to the --start/--end crop window; if the crop excludes
every seizure, the sidecar is still written with just a header (no rows).

Usage:
    pipeline\\.venv\\Scripts\\python.exe tools\\export_replay_csv.py chb01 chb01_16.edf
    pipeline\\.venv\\Scripts\\python.exe tools\\export_replay_csv.py chb01 chb01_16.edf --start 960 --end 1120
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent / "validation"))

from aura_pipeline.datasets import load_edf_recording, parse_chbmit_summary
from aura_pipeline.filters import preprocess
from validate_chbmit_multifeature import CHANNELS, CHB_ROOT, MAINS_HZ  # noqa: E402

OUT_ROOT = Path(__file__).parents[2] / "data" / "derivatives" / "replay"


def export(subject: str, filename: str, start: float | None = None, end: float | None = None) -> Path:
    edf_path = CHB_ROOT / subject / filename
    if not edf_path.exists():
        raise SystemExit(f"not found: {edf_path} (download it first — see validation/README.md)")

    raw = load_edf_recording(edf_path)
    raw.pick(CHANNELS)
    sfreq = raw.info["sfreq"]
    data = raw.get_data() * 1e6  # volts -> microvolts, matching validate_chbmit_multifeature
    filtered = preprocess(data, sfreq=sfreq, mains_hz=MAINS_HZ)

    start_idx = int((start or 0) * sfreq)
    end_idx = int(end * sfreq) if end is not None else filtered.shape[1]
    if not (0 <= start_idx < end_idx <= filtered.shape[1]):
        raise SystemExit(f"invalid --start/--end for a {filtered.shape[1] / sfreq:.1f}s recording")
    filtered = filtered[:, start_idx:end_idx]
    t_offset = start_idx / sfreq
    t_end = end_idx / sfreq

    n_samples = filtered.shape[1]
    t = t_offset + np.arange(n_samples) / sfreq

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    suffix = f"_{start_idx}-{end_idx}" if (start is not None or end is not None) else ""
    stem = f"{subject}_{filename.replace('.edf', '')}{suffix}"
    out_path = OUT_ROOT / f"{stem}.csv"
    with out_path.open("w") as f:
        f.write("t_seconds," + ",".join(CHANNELS) + "\n")
        for i in range(n_samples):
            row = [f"{t[i]:.6f}"] + [f"{filtered[ch, i]:.4f}" for ch in range(len(CHANNELS))]
            f.write(",".join(row) + "\n")
    print(f"wrote {out_path} ({n_samples} samples @ {sfreq}Hz = {n_samples / sfreq:.1f}s, "
          f"offset {t_offset:.1f}s into the original recording)")

    summary_path = CHB_ROOT / subject / f"{subject}-summary.txt"
    seizures = parse_chbmit_summary(summary_path).get(filename, []) if summary_path.exists() else []
    annotations_path = OUT_ROOT / f"{stem}_annotations.csv"
    with annotations_path.open("w") as f:
        f.write("start_seconds,end_seconds,label\n")
        written = 0
        for s_start, s_end in seizures:
            clipped_start, clipped_end = max(s_start, t_offset), min(s_end, t_end)
            if clipped_start < clipped_end:
                f.write(f"{clipped_start:.3f},{clipped_end:.3f},seizure ({filename}, CHB-MIT ground-truth annotation)\n")
                written += 1
    print(f"wrote {annotations_path} ({written} seizure annotation(s) in this window, "
          f"from {summary_path.name})")

    return out_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("subject")
    parser.add_argument("filename")
    parser.add_argument("--start", type=float, default=None, help="crop start, seconds into the recording")
    parser.add_argument("--end", type=float, default=None, help="crop end, seconds into the recording")
    args = parser.parse_args()
    export(args.subject, args.filename, args.start, args.end)
