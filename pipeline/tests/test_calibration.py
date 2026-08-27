"""Tests for per-patient threshold calibration — synthetic probabilities,
no CHB-MIT data needed."""

import numpy as np
import pytest

from aura_pipeline.calibration import calibrate_threshold_for_target_fp_rate


def test_calibrated_threshold_achieves_approximately_target_fp_rate():
    rng = np.random.default_rng(0)
    window_seconds = 2.0
    n_windows = 1800  # 1 hour of 2s windows
    baseline_proba = rng.uniform(0, 1, size=n_windows)

    threshold = calibrate_threshold_for_target_fp_rate(baseline_proba, window_seconds, target_fp_per_hour=10.0)
    actual_fp_count = int((baseline_proba >= threshold).sum())
    # Should land close to 10 for this 1-hour baseline window — allow
    # some slack since target_fp_count is rounded to a whole window count.
    assert 7 <= actual_fp_count <= 13


def test_zero_target_fp_sets_threshold_above_every_baseline_value():
    baseline_proba = np.array([0.1, 0.3, 0.5, 0.7, 0.9])
    threshold = calibrate_threshold_for_target_fp_rate(baseline_proba, window_seconds=2.0, target_fp_per_hour=0.0)
    assert threshold > baseline_proba.max()
    assert (baseline_proba >= threshold).sum() == 0


def test_higher_target_fp_rate_gives_lower_threshold():
    rng = np.random.default_rng(1)
    baseline_proba = rng.uniform(0, 1, size=1800)
    strict = calibrate_threshold_for_target_fp_rate(baseline_proba, 2.0, target_fp_per_hour=1.0)
    loose = calibrate_threshold_for_target_fp_rate(baseline_proba, 2.0, target_fp_per_hour=50.0)
    assert loose < strict


def test_raises_on_empty_baseline():
    with pytest.raises(ValueError):
        calibrate_threshold_for_target_fp_rate(np.array([]), window_seconds=2.0, target_fp_per_hour=1.0)
