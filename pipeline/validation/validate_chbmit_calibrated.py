"""Tests the calibration extension (aura_pipeline.calibration) with
proper LEAVE-ONE-SUBJECT-OUT methodology — the correct test for "does
per-patient calibration help a genuinely new patient." This is a
different, stricter question than validate_chbmit_multifeature.py's
leave-one-seizure-out, which only holds out one seizure at a time while
still training on the rest of the SAME subject's data.

For each subject S:
  1. Train the shared classifier on ALL OTHER subjects' data (both their
     baseline and seizure files). S contributes NOTHING to training —
     the model has never seen this person.
  2. Calibrate S's personal decision threshold using ONLY S's baseline
     files (aura_pipeline.calibration) — no seizure labels from S touch
     calibration either, matching what a real new patient actually has
     per design doc Phase 3.
  3. Test on S's real seizure files using that personally-calibrated
     threshold.

Run: python validation/validate_chbmit_calibrated.py [target_fp_per_hour]
Needs at least 2 subjects in SUBJECTS (validate_chbmit_multifeature.py) —
currently chb01 and chb02, so this is a 2-fold check. Add more subjects
there as they're downloaded to strengthen this.
"""

from __future__ import annotations

import json
import sys

import numpy as np
from sklearn.linear_model import LogisticRegression

from aura_pipeline.calibration import calibrate_threshold_for_target_fp_rate
from aura_pipeline.datasets import parse_chbmit_summary
from validate_chbmit_multifeature import (
    CHB_ROOT,
    SUBJECTS,
    WINDOW_SECONDS,
    apply_consecutive_smoothing,
    compute_window_features,
    _seizure_label_mask,
)


def _load_subject(subject: str):
    data_dir = CHB_ROOT / subject
    summary_path = data_dir / f"{subject}-summary.txt"
    seizures_by_file = parse_chbmit_summary(summary_path)
    baseline_files = SUBJECTS[subject]["baseline_files"]
    seizure_files = SUBJECTS[subject]["seizure_files"]
    all_files = baseline_files + seizure_files
    missing = [f for f in all_files if not (data_dir / f).exists()]
    if missing:
        raise SystemExit(f"Missing {len(missing)} file(s) for {subject}: {missing}")

    features_by_file = {f: compute_window_features(data_dir / f) for f in all_files}
    labels_by_file = {
        f: _seizure_label_mask(len(features_by_file[f]), seizures_by_file.get(f, []))
        for f in all_files
    }
    return baseline_files, seizure_files, features_by_file, labels_by_file


def main(target_fp_per_hour: float = 2.0, min_consecutive: int = 2) -> dict:
    all_subjects = list(SUBJECTS.keys())
    if len(all_subjects) < 2:
        raise SystemExit(f"Need at least 2 subjects for leave-one-subject-out; have {all_subjects}")

    print(f"Loading and extracting features for subjects: {all_subjects} ...")
    loaded = {s: _load_subject(s) for s in all_subjects}

    fold_results = []
    for held_out in all_subjects:
        train_subjects = [s for s in all_subjects if s != held_out]

        train_X_parts, train_y_parts = [], []
        for s in train_subjects:
            baseline_files, seizure_files, features_by_file, labels_by_file = loaded[s]
            for f in baseline_files + seizure_files:
                train_X_parts.append(features_by_file[f])
                train_y_parts.append(labels_by_file[f])
        train_X = np.concatenate(train_X_parts)
        train_y = np.concatenate(train_y_parts)

        clf = LogisticRegression(class_weight="balanced", max_iter=1000)
        clf.fit(train_X, train_y)

        held_baseline_files, held_seizure_files, held_features, held_labels = loaded[held_out]

        # Calibrate using ONLY the held-out subject's baseline data — no
        # seizure labels from them, matching a real new patient exactly.
        baseline_proba = np.concatenate(
            [clf.predict_proba(held_features[f])[:, 1] for f in held_baseline_files]
        )
        threshold = calibrate_threshold_for_target_fp_rate(baseline_proba, WINDOW_SECONDS, target_fp_per_hour)

        detected = 0
        fp_windows = 0
        non_seizure_windows = 0
        for f in held_seizure_files:
            proba = clf.predict_proba(held_features[f])[:, 1]
            pred = apply_consecutive_smoothing(proba >= threshold, min_consecutive)
            y = held_labels[f]
            if (pred & y).any():
                detected += 1
            fp_windows += int((pred & ~y).sum())
            non_seizure_windows += int((~y).sum())
        for f in held_baseline_files:
            proba = clf.predict_proba(held_features[f])[:, 1]
            pred = apply_consecutive_smoothing(proba >= threshold, min_consecutive)
            fp_windows += int(pred.sum())
            non_seizure_windows += len(pred)

        hours = (non_seizure_windows * WINDOW_SECONDS) / 3600
        fold_results.append({
            "held_out_subject": held_out,
            "trained_on": train_subjects,
            "calibrated_threshold": threshold,
            "seizures_total": len(held_seizure_files),
            "seizures_detected": detected,
            "sensitivity": detected / len(held_seizure_files),
            "false_positives_per_hour": fp_windows / hours if hours else None,
        })

    result = {
        "method": (
            "Population LogisticRegression trained on all-but-one subject, threshold "
            "calibrated per-patient using ONLY their own baseline data (no seizure labels "
            "from them), tested on their real seizures — leave-one-subject-out."
        ),
        "target_fp_per_hour": target_fp_per_hour,
        "min_consecutive_windows": min_consecutive,
        "folds": fold_results,
    }
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    target = float(sys.argv[1]) if len(sys.argv) > 1 else 2.0
    main(target)
