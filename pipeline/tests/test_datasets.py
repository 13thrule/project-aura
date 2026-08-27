"""Tests for CHB-MIT summary parsing, against the real downloaded
chb01-summary.txt (data/raw/chbmit/chb01/) — not a synthetic fixture,
since the whole point is correctly parsing PhysioNet's actual format.
Ground truth below was read directly from that file.
"""

from pathlib import Path

import pytest

from aura_pipeline.datasets import parse_chbmit_summary

SUMMARY_PATH = Path(__file__).parents[2] / "data" / "raw" / "chbmit" / "chb01" / "chb01-summary.txt"

pytestmark = pytest.mark.skipif(
    not SUMMARY_PATH.exists(),
    reason="chb01-summary.txt not downloaded — see pipeline/validation/README.md",
)


def test_parses_known_seizure_files():
    seizures = parse_chbmit_summary(SUMMARY_PATH)

    # Ground truth transcribed directly from chb01-summary.txt.
    assert seizures["chb01_03.edf"] == [(2996.0, 3036.0)]
    assert seizures["chb01_04.edf"] == [(1467.0, 1494.0)]
    assert seizures["chb01_15.edf"] == [(1732.0, 1772.0)]
    assert seizures["chb01_16.edf"] == [(1015.0, 1066.0)]
    assert seizures["chb01_18.edf"] == [(1720.0, 1810.0)]
    assert seizures["chb01_21.edf"] == [(327.0, 420.0)]
    assert seizures["chb01_26.edf"] == [(1862.0, 1963.0)]


def test_seizure_free_files_have_empty_list():
    seizures = parse_chbmit_summary(SUMMARY_PATH)
    assert seizures["chb01_01.edf"] == []
    assert seizures["chb01_02.edf"] == []
    assert seizures["chb01_05.edf"] == []
    assert seizures["chb01_06.edf"] == []


def test_total_seizure_count_matches_known_chb01_total():
    seizures = parse_chbmit_summary(SUMMARY_PATH)
    total = sum(len(v) for v in seizures.values())
    assert total == 7  # chb01 has 7 seizures across its recordings
