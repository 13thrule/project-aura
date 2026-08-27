"""Wraps `esl-epfl/timescoring` — the actual scoring library behind the
SzCORE benchmark already cited in design doc section 10 (Dan et al.
2024) — so validation scripts can report sensitivity/FP-rate in the
field's real standard instead of only the hand-rolled counting
`validate_chbmit_multifeature.py` has used up to now. Not a replacement
for that hand-rolled version (kept for its own working history and
because it doesn't require this dependency) — a cross-check reported
alongside it, see `validation/README.md`'s SzCORE section for what
agrees and what doesn't between the two.
"""

from __future__ import annotations

import numpy as np
from timescoring import scoring
from timescoring.annotations import Annotation

DEFAULT_EVENT_PARAMS = scoring.EventScoring.Parameters()


def windows_to_events(mask: np.ndarray, window_seconds: float) -> list[tuple[float, float]]:
    """Converts a boolean per-window array into a list of (start_s,
    end_s) event tuples, merging consecutive True windows into one
    event — timescoring's Annotation wants events in seconds, not a
    per-window mask sampled at a fractional Hz, so this avoids passing
    it a sub-1Hz `fs` (untested/unclear territory for that API) entirely."""
    events = []
    n = len(mask)
    i = 0
    while i < n:
        if mask[i]:
            j = i
            while j < n and mask[j]:
                j += 1
            events.append((i * window_seconds, j * window_seconds))
            i = j
        else:
            i += 1
    return events


def score_windows(
    pred_mask: np.ndarray,
    true_mask: np.ndarray,
    window_seconds: float,
    params: scoring.EventScoring.Parameters = DEFAULT_EVENT_PARAMS,
) -> scoring.EventScoring:
    """Event-level SzCORE scoring for one recording's per-window
    prediction/label arrays. `params` defaults to SzCORE's own defaults
    (toleranceStart=30s, toleranceEnd=60s, minOverlap=0,
    maxEventDuration=300s, minDurationBetweenEvents=90s) — pass an
    explicit `scoring.EventScoring.Parameters(...)` to use different
    tolerances, but don't do that silently when comparing against
    published SzCORE numbers.
    """
    if len(pred_mask) != len(true_mask):
        raise ValueError(f"pred/true length mismatch: {len(pred_mask)} vs {len(true_mask)}")

    duration_s = len(true_mask) * window_seconds
    ref = Annotation(windows_to_events(true_mask, window_seconds), 1, int(round(duration_s)))
    hyp = Annotation(windows_to_events(pred_mask, window_seconds), 1, int(round(duration_s)))
    return scoring.EventScoring(ref, hyp, params)
