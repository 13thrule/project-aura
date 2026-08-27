"""Round-trip test for tools/session_to_edf.py: builds a synthetic
storage.rs-style session (same chained-CSV construction as
test_chain_verify.py), converts it to EDF, reloads it with MNE, and
checks the recovered values match the originals within EDF's 16-bit
quantization precision — not just that the script ran without raising."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import mne
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import session_to_edf  # noqa: E402


def _write_synthetic_session(session_dir: Path, eeg_uv: np.ndarray, accel: np.ndarray, sfreq: float):
    """eeg_uv: (8, n), accel: (3, n). Builds samples.csv with the exact
    ChainedCsv construction broker/src/storage.rs uses, at a clean
    (non-jittery) sfreq, so this test isolates EDF export correctness
    from the timing-jitter handling covered separately."""
    session_dir.mkdir(parents=True, exist_ok=True)
    path = session_dir / "samples.csv"
    n = eeg_uv.shape[1]
    prev_hash = bytes(32)
    with path.open("w", newline="") as f:
        f.write("host_received_at_unix," + ",".join(f"ch{i}" for i in range(1, 9))
                + ",accel_x,accel_y,accel_z,chain_hash\n")
        for i in range(n):
            t = i / sfreq
            row = ",".join([f"{t:.6f}"] + [f"{v:.4f}" for v in eeg_uv[:, i]]
                            + [f"{v:.4f}" for v in accel[:, i]])
            new_hash = hashlib.sha256(prev_hash + row.encode("utf-8")).hexdigest()
            f.write(f"{row},{new_hash}\n")
            prev_hash = bytes.fromhex(new_hash)
    return path


def test_round_trips_eeg_values_within_edf_quantization(tmp_path):
    sfreq = 256.0
    n = 512  # exactly 2s, so no trimming is needed — isolates export correctness
    rng = np.random.default_rng(0)
    eeg_uv = rng.uniform(-200, 200, size=(8, n))
    accel = np.zeros((3, n))

    session_dir = tmp_path / "session_test"
    _write_synthetic_session(session_dir, eeg_uv, accel, sfreq)

    out_path = session_to_edf.convert(session_dir, session_dir / "samples.edf")

    raw = mne.io.read_raw_edf(str(out_path), preload=True, verbose=False)
    assert raw.ch_names == session_to_edf.EEG_CHANNEL_NAMES + session_to_edf.ACCEL_CHANNEL_NAMES
    assert raw.info["sfreq"] == sfreq

    recovered_uv = raw.get_data(picks=session_to_edf.EEG_CHANNEL_NAMES) * 1e6
    # EDF's 16-bit integer quantization over a ~400uV range gives a
    # resolution around 400/65536 ~= 0.006uV — 0.1uV is a safe, still
    # tight tolerance that wouldn't pass if the export/reload pipeline
    # were silently corrupting or mis-scaling data.
    assert np.allclose(recovered_uv, eeg_uv, atol=0.1)


def test_trims_trailing_partial_second(tmp_path):
    sfreq = 256.0
    n = 512 + 37  # 2 full seconds plus a partial third second
    eeg_uv = np.zeros((8, n))
    accel = np.zeros((3, n))
    session_dir = tmp_path / "session_test"
    _write_synthetic_session(session_dir, eeg_uv, accel, sfreq)

    out_path = session_to_edf.convert(session_dir, session_dir / "samples.edf")
    raw = mne.io.read_raw_edf(str(out_path), preload=True, verbose=False)
    assert raw.n_times == 512  # the trailing 37 samples were trimmed, not padded/errored


def test_refuses_to_export_a_tampered_session(tmp_path, capsys):
    sfreq = 256.0
    eeg_uv = np.zeros((8, 256))
    accel = np.zeros((3, 256))
    session_dir = tmp_path / "session_test"
    path = _write_synthetic_session(session_dir, eeg_uv, accel, sfreq)

    lines = path.read_text().splitlines()
    lines[5] = lines[5].replace("0.0000", "99.0000", 1)
    path.write_text("\n".join(lines) + "\n", newline="")

    with pytest.raises(SystemExit, match="chain verification failed"):
        session_to_edf.convert(session_dir, session_dir / "samples.edf")
