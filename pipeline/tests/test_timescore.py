"""Tests for aura_pipeline.timescore, checked against timescoring's own
documented example (github.com/esl-epfl/timescoring README) so this
isn't just testing our wrapper against itself."""

from __future__ import annotations

import numpy as np
from timescoring import scoring

from aura_pipeline.timescore import score_windows, windows_to_events


def test_windows_to_events_merges_consecutive_true_windows():
    mask = np.array([False, True, True, False, False, True, False])
    events = windows_to_events(mask, window_seconds=2.0)
    assert events == [(2.0, 6.0), (10.0, 12.0)]


def test_windows_to_events_empty_for_all_false():
    mask = np.zeros(5, dtype=bool)
    assert windows_to_events(mask, window_seconds=1.0) == []


def test_score_windows_matches_timescoring_documented_example():
    # Same scenario as timescoring's own README example, expressed as
    # 1-second windows (fs=1 there): ref events (8-12min, 30-35min,
    # 48-50min), hyp events (8-12min, 28-32min, 50.5-51min, 60-62min),
    # over a 66-minute recording. Documented result: sensitivity=1.0,
    # precision=0.75, fpRate=21.82(ish)/24h.
    window_seconds = 1.0
    duration_s = 66 * 60
    n_windows = int(duration_s / window_seconds)

    def mask_from_events(events_min):
        m = np.zeros(n_windows, dtype=bool)
        for start_min, end_min in events_min:
            m[int(start_min * 60):int(end_min * 60)] = True
        return m

    ref_mask = mask_from_events([(8, 12), (30, 35), (48, 50)])
    hyp_mask = mask_from_events([(8, 12), (28, 32), (50.5, 51), (60, 62)])

    result = score_windows(hyp_mask, ref_mask, window_seconds)
    assert result.sensitivity == 1.0
    assert abs(result.precision - 0.75) < 1e-9
    assert abs(result.fpRate - 21.818181818181817) < 1e-6


def test_score_windows_perfect_match_has_no_false_positives():
    mask = np.array([False, True, True, False, True, True, True, False])
    result = score_windows(mask, mask, window_seconds=2.0)
    assert result.sensitivity == 1.0
    assert result.fp == 0


def test_score_windows_rejects_mismatched_lengths():
    import pytest

    with pytest.raises(ValueError):
        score_windows(np.zeros(5, dtype=bool), np.zeros(6, dtype=bool), 2.0)
