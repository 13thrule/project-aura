"""Converts one CHB-MIT recording to the double-banana bipolar montage +
BIDS-style events.tsv that `esl-epfl/epilepsy2bids` (the reference
implementation behind the SzCORE benchmark already cited in design doc
section 10) expects — using that library's own `Eeg`/`Annotations`
classes to write the files, not a hand-rolled EDF/TSV writer.

## Scope — read this before assuming this is "the BIDS exporter"

This is deliberately NOT the full BIDS/anonymization pipeline design doc
section 5 calls for ("its own deliverable... its own validation pass,"
not a quick script). A real, complete BIDS-EEG dataset also needs
`dataset_description.json`, `participants.tsv`, per-recording sidecar
`*_eeg.json`, `*_channels.tsv`, and the `sub-XX/ses-XX/eeg/` directory
layout — none of that is built here. What this script *does* produce is
real and useful on its own: a re-referenced, correctly-labeled EDF plus
a real `events.tsv` written by the library that actually defines that
format, which is the harder, easier-to-get-wrong part of the job.

## The montage mismatch this script exists to bridge

`epilepsy2bids.eeg.Eeg.loadEdfAutoDetectMontage()` — the library's own
loader — rejects CHB-MIT files as-is:
`ValueError: Unrecognized electrode: FP1-F7. Expected Fp1 or Fp1-Avg or
Fp1-F3` (confirmed by actually running it against chb01_16.edf, not
assumed from the docs). Two real, separate mismatches, not one:

1. **Case**: CHB-MIT uses `FP1`/`FP2`; epilepsy2bids's fixed channel
   list (`Eeg.ELECTRODES_10_20`) uses `Fp1`/`Fp2`.
2. **Nomenclature era**: CHB-MIT uses the modern (post-1985 IFCN/ACNS)
   `T7`/`T8`/`P7`/`P8`; epilepsy2bids's `Eeg.BIPOLAR_DBANANA` uses the
   older `T3`/`T4`/`T5`/`T6` these positions used to be called. The
   equivalence (T3=T7, T4=T8, T5=P7, T6=P8) is a real, documented ACNS
   convention change, not a guess — see the ACNS "Guidelines for Standard
   Electrode Position Nomenclature." Verified here before writing
   `CHBMIT_TO_DBANANA` below, the same way T8-P8-0-vs-1 was verified
   against real files rather than assumed (see validation/README.md).

`CHBMIT_TO_DBANANA` below is the explicit, checked mapping from chb01's
raw 18 double-banana channel labels (see `aura_pipeline.datasets`'s
T8-P8-0 handling — reused, not re-derived) to epilepsy2bids's
`BIPOLAR_DBANANA` order. This only covers the double-banana subset — the
extra channels some CHB-MIT files carry (e.g. `P7-T7`, `FT9-FT10`) are
outside the standard double-banana montage and are dropped, not merged
in.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from epilepsy2bids import eeg as e2b_eeg
from epilepsy2bids.annotations import Annotations

sys.path.insert(0, str(Path(__file__).parent.parent))
from aura_pipeline.datasets import load_edf_recording, parse_chbmit_summary  # noqa: E402

CHB_ROOT = Path(__file__).parents[2] / "data" / "raw" / "chbmit"
OUT_ROOT = Path(__file__).parents[2] / "data" / "derivatives" / "bids_chbmit"

# Target order/names: epilepsy2bids.eeg.Eeg.BIPOLAR_DBANANA. Source: the
# CHB-MIT channel name (post T8-P8-0/-1 dedup, see datasets.py) that maps
# to it under the case + T7/T8/P7/P8 <-> T3/T4/T5/T6 equivalence above.
CHBMIT_TO_DBANANA: list[tuple[str, str]] = [
    ("Fp1-F3", "FP1-F3"),
    ("F3-C3", "F3-C3"),
    ("C3-P3", "C3-P3"),
    ("P3-O1", "P3-O1"),
    ("Fp1-F7", "FP1-F7"),
    ("F7-T3", "F7-T7"),
    ("T3-T5", "T7-P7"),
    ("T5-O1", "P7-O1"),
    ("Fz-Cz", "FZ-CZ"),
    ("Cz-Pz", "CZ-PZ"),
    ("Fp2-F4", "FP2-F4"),
    ("F4-C4", "F4-C4"),
    ("C4-P4", "C4-P4"),
    ("P4-O2", "P4-O2"),
    ("Fp2-F8", "FP2-F8"),
    ("F8-T4", "F8-T8"),
    ("T4-T6", "T8-P8-0"),
    ("T6-O2", "P8-O2"),
]

assert tuple(dst for dst, _ in CHBMIT_TO_DBANANA) == e2b_eeg.Eeg.BIPOLAR_DBANANA, (
    "CHBMIT_TO_DBANANA's target order has drifted from epilepsy2bids's own "
    "BIPOLAR_DBANANA — fix the mapping table above, don't silently mismatch order."
)


def convert(subject: str, filename: str) -> tuple[Path, Path]:
    edf_path = CHB_ROOT / subject / filename
    if not edf_path.exists():
        raise SystemExit(f"not found: {edf_path} (download it first — see validation/README.md)")

    raw = load_edf_recording(edf_path)
    missing = [src for _, src in CHBMIT_TO_DBANANA if src not in raw.ch_names]
    if missing:
        raise SystemExit(
            f"{filename}: missing expected double-banana channel(s) {missing} — "
            f"this file's montage may differ from chb01's; check raw.ch_names before trusting "
            f"CHBMIT_TO_DBANANA against it."
        )

    raw.pick([src for _, src in CHBMIT_TO_DBANANA])
    raw.reorder_channels([src for _, src in CHBMIT_TO_DBANANA])
    fs = int(raw.info["sfreq"])
    data_uv = raw.get_data() * 1e6  # volts -> microvolts, matching CHB-MIT's own EDF physical units

    dst_names = tuple(dst for dst, _ in CHBMIT_TO_DBANANA)
    e = e2b_eeg.Eeg(
        data=data_uv,
        channels=dst_names,
        fs=fs,
        montage=e2b_eeg.Eeg.Montage.BIPOLAR,
    )

    subject_out = OUT_ROOT / subject
    subject_out.mkdir(parents=True, exist_ok=True)
    stem = filename.replace(".edf", "")
    edf_out = subject_out / f"{stem}_dbanana.edf"
    tsv_out = subject_out / f"{stem}_events.tsv"

    e.saveEdf(str(edf_out))

    seizures_by_file = parse_chbmit_summary(CHB_ROOT / subject / f"{subject}-summary.txt")
    duration_s = data_uv.shape[1] / fs
    events = seizures_by_file.get(filename, [])
    annotations = Annotations.loadEvents(events, duration_s)
    annotations.saveTsv(str(tsv_out))

    print(f"wrote {edf_out} ({data_uv.shape[1]} samples @ {fs}Hz, 18 double-banana channels)")
    print(f"wrote {tsv_out} ({len(events)} seizure event(s))")
    return edf_out, tsv_out


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: export_chbmit_bids.py <subject> <filename.edf>")
    convert(sys.argv[1], sys.argv[2])
