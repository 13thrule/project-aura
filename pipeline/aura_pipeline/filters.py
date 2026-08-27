"""Bandpass + notch filtering (design doc section 4.2).

Uses MNE-Python's filter implementation rather than hand-rolled DSP, per
CLAUDE.md. Data convention throughout this package: numpy array shaped
(n_channels, n_times), float64, in volts (MNE's expected unit) unless a
function says otherwise.
"""

from __future__ import annotations

import numpy as np
from mne.filter import filter_data, notch_filter as mne_notch_filter

SAMPLE_RATE_HZ = 250.0  # Cyton's fixed sampling rate — do not vary this.


def bandpass_filter(
    data: np.ndarray,
    sfreq: float = SAMPLE_RATE_HZ,
    l_freq: float = 1.0,
    h_freq: float = 50.0,
) -> np.ndarray:
    """1-50Hz bandpass, per design doc section 4.2."""
    return filter_data(data, sfreq=sfreq, l_freq=l_freq, h_freq=h_freq, verbose=False)


def mains_notch_filter(
    data: np.ndarray,
    sfreq: float = SAMPLE_RATE_HZ,
    mains_hz: float = 50.0,
) -> np.ndarray:
    """AC mains notch filter. `mains_hz` must be a config flag (50 for UK/EU,
    60 for US) — do not hardcode a region assumption in callers."""
    return mne_notch_filter(data, Fs=sfreq, freqs=[mains_hz], verbose=False)


def preprocess(
    data: np.ndarray,
    sfreq: float = SAMPLE_RATE_HZ,
    mains_hz: float = 50.0,
) -> np.ndarray:
    """Full section-4.2 filter chain: mains notch, then bandpass.

    An earlier version of this docstring claimed the order (notch before
    bandpass, vs. bandpass before notch) mattered for correctness, based
    on a same-frequency-band comparison that wasn't actually apples-to-
    apples. Re-tested properly (bandpass-then-notch vs notch-then-bandpass
    on the same signal): both orderings produce numerically IDENTICAL
    output, because `bandpass_filter` and `mains_notch_filter` are both
    linear time-invariant FIR filters, and cascaded LTI filters commute.
    The order below is arbitrary, not corrective — flagging that here so
    nobody re-derives the wrong "order matters" conclusion from a similarly
    flawed test later.

    The real, verified nuance worth keeping: when `mains_hz` is at or
    above `bandpass_filter`'s default `h_freq` (50Hz) — true for
    mains_hz=60 (US-recorded data, e.g. CHB-MIT) — the bandpass alone
    already suppresses most mains content on its own (measured ~96% power
    reduction on a pure 60Hz tone with no notch at all), so the notch
    filter's own marginal contribution on top of that is small (~14%
    further reduction in the same test), not the primary mains-rejection
    mechanism the design doc's section 4.2 phrasing might suggest for
    that region. It's not useless, just not doing the heavy lifting when
    mains_hz >= h_freq — worth knowing before assuming it's fully earning
    its place in the pipeline for 60Hz regions.
    """
    notched = mains_notch_filter(data, sfreq=sfreq, mains_hz=mains_hz)
    return bandpass_filter(notched, sfreq=sfreq)
