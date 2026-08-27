"""Synthetic tests for both motion-cleaning approaches in ica_motion.py."""

import numpy as np

from aura_pipeline.ica_motion import build_raw, regress_out_motion, remove_motion_components


def test_regress_out_motion_removes_linear_accel_component():
    rng = np.random.default_rng(0)
    n_times = 1000
    accel = rng.normal(size=(3, n_times))

    true_signal = np.sin(np.linspace(0, 20, n_times))
    motion_leak = 3.0 * accel[0] - 1.5 * accel[1] + 0.5 * accel[2]
    contaminated = (true_signal + motion_leak)[np.newaxis, :]  # 1 EEG channel

    cleaned = regress_out_motion(contaminated, accel)

    # Cleaned signal should correlate far better with the true signal
    # than the contaminated one did.
    contaminated_corr = np.corrcoef(contaminated[0], true_signal)[0, 1]
    cleaned_corr = np.corrcoef(cleaned[0], true_signal)[0, 1]
    assert cleaned_corr > contaminated_corr
    assert cleaned_corr > 0.9


def test_remove_motion_components_runs_without_raising():
    """Regression test for a real bug: an earlier version used
    ica.find_bads_ref(), which is hardcoded to MEG reference channels and
    ALWAYS raised `ValueError: ICA solution must contain both reference
    and MEG channels` against "misc"-typed accelerometer channels —
    confirmed by actually running it, not by reading MNE's source. This
    just needs to not raise; the next test checks it's actually doing
    something useful, not just silently doing nothing."""
    rng = np.random.default_rng(0)
    n_times = 2500
    accel = rng.normal(size=(3, n_times))
    eeg = rng.normal(scale=1e-5, size=(8, n_times))
    raw = build_raw(eeg, accel, sfreq=250.0, eeg_ch_names=[f"ch{i}" for i in range(8)])
    remove_motion_components(raw)  # must not raise


def test_remove_motion_components_improves_correlation_with_true_signal():
    rng = np.random.default_rng(0)
    n_times = 5000
    sfreq = 250.0
    t = np.arange(n_times) / sfreq

    accel = rng.normal(size=(3, n_times))
    true_signal = np.array([np.sin(2 * np.pi * (5 + i) * t) * 1e-5 for i in range(8)])
    motion_leak = (4.0 * accel[0]) * 1e-5  # strong, shared contamination across all channels
    eeg = true_signal + motion_leak[None, :]

    raw = build_raw(eeg, accel, sfreq, [f"ch{i}" for i in range(8)])
    cleaned = remove_motion_components(raw).get_data()[:8]

    for ch in range(8):
        before = np.corrcoef(eeg[ch], true_signal[ch])[0, 1]
        after = np.corrcoef(cleaned[ch], true_signal[ch])[0, 1]
        assert after > before
