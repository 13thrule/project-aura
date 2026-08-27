"""Synthetic-signal tests for feature extraction (design doc section 4.3)."""

import numpy as np

from aura_pipeline.features import band_power, hjorth_complexity, hjorth_mobility, line_length


def test_line_length_zero_for_constant_signal():
    x = np.ones(250)
    assert line_length(x) == 0.0


def test_line_length_increases_with_amplitude():
    t = np.linspace(0, 1, 250)
    small = np.sin(2 * np.pi * 10 * t)
    large = 5 * np.sin(2 * np.pi * 10 * t)
    assert line_length(large) > line_length(small)


def test_hjorth_mobility_positive_for_noise():
    rng = np.random.default_rng(0)
    x = rng.normal(size=1000)
    assert hjorth_mobility(x) > 0


def test_hjorth_complexity_near_one_for_sine_wave():
    # A pure sine wave is the textbook case where complexity ~= 1.
    t = np.linspace(0, 10, 2500)
    x = np.sin(2 * np.pi * 10 * t)
    assert abs(hjorth_complexity(x) - 1.0) < 0.2


def test_band_power_places_energy_in_correct_band():
    sfreq = 250.0
    t = np.arange(int(4 * sfreq)) / sfreq
    alpha_signal = np.sin(2 * np.pi * 10 * t)  # 10Hz -> alpha band
    powers = band_power(alpha_signal, sfreq)
    assert powers["alpha"] == max(powers.values())
