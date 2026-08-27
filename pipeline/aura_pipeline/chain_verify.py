"""Verifies the tamper-evident hash chain `broker/src/storage.rs` writes
into every `samples.csv`/`triggers.csv` (design doc section 2.5). Before
this module existed, that verification logic only lived in one place:
`dashboard/index.html`'s client-side JS (for trigger events only, over a
live WebSocket) — there was no way to verify a session file already
written to disk without opening a browser. This re-implements the same
construction in Python so any tool in `pipeline/` (this session's
`tools/session_to_edf.py`, or a future BIDS export pass) can check a
session's integrity directly.

Mirrors `ChainedCsv::append_chained` in `broker/src/storage.rs`
byte-for-byte: each row's `chain_hash` = `sha256(prev_hash_bytes +
row_text_bytes)`, chained from an all-zero 32-byte genesis, where
`row_text_bytes` is the exact CSV text of that row *excluding* the
trailing `chain_hash` column (not a re-serialization of parsed values —
that would only work if this matched Rust's float-to-string formatting
exactly, which is not a safe assumption to make). Splitting on the last
comma and hashing the raw text preserves that byte-for-byte guarantee
regardless of formatting.

Scope limit, same as storage.rs's own module doc and design doc section
2.5: this proves "unmodified since this file was written," not
cryptographic proof of physical origin. Don't blur that distinction.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

GENESIS_HASH = bytes(32)


def verify_chained_csv(path: Path | str) -> tuple[bool, str]:
    """Re-hashes every row from scratch and compares against the stored
    chain_hash column. Returns (ok, message) rather than raising, since a
    broken chain is an expected, reportable outcome for callers to
    surface (e.g. refuse to export a session that fails), not a bug.
    Catches corruption, edits, reordering, or a deleted row anywhere in
    the file — not just a tampered final row — because each row's hash
    depends on every row before it.
    """
    path = Path(path)
    prev_hash = GENESIS_HASH

    with path.open("r", newline="") as f:
        header = f.readline().rstrip("\n")
        if not header.endswith(",chain_hash"):
            return False, f"header missing trailing chain_hash column: {header!r}"

        n_rows = 0
        for line_no, raw_line in enumerate(f, start=2):
            line = raw_line.rstrip("\n")
            if not line:
                continue
            row_text, sep, claimed_hash = line.rpartition(",")
            if not sep:
                return False, f"line {line_no}: malformed row (no chain_hash column found)"

            computed = hashlib.sha256(prev_hash + row_text.encode("utf-8")).hexdigest()
            if computed != claimed_hash:
                return False, (
                    f"line {line_no}: chain broken — expected chain_hash {computed}, "
                    f"found {claimed_hash}"
                )
            prev_hash = bytes.fromhex(computed)
            n_rows += 1

    if n_rows == 0:
        return True, "chain verified (0 data rows)"
    return True, f"chain verified ({n_rows} rows)"
