"""Tests for chain_verify.py, checked against a synthetic chain built the
same way broker/src/storage.rs builds a real one — not against a fixture
file that might itself already be stale."""

from __future__ import annotations

import hashlib

import pytest

from aura_pipeline.chain_verify import verify_chained_csv


def _write_chained_csv(path, header: str, rows: list[str]) -> None:
    """Builds a CSV using the exact same construction as
    ChainedCsv::append_chained in storage.rs, so tests exercise the real
    algorithm rather than a simplified stand-in."""
    prev_hash = bytes(32)
    with path.open("w", newline="") as f:
        f.write(f"{header},chain_hash\n")
        for row in rows:
            new_hash = hashlib.sha256(prev_hash + row.encode("utf-8")).hexdigest()
            f.write(f"{row},{new_hash}\n")
            prev_hash = bytes.fromhex(new_hash)


def test_verifies_a_correctly_chained_file(tmp_path):
    path = tmp_path / "samples.csv"
    _write_chained_csv(
        path,
        "host_received_at_unix,ch1,ch2",
        ["1700000000.0,1.5,-2.5", "1700000001.0,1.6,-2.4", "1700000002.0,1.7,-2.3"],
    )
    ok, msg = verify_chained_csv(path)
    assert ok is True
    assert "3 rows" in msg


def test_detects_a_tampered_row(tmp_path):
    path = tmp_path / "samples.csv"
    _write_chained_csv(
        path,
        "host_received_at_unix,ch1,ch2",
        ["1700000000.0,1.5,-2.5", "1700000001.0,1.6,-2.4", "1700000002.0,1.7,-2.3"],
    )
    lines = path.read_text().splitlines()
    # Tamper with a data value in the middle row, leaving its stored
    # chain_hash untouched — this is exactly the kind of edit the chain
    # exists to catch.
    lines[2] = lines[2].replace("1.6", "99.9")
    path.write_text("\n".join(lines) + "\n", newline="")

    ok, msg = verify_chained_csv(path)
    assert ok is False
    assert "chain broken" in msg


def test_detects_a_missing_row(tmp_path):
    path = tmp_path / "samples.csv"
    _write_chained_csv(
        path,
        "host_received_at_unix,ch1,ch2",
        ["1700000000.0,1.5,-2.5", "1700000001.0,1.6,-2.4", "1700000002.0,1.7,-2.3"],
    )
    lines = path.read_text().splitlines()
    del lines[2]  # remove the middle data row, keep everything else as-is
    path.write_text("\n".join(lines) + "\n", newline="")

    ok, msg = verify_chained_csv(path)
    assert ok is False
    assert "chain broken" in msg


def test_rejects_a_header_without_chain_hash_column(tmp_path):
    path = tmp_path / "samples.csv"
    path.write_text("host_received_at_unix,ch1,ch2\n1700000000.0,1.5,-2.5,deadbeef\n", newline="")
    ok, msg = verify_chained_csv(path)
    assert ok is False
    assert "header" in msg


def test_empty_file_with_only_header_verifies_trivially(tmp_path):
    path = tmp_path / "samples.csv"
    path.write_text("host_received_at_unix,ch1,ch2,chain_hash\n", newline="")
    ok, msg = verify_chained_csv(path)
    assert ok is True
    assert "0 data rows" in msg
