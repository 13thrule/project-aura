"""Tests for tools/export_chbmit_bids.py, against real downloaded chb01
files (not a synthetic fixture — the whole point is correctly bridging
CHB-MIT's real channel-naming quirks into epilepsy2bids's expected
double-banana montage, see that script's module doc). Ground truth
(seizure timing) is the same as test_datasets.py's, since both read the
same real chb01-summary.txt."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from epilepsy2bids import eeg as e2b_eeg

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import export_chbmit_bids  # noqa: E402

CHB01_DIR = Path(__file__).parents[2] / "data" / "raw" / "chbmit" / "chb01"

pytestmark = pytest.mark.skipif(
    not (CHB01_DIR / "chb01-summary.txt").exists(),
    reason="chb01 not downloaded — see pipeline/validation/README.md",
)


def _read_tsv_rows(path: Path) -> list[dict]:
    lines = path.read_text().splitlines()
    header = lines[0].split("\t")
    return [dict(zip(header, line.split("\t"))) for line in lines[1:]]


def test_seizure_file_produces_a_montage_epilepsy2bids_recognizes_and_a_correct_event(tmp_path, monkeypatch):
    monkeypatch.setattr(export_chbmit_bids, "OUT_ROOT", tmp_path)
    edf_out, tsv_out = export_chbmit_bids.convert("chb01", "chb01_16.edf")

    # The real correctness check: epilepsy2bids's OWN auto-detecting
    # loader accepts the file we wrote, not just "the script ran."
    reloaded = e2b_eeg.Eeg.loadEdfAutoDetectMontage(str(edf_out))
    assert reloaded.montage == e2b_eeg.Eeg.Montage.BIPOLAR
    assert tuple(reloaded.channels) == e2b_eeg.Eeg.BIPOLAR_DBANANA
    assert reloaded.fs == 256.0
    assert reloaded.data.shape == (18, 921600)

    rows = _read_tsv_rows(tsv_out)
    assert len(rows) == 1
    # Ground truth transcribed from chb01-summary.txt (same as test_datasets.py).
    assert float(rows[0]["onset"]) == 1015.0
    assert float(rows[0]["duration"]) == 51.0
    assert rows[0]["eventType"] == "sz"


def test_baseline_file_produces_a_single_background_event(tmp_path, monkeypatch):
    monkeypatch.setattr(export_chbmit_bids, "OUT_ROOT", tmp_path)
    _, tsv_out = export_chbmit_bids.convert("chb01", "chb01_01.edf")

    rows = _read_tsv_rows(tsv_out)
    assert len(rows) == 1
    assert rows[0]["eventType"] == "bckg"
    assert float(rows[0]["onset"]) == 0.0
    assert float(rows[0]["duration"]) == 3600.0
