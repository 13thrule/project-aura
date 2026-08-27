"""Cross-checks validate_chbmit_multifeature.py's hand-rolled
sensitivity/false-positives-per-hour counting against
`esl-epfl/timescoring` — the actual scoring library behind SzCORE, the
benchmark standard design doc section 10 already cites (Dan et al.
2024). Same leave-one-seizure-out classifier and same operating points
already reported in validation/README.md (threshold=0.9/smoothing=2 and
threshold=0.99/smoothing=3) — this script doesn't refit anything new, it
re-scores the SAME per-window predictions two ways so any difference is
attributable to the scoring method, not the model.

Why this can legitimately disagree with the hand-rolled numbers, and
that's not a bug in either: the hand-rolled version in
validate_chbmit_multifeature.py counts "any predicted-positive window
overlapping the true seizure interval" as a detection and every
predicted-positive window outside it as a false positive, with no
timing tolerance. SzCORE's EventScoring (via timescoring) applies real
clinical tolerances instead — up to 30s early / 60s late still counts as
a correct detection (`toleranceStart`/`toleranceEnd`), nearby false
alarms within `minDurationBetweenEvents` merge into one event rather
than being counted separately, and it reports false positives as
events/24h, not windows/hour. Different, both legitimate, and the gap
between them (if any) is itself worth reporting honestly rather than
picking whichever number looks better.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from timescoring import scoring

sys.path.insert(0, str(Path(__file__).parent))
from validate_chbmit_multifeature import (  # noqa: E402
    CHB_ROOT,
    SUBJECTS,
    WINDOW_SECONDS,
    apply_consecutive_smoothing,
    compute_window_features,
)

sys.path.insert(0, str(Path(__file__).parents[1]))
from aura_pipeline.datasets import parse_chbmit_summary  # noqa: E402
from aura_pipeline.timescore import score_windows  # noqa: E402

# Same two operating points validation/README.md already highlights as
# the "consistent neighborhood" on chb01 — re-used, not re-picked, so
# this can't be accused of cherry-picking a flattering point for the
# comparison.
OPERATING_POINTS = [
    {"threshold": 0.9, "min_consecutive": 2},
    {"threshold": 0.99, "min_consecutive": 3},
]


def _seizure_label_mask(n_windows: int, seizure_intervals: list[tuple[float, float]]) -> np.ndarray:
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
    data_dir = CHB_ROOT / subject
    summary_path = data_dir / f"{subject}-summary.txt"
    baseline_files = SUBJECTS[subject]["baseline_files"]
    seizure_files = SUBJECTS[subject]["seizure_files"]

    seizures_by_file = parse_chbmit_summary(summary_path)
    all_files = baseline_files + seizure_files
    missing = [f for f in all_files if not (data_dir / f).exists()]
    if missing:
        raise SystemExit(f"Missing {len(missing)} file(s) for {subject}: {missing}")

    print(f"[{subject}] Extracting features...")
    features_by_file = {f: compute_window_features(data_dir / f) for f in all_files}
    labels_by_file = {
        f: _seizure_label_mask(len(features_by_file[f]), seizures_by_file.get(f, []))
        for f in all_files
    }
    baseline_X = np.concatenate([features_by_file[f] for f in baseline_files])
    baseline_y = np.zeros(len(baseline_X), dtype=bool)

    results = []
    for op in OPERATING_POINTS:
        threshold, min_consecutive = op["threshold"], op["min_consecutive"]

        # Hand-rolled counting (same method as validate_chbmit_multifeature.py).
        hand_detected = 0
        hand_fp_windows = 0
        hand_non_seizure_windows = 0

        # SzCORE event-level scoring, accumulated across folds by
        # concatenating each held-out file's predictions/labels into one
        # timeline per fold and summing tp/fp/refTrue across folds —
        # timescoring scores one continuous recording at a time, so each
        # held-out seizure file is its own SzCORE-scored recording.
        sz_tp = sz_fp = sz_ref_events = 0

        for held_out in seizure_files:
            train_files = [f for f in seizure_files if f != held_out]
            train_X = np.concatenate([baseline_X] + [features_by_file[f] for f in train_files])
            train_y = np.concatenate([baseline_y] + [labels_by_file[f] for f in train_files])

            clf = LogisticRegression(class_weight="balanced", max_iter=1000)
            clf.fit(train_X, train_y)

            test_X = features_by_file[held_out]
            test_y = labels_by_file[held_out]
            proba = clf.predict_proba(test_X)[:, 1]
            pred = apply_consecutive_smoothing(proba >= threshold, min_consecutive)

            hand_detected += int((pred & test_y).any())
            hand_fp_windows += int((pred & ~test_y).sum())
            hand_non_seizure_windows += int((~test_y).sum())

            sz = score_windows(pred, test_y, WINDOW_SECONDS)
            sz_tp += sz.tp
            sz_fp += sz.fp
            sz_ref_events += len(sz.ref.events)

        hand_hours = (hand_non_seizure_windows * WINDOW_SECONDS) / 3600
        results.append({
            "threshold": threshold,
            "min_consecutive_windows": min_consecutive,
            "hand_rolled": {
                "sensitivity": hand_detected / len(seizure_files),
                "seizures_detected": hand_detected,
                "false_positives_per_hour": hand_fp_windows / hand_hours if hand_hours else None,
            },
            "szcore_timescoring": {
                "sensitivity": sz_tp / sz_ref_events if sz_ref_events else None,
                "seizures_detected": sz_tp,
                "seizures_total": sz_ref_events,
                "false_positives_per_24h": sz_fp,  # summed count across folds' whole-file durations, not a rate here — see note below
            },
        })

    result = {
        "subject": subject,
        "method": (
            "Same LogisticRegression + leave-one-seizure-out CV as validate_chbmit_multifeature.py, "
            "re-scored two ways: hand-rolled window-overlap counting (no timing tolerance) vs "
            "esl-epfl/timescoring's EventScoring (SzCORE default tolerances: toleranceStart=30s, "
            "toleranceEnd=60s, minDurationBetweenEvents=90s)."
        ),
        "note": (
            "szcore false_positives_per_24h here is a summed event count across all held-out "
            "seizure-file folds, not a normalized rate — each fold is a different-length recording. "
            "Treat it as 'total false alarms SzCORE would count across all 7 folds' for comparison "
            "against hand_rolled's per-hour rate, not as a directly comparable per-24h figure."
        ),
        "operating_points": results,
    }
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    subject_arg = sys.argv[1] if len(sys.argv) > 1 else "chb01"
    main(subject_arg)
