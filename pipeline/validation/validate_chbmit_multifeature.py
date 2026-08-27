"""Multi-feature Phase 2 detector, evaluated honestly, against real
CHB-MIT data — the natural next step flagged in `validate_chbmit.py`
(line-length alone, 28.6% sensitivity / 4.5 FP/hr) and in
`pipeline/README.md`.

## Why this file exists instead of just editing the threshold

The single most tempting-and-wrong thing to do after seeing a weak first
result is to keep nudging the threshold on the same 7 seizures until it
"catches all of them." That number would be meaningless: at the limit, a
detector that fires on every window "detects" 7/7 trivially, at the cost
of a false-positive rate that makes it useless. Sensitivity only means
something paired with a false-positive rate, and only if the detector
was evaluated on data it never got to see the answer key for.

This file does the legitimate version of "make it better":

1. Combines the features design doc section 4.3 actually specifies —
   line length, Hjorth mobility/complexity, and FFT band power — into
   one feature vector per window, instead of line length alone. All four
   are already implemented and tested in `aura_pipeline/features.py`;
   this just uses more of what's already there.
2. Fits a real `sklearn` classifier (`LogisticRegression`, per
   CLAUDE.md's "use scikit-learn for threshold classifiers"), not a
   hand-picked threshold.
3. Evaluates with **leave-one-seizure-out cross-validation**: for each of
   chb01's 7 seizures, the classifier is trained on the OTHER 6 + all 4
   baseline files, then tested on the held-out seizure it never saw
   during training. This is the standard technique for getting an honest
   generalization estimate out of a small positive-example count — it
   uses all 7 seizures for evaluation without ever scoring a fold against
   data that fold's model was fit on.

Whatever sensitivity/FP-rate comes out of this is reported as-is — this
file does not exist to hit a target number, including 7/7. Read the
printed result the same way `validate_chbmit.py`'s result should be
read: honestly, as a real data point with room to improve, not a
number to defend.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression

from aura_pipeline.datasets import load_edf_recording, parse_chbmit_summary
from aura_pipeline.features import band_power, hjorth_complexity, hjorth_mobility, line_length
from aura_pipeline.filters import SAMPLE_RATE_HZ, preprocess

CHB_ROOT = Path(__file__).parents[2] / "data" / "raw" / "chbmit"

# See validate_chbmit.py for the montage-subset and T8-P8-0 rationale —
# identical here, deliberately kept in sync. NOTE: "T8-P8-0" is verified
# correct via real file inspection (raw.ch_names), not assumed, for
# chb01, chb02, and chb03 — still confirm on any NEW subject's real data
# before trusting it blindly, since MNE's duplicate-renaming order could
# plausibly differ if a future subject's montage list differs even
# slightly. (chb04/chb05 not yet checked as of this comment — verify
# before running the multi-feature/calibrated scripts against them.)
CHANNELS = ["FP1-F7", "F7-T7", "T7-P7", "P7-O1", "FP2-F8", "F8-T8", "T8-P8-0", "P8-O2"]
WINDOW_SECONDS = 2.0
MAINS_HZ = 60.0

FEATURE_NAMES = ["line_length", "hjorth_mobility", "hjorth_complexity",
                  "delta", "theta", "alpha", "beta", "gamma"]

# Per-subject file lists. Add a subject here once its files are
# downloaded (see validation/README.md) — everything else in this file
# is subject-agnostic.
SUBJECTS = {
    "chb01": {
        "baseline_files": ["chb01_01.edf", "chb01_02.edf", "chb01_05.edf", "chb01_06.edf"],
        "seizure_files": [
            "chb01_03.edf", "chb01_04.edf", "chb01_15.edf", "chb01_16.edf",
            "chb01_18.edf", "chb01_21.edf", "chb01_26.edf",
        ],
    },
    "chb02": {
        "baseline_files": ["chb02_01.edf", "chb02_02.edf", "chb02_03.edf", "chb02_04.edf"],
        "seizure_files": ["chb02_16.edf", "chb02_16+.edf", "chb02_19.edf"],
    },
    "chb03": {
        "baseline_files": ["chb03_05.edf", "chb03_06.edf", "chb03_07.edf", "chb03_08.edf"],
        "seizure_files": [
            "chb03_01.edf", "chb03_02.edf", "chb03_03.edf", "chb03_04.edf",
            "chb03_34.edf", "chb03_35.edf", "chb03_36.edf",
        ],
    },
    "chb04": {
        "baseline_files": ["chb04_01.edf", "chb04_02.edf", "chb04_03.edf", "chb04_04.edf"],
        "seizure_files": ["chb04_05.edf", "chb04_08.edf", "chb04_28.edf"],
    },
    "chb05": {
        "baseline_files": ["chb05_01.edf", "chb05_02.edf", "chb05_03.edf", "chb05_04.edf"],
        "seizure_files": [
            "chb05_06.edf", "chb05_13.edf", "chb05_16.edf", "chb05_17.edf", "chb05_22.edf",
        ],
    },
}


def compute_window_features(edf_path: Path) -> np.ndarray:
    """Per-window 8-dim feature vector (mean across the 8-channel
    subset), for non-overlapping WINDOW_SECONDS windows across the whole
    recording. Shape: (n_windows, 8)."""
    raw = load_edf_recording(edf_path)
    raw.pick(CHANNELS)
    sfreq = raw.info["sfreq"]
    data = raw.get_data() * 1e6  # volts -> microvolts
    filtered = preprocess(data, sfreq=sfreq, mains_hz=MAINS_HZ)

    window_len = int(WINDOW_SECONDS * sfreq)
    n_windows = filtered.shape[1] // window_len
    features = np.zeros((n_windows, len(FEATURE_NAMES)))

    for w in range(n_windows):
        seg = filtered[:, w * window_len: (w + 1) * window_len]
        n_ch = seg.shape[0]
        ll = np.mean([line_length(seg[ch]) for ch in range(n_ch)])
        mob = np.mean([hjorth_mobility(seg[ch]) for ch in range(n_ch)])
        cplx = np.mean([hjorth_complexity(seg[ch]) for ch in range(n_ch)])
        bands = [band_power(seg[ch], sfreq) for ch in range(n_ch)]
        band_means = {
            b: np.mean([bands[ch][b] for ch in range(n_ch)])
            for b in ("delta", "theta", "alpha", "beta", "gamma")
        }
        features[w] = [ll, mob, cplx, band_means["delta"], band_means["theta"],
                        band_means["alpha"], band_means["beta"], band_means["gamma"]]
    return features


def apply_consecutive_smoothing(pred: np.ndarray, min_consecutive: int) -> np.ndarray:
    """Only count a window as a firing alarm once `min_consecutive`
    consecutive windows have all been predicted positive — a real
    seizure spans many windows (chb01's shortest is 40s = 20 windows at
    2s each), so requiring 2-3 in a row should filter isolated
    false-positive blips without costing real detections. `min_consecutive=1`
    is the raw, unsmoothed prediction (no-op)."""
    if min_consecutive <= 1:
        return pred.copy()
    smoothed = np.zeros_like(pred)
    streak = 0
    for i in range(len(pred)):
        streak = streak + 1 if pred[i] else 0
        smoothed[i] = streak >= min_consecutive
    return smoothed


def _seizure_label_mask(n_windows: int, seizure_intervals: list[tuple[float, float]]) -> np.ndarray:
    """Boolean mask over windows: True where the window overlaps a known
    seizure interval."""
    labels = np.zeros(n_windows, dtype=bool)
    for w in range(n_windows):
        w_start = w * WINDOW_SECONDS
        w_end = w_start + WINDOW_SECONDS
        for s_start, s_end in seizure_intervals:
            if s_start <= w_end and w_start <= s_end:
                labels[w] = True
                break
    return labels


def main(subject: str = "chb01") -> dict:
    if subject not in SUBJECTS:
        raise SystemExit(f"Unknown subject {subject!r} — add it to SUBJECTS first. Known: {list(SUBJECTS)}")

    data_dir = CHB_ROOT / subject
    summary_path = data_dir / f"{subject}-summary.txt"
    baseline_files = SUBJECTS[subject]["baseline_files"]
    seizure_files = SUBJECTS[subject]["seizure_files"]

    seizures_by_file = parse_chbmit_summary(summary_path)
    all_files = baseline_files + seizure_files
    missing = [f for f in all_files if not (data_dir / f).exists()]
    if missing:
        raise SystemExit(f"Missing {len(missing)} file(s) for {subject}: {missing}")

    print(f"[{subject}] Extracting features for all files (line length, Hjorth, band power per window)...")
    features_by_file: dict[str, np.ndarray] = {f: compute_window_features(data_dir / f) for f in all_files}
    labels_by_file: dict[str, np.ndarray] = {
        f: _seizure_label_mask(len(features_by_file[f]), seizures_by_file.get(f, []))
        for f in all_files
    }

    baseline_X = np.concatenate([features_by_file[f] for f in baseline_files])
    baseline_y = np.zeros(len(baseline_X), dtype=bool)

    # Sweep decision thresholds AND consecutive-window smoothing rather
    # than reporting one cherry-picked operating point — sensitivity
    # alone (or FP/hour alone) is easy to make look good by ignoring the
    # other. Report the real tradeoff across both knobs.
    THRESHOLDS = [0.5, 0.9, 0.99, 0.999]
    SMOOTHING_LEVELS = [1, 2, 3]  # 1 = raw, no smoothing
    configs = [(t, m) for t in THRESHOLDS for m in SMOOTHING_LEVELS]

    detected = {c: 0 for c in configs}
    total_fp_windows = {c: 0 for c in configs}
    total_test_non_seizure_windows = 0
    per_fold_results = []

    for held_out in seizure_files:
        train_files = [f for f in seizure_files if f != held_out]
        train_X = np.concatenate([baseline_X] + [features_by_file[f] for f in train_files])
        train_y = np.concatenate([baseline_y] + [labels_by_file[f] for f in train_files])

        clf = LogisticRegression(class_weight="balanced", max_iter=1000)
        clf.fit(train_X, train_y)

        test_X = features_by_file[held_out]
        test_y = labels_by_file[held_out]
        proba = clf.predict_proba(test_X)[:, 1]

        fold_non_seizure = int((~test_y).sum())
        total_test_non_seizure_windows += fold_non_seizure

        fold_summary = {"held_out_file": held_out}
        for t in THRESHOLDS:
            raw_pred = proba >= t
            for m in SMOOTHING_LEVELS:
                pred = apply_consecutive_smoothing(raw_pred, m)
                fold_detected = bool((pred & test_y).any())
                fold_fp = int((pred & ~test_y).sum())
                detected[(t, m)] += int(fold_detected)
                total_fp_windows[(t, m)] += fold_fp
                fold_summary[f"detected_t{t}_smooth{m}"] = fold_detected
                fold_summary[f"fp_windows_t{t}_smooth{m}"] = fold_fp
        per_fold_results.append(fold_summary)

    hours = (total_test_non_seizure_windows * WINDOW_SECONDS) / 3600
    operating_points = [
        {
            "probability_threshold": t,
            "min_consecutive_windows": m,
            "sensitivity": detected[(t, m)] / len(seizure_files),
            "seizures_detected": detected[(t, m)],
            "false_positives_per_hour": total_fp_windows[(t, m)] / hours if hours else None,
        }
        for (t, m) in configs
    ]

    result = {
        "subject": subject,
        "n_subjects": 1,
        "method": "LogisticRegression, 8 features (line_length, hjorth mobility/complexity, 5 band powers), leave-one-seizure-out CV",
        "channels_used": CHANNELS,
        "window_seconds": WINDOW_SECONDS,
        "seizures_total": len(seizure_files),
        "test_non_seizure_hours_evaluated": hours,
        "operating_points": operating_points,
        "per_fold": per_fold_results,
    }
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    subject_arg = sys.argv[1] if len(sys.argv) > 1 else "chb01"
    main(subject_arg)
