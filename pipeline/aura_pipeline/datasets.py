"""Baseline dataset loaders (design doc section 4.1): CHB-MIT and TUH.

CHB-MIT annotation parsing is implemented (see `parse_chbmit_summary`
below) and used by `pipeline/validation/validate_chbmit.py` — the design
doc section 4.1 / CLAUDE.md "Data constraints" gate this project has been
treating as a hard prerequisite before any patient data. TUH/TUSZ is
still not implemented (see TODO at the bottom): it requires a data use
agreement/registration, and hasn't been pulled into this validation pass.
"""

from __future__ import annotations

import re
from pathlib import Path

import mne


def load_edf_recording(path: str | Path) -> mne.io.Raw:
    """Load a single EDF recording (CHB-MIT or TUH file) as an MNE Raw
    object."""
    return mne.io.read_raw_edf(str(path), preload=True, verbose=False)


def parse_chbmit_summary(summary_path: str | Path) -> dict[str, list[tuple[float, float]]]:
    """Parse a CHB-MIT `chbXX-summary.txt` file into
    `{filename: [(seizure_start_s, seizure_end_s), ...]}`.

    Format (real example, from chb01-summary.txt on PhysioNet):

        File Name: chb01_03.edf
        File Start Time: 13:43:04
        File End Time: 14:43:04
        Number of Seizures in File: 1
        Seizure Start Time: 2996 seconds
        Seizure End Time: 3036 seconds

    A file can have zero, one, or multiple seizures (multi-seizure files
    repeat the "Seizure Start/End Time" pair once per seizure, in the
    later-subject summary files that use a slightly different "Seizure N
    Start Time" label for exactly this reason — both label forms are
    handled here). Files with zero seizures have no such lines at all.
    """
    text = Path(summary_path).read_text()
    seizures_by_file: dict[str, list[tuple[float, float]]] = {}

    file_blocks = re.split(r"\n(?=File Name:)", text)
    for block in file_blocks:
        name_match = re.search(r"File Name:\s*(\S+)", block)
        if not name_match:
            continue
        filename = name_match.group(1)

        starts = [float(s) for s in re.findall(r"Seizure(?:\s+\d+)?\s+Start Time:\s*(\d+)\s*seconds", block)]
        ends = [float(s) for s in re.findall(r"Seizure(?:\s+\d+)?\s+End Time:\s*(\d+)\s*seconds", block)]
        seizures_by_file[filename] = list(zip(starts, ends))

    return seizures_by_file


# TODO(pipeline engineer):
#   - TUH/TUSZ: https://isip.piconepress.com/projects/tuh_eeg/ — requires
#     a data use agreement/registration before download; check current
#     access terms, don't assume open download.
