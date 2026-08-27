"""Per-patient threshold calibration for a new patient.

Why this exists: `pipeline/validation/README.md`'s chb01->chb02 check
showed a single population-shared decision threshold does NOT transfer
between patients (design doc section 7 risk #4) — the same settings that
held 7/7 sensitivity at 1-4 FP/hr on chb01 dropped to 2/3 at 18-25 FP/hr
on chb02. A brand-new patient has no labeled seizure examples to fit a
classifier against — but they DO have baseline (seizure-free) recordings,
per the existing Phase 3 protocol (design doc section 6: "Baseline daily
sessions (10-20 min, resting)... to characterize this specific setup's
noise floor"). This module uses exactly that data — nothing more — to
calibrate a personal decision threshold on top of a population-pretrained
classifier.

What this can and can't do, stated plainly so it doesn't get overclaimed
later:
- CAN calibrate: "how sensitive should the alarm be to keep THIS
  patient's false-positive rate near a target," using only their own
  baseline data. No seizure labels from them required or used.
- CANNOT calibrate: whether the underlying classifier actually recognizes
  this patient's seizure patterns at all — that still depends on the
  population classifier's features generalizing to them, which section
  4.1's chb01/chb02 check shows is imperfect. Calibration fixes the
  operating POINT on an existing model, not the model's blind spots. See
  `pipeline/validation/validate_chbmit_calibrated.py` for the honest,
  leave-one-subject-out test of how much this actually helps.
"""

from __future__ import annotations

import numpy as np


def calibrate_threshold_for_target_fp_rate(
    baseline_proba: np.ndarray,
    window_seconds: float,
    target_fp_per_hour: float,
) -> float:
    """Given a classifier's predicted probabilities on a new patient's own
    baseline (seizure-free) windows ONLY, return the probability
    threshold that keeps their false-positive rate near
    `target_fp_per_hour`.

    No seizure labels are used or needed — this is exactly the data
    available before a patient has ever had a recorded seizure.
    """
    n_windows = len(baseline_proba)
    total_hours = (n_windows * window_seconds) / 3600
    if total_hours <= 0:
        raise ValueError("need at least one window of baseline data to calibrate against")

    target_fp_count = max(0, min(n_windows - 1, int(round(target_fp_per_hour * total_hours))))
    sorted_desc = np.sort(baseline_proba)[::-1]

    if target_fp_count == 0:
        # No baseline window is allowed to fire at all — set the
        # threshold just above the single highest baseline probability
        # observed, not at 1.0, so it stays meaningful if predict_proba
        # never actually reaches 1.0 on this patient's data.
        return float(sorted_desc[0]) + 1e-6

    # The threshold at which exactly `target_fp_count` baseline windows
    # would have fired: the (target_fp_count)-th highest probability.
    return float(sorted_desc[target_fp_count])
