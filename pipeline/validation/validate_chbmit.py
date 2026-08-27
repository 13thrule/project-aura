"""Validates Aura's Phase 2 baseline detector (design doc section 4)
against real CHB-MIT recordings — the hard gate in section 4.1: no
detector touches patient data until it's proven here first, on public
data, with real clinician-annotated ground truth.

Run: from pipeline/, with the venv active:
    python validation/validate_chbmit.py

Requires data/raw/chbmit/chb01/ populated first — see
validation/README.md for exactly which files and why.

## Methodology, and why it's shaped this way

- CHB-MIT's 23-channel bipolar montage includes an 8-channel subset
  (FP1-F7, F7-T7, T7-P7, P7-O1, FP2-F8, F8-T8, T8-P8, P8-O2) that maps
  closely to Aura's actual planned 8-channel coverage (design doc section
  2.1: Fp1/F7/T3/O1, Fp2/F8/T4/O2 — T7/T8 are the modern names for
  T3/T4). Using only this subset, not all 23 channels, matters: a
  23-channel detector would trivially outperform what Aura's real
  8-channel hardware can ever see, and reporting that number as "Aura's
  expected performance" would be a real overclaim (design doc risk #4).
- The detection statistic is line length (Esteller et al. 2001, design
  doc section 10) averaged across the 8 channels per 2-second window —
  the simplest baseline from design doc section 4.3, deliberately not
  the KAN prototype (section 4.4), since the baseline is what this gate
  exists to validate first.
- The threshold is calibrated ONLY on seizure-free files (chb01_01, 02,
  05, 06) — never on the seizure files' own interictal segments — so the
  reported sensitivity isn't inflated by tuning on the same recordings
  it's tested against. This is a real methodological choice, not a
  formality: calibrating on the test data would make the number
  meaningless.
- Reported as event-level sensitivity (did we flag at least one window
  inside each known seizure) plus false positives per hour — NOT naive
  window-level accuracy. With seizures occupying well under 1% of total
  recording time, "99% accuracy" would be a trivially-achieved, mostly
  meaningless number here (a detector that never fires gets >99%
  accuracy and 0% sensitivity). Sensitivity + FP/hour is what the actual
  seizure-detection literature reports.
- This is n=1 subject (chb01, 7 seizures) — not the full 23-subject
  CHB-MIT dataset. Report results as exactly that, not as "CHB-MIT
  validation" full stop — see design doc risk #4 on overclaiming from
  thin data.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from aura_pipeline.datasets import load_edf_recording, parse_chbmit_summary
from aura_pipeline.features import line_length
from aura_pipeline.filters import preprocess

DATA_DIR = Path(__file__).parents[2] / "data" / "raw" / "chbmit" / "chb01"
SUMMARY_PATH = DATA_DIR / "chb01-summary.txt"

# chb01's raw montage lists "T8-P8" TWICE (channel 15 and channel 23 —
# see chb01-summary.txt), and MNE auto-renames duplicates with a running
# suffix on load ("T8-P8" -> "T8-P8-0"/"T8-P8-1"), logging a
# RuntimeWarning when it does. Confirmed which is which by loading a real
# file and inspecting raw.ch_names directly rather than assuming: index
# 14 (the one in this bipolar chain, right after F8-T8) becomes
# "T8-P8-0"; the unrelated duplicate at the end of the montage becomes
# "T8-P8-1". Verified consistent across chb01_01/03/26.
CHANNELS = ["FP1-F7", "F7-T7", "T7-P7", "P7-O1", "FP2-F8", "F8-T8", "T8-P8-0", "P8-O2"]
WINDOW_SECONDS = 2.0
MAINS_HZ = 60.0  # CHB-MIT was recorded at Boston Children's Hospital (US)

BASELINE_FILES = ["chb01_01.edf", "chb01_02.edf", "chb01_05.edf", "chb01_06.edf"]
SEIZURE_FILES = [
    "chb01_03.edf", "chb01_04.edf", "chb01_15.edf", "chb01_16.edf",
    "chb01_18.edf", "chb01_21.edf", "chb01_26.edf",
]


def compute_window_scores(edf_path: Path) -> np.ndarray:
    """Per-window aggregate line-length score (mean across the 8-channel
    subset), for non-overlapping WINDOW_SECONDS windows across the whole
    recording."""
    raw = load_edf_recording(edf_path)
    raw.pick(CHANNELS)
    sfreq = raw.info["sfreq"]
    data = raw.get_data() * 1e6  # volts -> microvolts, keeps magnitudes legible
    filtered = preprocess(data, sfreq=sfreq, mains_hz=MAINS_HZ)

    window_len = int(WINDOW_SECONDS * sfreq)
    n_windows = filtered.shape[1] // window_len
    scores = np.zeros(n_windows)
    for w in range(n_windows):
        seg = filtered[:, w * window_len: (w + 1) * window_len]
        scores[w] = np.mean([line_length(seg[ch]) for ch in range(seg.shape[0])])
    return scores


def _non_seizure_windows(scores: np.ndarray, seizure_intervals: list[tuple[float, float]]) -> np.ndarray:
    """Boolean mask over `scores`' windows: True where the window does
    NOT overlap any known seizure interval."""
    mask = np.ones(len(scores), dtype=bool)
    for w in range(len(scores)):
        w_start = w * WINDOW_SECONDS
        w_end = w_start + WINDOW_SECONDS
        for s_start, s_end in seizure_intervals:
            if s_start <= w_end and w_start <= s_end:
                mask[w] = False
                break
    return mask


def main() -> dict:
    seizures_by_file = parse_chbmit_summary(SUMMARY_PATH)

    missing = [f for f in BASELINE_FILES + SEIZURE_FILES if not (DATA_DIR / f).exists()]
    if missing:
        raise SystemExit(
            f"Missing {len(missing)} file(s): {missing}\n"
            f"See validation/README.md to download them into {DATA_DIR}"
        )

    # --- Calibrate threshold on baseline-only files (never on test data) ---
    baseline_scores = np.concatenate([compute_window_scores(DATA_DIR / f) for f in BASELINE_FILES])
    threshold = baseline_scores.mean() + 5 * baseline_scores.std()

    # --- Evaluate: event-level sensitivity + false positives/hour ---
    detected = 0
    total_seizures = 0
    total_fp_windows = 0
    total_non_seizure_windows = 0

    for fname in SEIZURE_FILES:
        scores = compute_window_scores(DATA_DIR / fname)
        seizure_intervals = seizures_by_file.get(fname, [])
        total_seizures += len(seizure_intervals)
        predicted = scores > threshold

        for s_start, s_end in seizure_intervals:
            w_start = int(s_start // WINDOW_SECONDS)
            w_end = int(s_end // WINDOW_SECONDS) + 1
            if predicted[w_start:w_end].any():
                detected += 1

        non_seizure_mask = _non_seizure_windows(scores, seizure_intervals)
        total_non_seizure_windows += int(non_seizure_mask.sum())
        total_fp_windows += int((predicted & non_seizure_mask).sum())

    for fname in BASELINE_FILES:
        scores = compute_window_scores(DATA_DIR / fname)
        predicted = scores > threshold
        total_non_seizure_windows += len(scores)
        total_fp_windows += int(predicted.sum())

    hours = (total_non_seizure_windows * WINDOW_SECONDS) / 3600
    result = {
        "subject": "chb01",
        "n_subjects": 1,
        "channels_used": CHANNELS,
        "window_seconds": WINDOW_SECONDS,
        "mains_hz": MAINS_HZ,
        "threshold_line_length": float(threshold),
        "seizures_total": total_seizures,
        "seizures_detected_event_level": detected,
        "sensitivity": detected / total_seizures if total_seizures else None,
        "false_positives_per_hour": total_fp_windows / hours if hours else None,
        "total_non_seizure_hours_evaluated": hours,
    }
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    main()
