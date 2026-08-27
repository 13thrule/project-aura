"""Motion-artifact regression using the Cyton's accelerometer as an ICA
reference (design doc section 4.2, and risk #3 in section 7).

`remove_motion_components` (full ICA) is EXPERIMENTAL for Phase 2 — the
design doc gives standing backlog permission to drop it in favor of
`regress_out_motion` (plain linear regression against the accelerometer
channels) the moment ICA components start eating true EEG signal
variance instead of motion artifact. That's not a hypothetical: standard
ICA-with-reference literature assumes richer reference channels than a
single 3-axis accelerometer feeding 8 EEG channels, so expect to need the
fallback. Validate both against CHB-MIT/synthetic motion-contaminated
data before trusting either on real sessions.

`remove_motion_components` should receive `filters.preprocess()`-ed data
(1-50Hz bandpass + mains notch), not raw EEG — MNE's own `ica.fit()` logs
a RuntimeWarning otherwise ("data has not been high-pass filtered"),
since ICA performs poorly on unfiltered data with strong low-frequency
drift. Not enforced in code here (both functions take a plain array/Raw,
no forced pipeline ordering); worth wiring together explicitly once this
plugs into the rest of the pipeline rather than being called standalone.
"""

from __future__ import annotations

import mne
import numpy as np


def build_raw(
    eeg: np.ndarray,
    accel: np.ndarray,
    sfreq: float,
    eeg_ch_names: list[str],
) -> mne.io.RawArray:
    """Pack EEG + accelerometer channels into one MNE Raw object so ICA
    can use the accel channels as a motion reference.

    eeg: (n_eeg_channels, n_times); accel: (3, n_times).
    """
    ch_names = list(eeg_ch_names) + ["accel_x", "accel_y", "accel_z"]
    ch_types = ["eeg"] * len(eeg_ch_names) + ["misc"] * 3
    info = mne.create_info(ch_names=ch_names, sfreq=sfreq, ch_types=ch_types)
    data = np.vstack([eeg, accel])
    return mne.io.RawArray(data, info, verbose=False)


def regress_out_motion(eeg: np.ndarray, accel: np.ndarray) -> np.ndarray:
    """Fallback for `remove_motion_components`: per-channel linear
    regression of each EEG channel against the accelerometer channels,
    subtracting the motion-correlated component.

    Cheaper and far more predictable than ICA, at the cost of only
    removing *linearly*-correlated motion artifact rather than whatever
    ICA can separate. eeg: (n_eeg_channels, n_times); accel: (3, n_times).
    Returns an array the same shape as `eeg`.
    """
    design = np.vstack([accel, np.ones(accel.shape[1])]).T  # (n_times, 4)
    cleaned = np.empty_like(eeg)
    for ch in range(eeg.shape[0]):
        coeffs, *_ = np.linalg.lstsq(design, eeg[ch], rcond=None)
        motion_component = design @ coeffs
        cleaned[ch] = eeg[ch] - motion_component
    return cleaned


def remove_motion_components(
    raw: mne.io.RawArray,
    n_components: int | None = None,
    accel_corr_threshold: float = 0.5,
) -> mne.io.RawArray:
    """EXPERIMENTAL (design doc risk #3 / Phase 2 backlog note): fit ICA
    on the EEG channels, correlate each component against the accel
    channels, and drop components above `accel_corr_threshold`. Switch to
    `regress_out_motion` above without ceremony if this eats true EEG
    signal variance instead of motion artifact.

    Uses manual correlation between each ICA source
    (`ica.get_sources()`) and the accelerometer channels — NOT
    `ica.find_bads_ref()`, which was tried first and confirmed (not just
    suspected) to always raise `ValueError: ICA solution must contain
    both reference and MEG channels` against "misc"-typed accelerometer
    channels; it's hardcoded to MEG reference channels regardless of
    threshold or input shape. Confirmed by actually running it against
    synthetic motion-contaminated data, not by reading the source.
    """
    ica = mne.preprocessing.ICA(n_components=n_components, random_state=0)
    eeg_only = raw.copy().pick("eeg")
    ica.fit(eeg_only, verbose=False)

    sources = ica.get_sources(eeg_only).get_data()  # (n_components, n_times)
    accel = raw.copy().pick(["accel_x", "accel_y", "accel_z"]).get_data()  # (3, n_times)

    exclude = []
    for comp_idx in range(sources.shape[0]):
        corr = np.corrcoef(sources[comp_idx], accel)[0, 1:]  # correlation vs each accel axis
        if np.any(np.abs(corr) >= accel_corr_threshold):
            exclude.append(comp_idx)

    ica.exclude = exclude
    return ica.apply(raw.copy(), verbose=False)
