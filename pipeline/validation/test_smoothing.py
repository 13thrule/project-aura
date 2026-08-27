"""Tests for the consecutive-window smoothing helper in
validate_chbmit_multifeature.py — pure logic, no CHB-MIT data needed."""

import numpy as np

from validate_chbmit_multifeature import apply_consecutive_smoothing


def test_no_smoothing_is_identity():
    pred = np.array([True, False, True, True, False])
    result = apply_consecutive_smoothing(pred, min_consecutive=1)
    np.testing.assert_array_equal(result, pred)


def test_isolated_positive_is_filtered_at_min_consecutive_2():
    # Single isolated True at index 2 should not survive smoothing=2.
    pred = np.array([False, False, True, False, False])
    result = apply_consecutive_smoothing(pred, min_consecutive=2)
    assert not result.any()


def test_two_consecutive_positives_survive_at_min_consecutive_2():
    pred = np.array([False, True, True, False, False])
    result = apply_consecutive_smoothing(pred, min_consecutive=2)
    # Fires starting at the point the streak reaches 2 (index 2 here),
    # not retroactively at index 1 — this is a real, documented latency
    # cost of smoothing, not an oversight.
    expected = np.array([False, False, True, False, False])
    np.testing.assert_array_equal(result, expected)


def test_long_run_stays_true_until_streak_breaks():
    pred = np.array([True, True, True, True, False, True])
    result = apply_consecutive_smoothing(pred, min_consecutive=3)
    expected = np.array([False, False, True, True, False, False])
    np.testing.assert_array_equal(result, expected)


def test_never_fires_if_seizure_shorter_than_min_consecutive():
    """The real tradeoff smoothing introduces: a run of positives
    shorter than min_consecutive is fully suppressed, not partially
    counted. Worth knowing before picking a smoothing level larger than
    the shortest real seizure's window count."""
    pred = np.array([False, True, True, False])
    result = apply_consecutive_smoothing(pred, min_consecutive=3)
    assert not result.any()
