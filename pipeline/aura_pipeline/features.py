"""Feature extraction (design doc section 4.3): Hjorth parameters, line
length, and FFT spectral band power.

All functions take a single-channel 1D array unless noted, so callers can
map them across channels with whatever windowing scheme the detector
ends up using — that windowing decision belongs to the detector, not
here.
"""

from __future__ import annotations

import numpy as np

BANDS = {
    "delta": (1.0, 4.0),
    "theta": (4.0, 8.0),
    "alpha": (8.0, 13.0),
    "beta": (13.0, 30.0),
    "gamma": (30.0, 50.0),
}


def hjorth_mobility(x: np.ndarray) -> float:
    dx = np.diff(x)
    return float(np.sqrt(np.var(dx) / np.var(x)))


def hjorth_complexity(x: np.ndarray) -> float:
    dx = np.diff(x)
    return float(hjorth_mobility(dx) / hjorth_mobility(x))


def line_length(x: np.ndarray) -> float:
    """Sum of absolute successive differences — Esteller et al. 2001,
    design doc section 10."""
    return float(np.sum(np.abs(np.diff(x))))


def band_power(x: np.ndarray, sfreq: float) -> dict[str, float]:
    """FFT power per band in BANDS, for a single channel/window."""
    n = len(x)
    freqs = np.fft.rfftfreq(n, d=1.0 / sfreq)
    power = np.abs(np.fft.rfft(x)) ** 2
    out: dict[str, float] = {}
    for name, (lo, hi) in BANDS.items():
        mask = (freqs >= lo) & (freqs < hi)
        out[name] = float(np.sum(power[mask]))
    return out
