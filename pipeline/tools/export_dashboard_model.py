"""Trains a real LogisticRegression on chb01's full CHB-MIT data (all
baseline + all seizure files — not a CV fold, since this is the
"production" model the dashboard runs live, a different purpose than
validate_chbmit_multifeature.py's leave-one-seizure-out evaluation) and
exports its weights to JSON, so dashboard/index.html can compute a real
seizure-likelihood score client-side instead of a decorative random walk.

Same 8 features, same order, as validate_chbmit_multifeature.py (line
length, Hjorth mobility/complexity, 5-band FFT power) — reuses that
module's compute_window_features rather than re-deriving the feature
extraction, so the exported model can't silently drift from what's
actually been validated.

Honesty constraints on how this gets used (see dashboard/index.html's
panel caveat, written to match): this is a real trained model computing
a real score from real live features — not synthetic — but it is fit on
ONE subject (chb01), and validation/README.md's chb02 generalization
check found this exact model class does NOT reliably generalize across
subjects. The exported JSON carries that caveat text directly so the
dashboard can't drift from it either.

Usage:
    pipeline\\.venv\\Scripts\\python.exe tools\\export_dashboard_model.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression

sys.path.insert(0, str(Path(__file__).parent.parent / "validation"))
from validate_chbmit_multifeature import (  # noqa: E402
    CHB_ROOT,
    FEATURE_NAMES,
    SUBJECTS,
    WINDOW_SECONDS,
    compute_window_features,
)
from aura_pipeline.datasets import parse_chbmit_summary  # noqa: E402

OUT_PATH = Path(__file__).parents[2] / "dashboard" / "model_chb01.json"

CAVEAT = (
    "Real LogisticRegression (scikit-learn), trained on ALL of chb01's CHB-MIT "
    "recordings (not a held-out evaluation fold) using the same 8 features as "
    "pipeline/aura_pipeline/features.py: line length, Hjorth mobility/complexity, "
    "and 5-band FFT power, each averaged across the 8-channel montage. Computed "
    "live, in this browser, from this panel's actual buffered signal -- not a "
    "synthetic or random value. IMPORTANT CAVEAT: fit on a single subject. "
    "pipeline/validation/README.md's chb02 generalization check found this exact "
    "model class does NOT reliably transfer to a different person (sensitivity "
    "dropped from 7/7 on chb01 to 2/3 on chb02, false-positive rate rose ~5-10x). "
    "Read this score as 'how much does this signal's features resemble chb01's own "
    "seizures', not a validated general-purpose or clinical detector."
)


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


def main() -> None:
    subject = "chb01"
    data_dir = CHB_ROOT / subject
    baseline_files = SUBJECTS[subject]["baseline_files"]
    seizure_files = SUBJECTS[subject]["seizure_files"]
    all_files = baseline_files + seizure_files

    missing = [f for f in all_files if not (data_dir / f).exists()]
    if missing:
        raise SystemExit(f"Missing {len(missing)} file(s) for {subject}: {missing}")

    seizures_by_file = parse_chbmit_summary(data_dir / f"{subject}-summary.txt")
    print(f"[{subject}] extracting features from all {len(all_files)} files for the production fit...")

    X_parts, y_parts = [], []
    for f in all_files:
        feats = compute_window_features(data_dir / f)
        labels = _seizure_label_mask(len(feats), seizures_by_file.get(f, []))
        X_parts.append(feats)
        y_parts.append(labels)
    X = np.concatenate(X_parts)
    y = np.concatenate(y_parts)

    clf = LogisticRegression(class_weight="balanced", max_iter=1000)
    clf.fit(X, y)

    train_acc_sensitivity = float(clf.predict(X)[y].mean())  # on training data, informational only
    print(f"fit on {len(X)} windows ({int(y.sum())} seizure windows). "
          f"training-set recall (NOT a held-out metric): {train_acc_sensitivity:.3f}")

    model = {
        "feature_names": FEATURE_NAMES,
        "window_seconds": WINDOW_SECONDS,
        "coef": clf.coef_[0].tolist(),
        "intercept": float(clf.intercept_[0]),
        "trained_on": f"{subject} (all {len(all_files)} recordings, full-data fit -- not a CV fold)",
        "caveat": CAVEAT,
    }
    OUT_PATH.write_text(json.dumps(model, indent=2))
    print(f"wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
