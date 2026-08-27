"""Synthetic-noise tests for the filter chain, per CLAUDE.md: MNE filter
changes should be validated against synthetic 8-channel arrays, not real
hardware, since no hardware exists yet.
"""

import numpy as np

from aura_pipeline.filters import SAMPLE_RATE_HZ, bandpass_filter, mains_notch_filter, preprocess


def _synthetic_eeg(n_channels: int = 8, seconds: float = 10.0, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n_times = int(seconds * SAMPLE_RATE_HZ)
    t = np.arange(n_times) / SAMPLE_RATE_HZ
    # Broadband noise plus a strong 50Hz mains tone plus an out-of-band
    # 80Hz tone, in volts-scale (MNE expects volts, not microvolts).
    noise = rng.normal(scale=20e-6, size=(n_channels, n_times))
    mains = 50e-6 * np.sin(2 * np.pi * 50 * t)
    out_of_band = 30e-6 * np.sin(2 * np.pi * 80 * t)
    return noise + mains + out_of_band


def test_bandpass_filter_shape_preserved():
    data = _synthetic_eeg()
    filtered = bandpass_filter(data)
    assert filtered.shape == data.shape


def test_bandpass_filter_attenuates_out_of_band_energy():
    data = _synthetic_eeg()
    filtered = bandpass_filter(data)
    # 80Hz is above the 50Hz cutoff — total signal power should drop.
    assert np.sum(filtered**2) < np.sum(data**2)


def test_mains_notch_attenuates_50hz():
    data = _synthetic_eeg()
    notched = mains_notch_filter(data, mains_hz=50.0)

    def power_at_50hz(x: np.ndarray) -> float:
        freqs = np.fft.rfftfreq(x.shape[-1], d=1.0 / SAMPLE_RATE_HZ)
        spectrum = np.abs(np.fft.rfft(x, axis=-1))
        idx = np.argmin(np.abs(freqs - 50.0))
        return float(np.mean(spectrum[:, idx]))

    assert power_at_50hz(notched) < power_at_50hz(data)


def test_preprocess_filter_order_does_not_affect_output():
    """Locks in the finding in preprocess()'s docstring: bandpass_filter
    and mains_notch_filter are both LTI FIR filters, so cascading them in
    either order produces numerically identical output. If this ever
    fails, one of the two filters stopped being LTI (or gained internal
    state) and preprocess()'s docstring claim needs re-verifying, not
    silently trusting."""
    data = _synthetic_eeg()
    notch_then_bandpass = bandpass_filter(mains_notch_filter(data))
    bandpass_then_notch = mains_notch_filter(bandpass_filter(data))
    np.testing.assert_allclose(notch_then_bandpass, bandpass_then_notch, atol=1e-15)
    np.testing.assert_allclose(notch_then_bandpass, preprocess(data), atol=1e-15)
