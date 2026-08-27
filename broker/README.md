# aura-broker

**Before you run `cargo build`:** Cyton ingestion in this crate depends
on BrainFlow's Rust bindings, which are **not** a plain crates.io
dependency. There is no crate literally named `brainflow` on crates.io —
confirmed directly against the crates.io API (`GET
crates.io/api/v1/crates/brainflow` → 404). If someone hands you a
`Cargo.toml` with a line like `brainflow = "5.12.0"`, that's wrong and
won't resolve — don't add it as-is. If you skip local setup, `cargo
build` will look fine today (the BrainFlow dependency line is still
commented out in `Cargo.toml` until this is done) but will fail the
moment someone tries to point `src/cyton.rs`'s stub at a real
dependency. Do this first:

1. Clone BrainFlow (github.com/brainflow-dev/brainflow) and build its
   C/C++ core per its build docs.
2. Build the Rust binding against that core:
   ```
   cd brainflow/rust_package/brainflow
   cargo build --features generate_binding
   ```
   Full instructions: https://brainflow.readthedocs.io/en/stable/BuildBrainFlow.html#rust
3. Path-dependency it into this crate's `Cargo.toml` (see the commented
   line already there) once step 2 succeeds locally.

The Aura Trigger (Pico) half of this crate — `src/trigger.rs` — has no
such dependency; it's plain `serialport` (blocking, see below for why
not `tokio-serial`) + `serde_json` and builds with a stock `cargo build`
today.

**If you're on Windows:** `src/trigger.rs` uses blocking serial I/O on a
dedicated thread, not `tokio-serial`'s async API — deliberately. Async
serial I/O via `tokio-serial` does not work on Windows with modern Tokio:
the port opens without any error, but reads never complete (confirmed on
real hardware, not assumed — see that file's module doc for the specific
GitHub issues). If you're tempted to "simplify" this back to
`tokio-serial`'s async API, don't, on Windows at least — it'll silently
stop receiving anything and look like a hardware/wiring problem instead
of a library limitation.

## Status

- `cargo build` / `cargo check` / `cargo test` pass clean — **zero
  warnings**, not just fewer; `main.rs` genuinely wires up everything
  that has a real implementation rather than leaving it uncalled.
- `main.rs` — runnable today. `cargo run` starts the dashboard WebSocket
  server (`AURA_DASHBOARD_ADDR`, default `127.0.0.1:9001`) unconditionally,
  and Aura Trigger serial ingestion if `AURA_PICO_SERIAL_PORT` is set
  (e.g. `COM5` or `/dev/ttyACM0`) — logs plainly when it isn't, rather
  than silently doing nothing.
- **Verified fully working end-to-end against real hardware** (2026-08-27):
  a real Pico with a real wired button, running `aura-broker` with
  `AURA_PICO_SERIAL_PORT` pointed at it, feeding a real browser dashboard
  over the real WebSocket connection — actual button presses showed up
  live in the dashboard's trigger log. Not a synthetic demo, not a unit
  test: the whole chain, working together, at once, for the first time.
- `src/trigger.rs` — real, working logic, wired into `main.rs`: opens the
  Pico's serial port on its own blocking thread (see Windows note above),
  parses JSON lines from **both** firmware protocols
  (`hardware/pico_clicker/main.py` and `provenance_main.py` — an earlier
  version only handled the former and silently dropped every line from
  the latter), filters to `AURA_TRIGGER` events, and publishes
  `AuraEvent::Trigger` with the broker's own receipt time. `rtc_time` is
  deliberately never deserialized (see that file's module doc).
- `src/dashboard.rs` — real, working logic, wired into `main.rs`: accepts
  WebSocket connections, streams EEG samples as binary frames and trigger
  events as JSON text (wire format documented in that file). Propagates
  `seq`/`chain_hash`/`chain_ticks_us` for provenance_main.py's protocol —
  `dashboard/index.html` verifies the hash chain client-side with real
  SHA-256 (Web Crypto), browser-tested against both a valid chain and a
  deliberately corrupted one.
- `src/storage.rs` — real, working logic, wired into `main.rs`: writes
  `samples.csv` and `triggers.csv` per session under `AURA_DATA_DIR`
  (default `../data/raw`, relative to this crate — override if running
  from elsewhere), each with its own hash chain (same principle as
  `hardware/pico_clicker/provenance_main.py`). **Verified against real
  hardware**: real button presses produced real chained rows in
  `triggers.csv`, and the chain was independently re-verified in Python
  (recomputed every row's hash from scratch, all matched) rather than
  just trusted to look right. `samples.csv` is ready but empty — no
  Cyton data exists yet to write there.
- `src/cyton.rs` — typed stub, blocked on the BrainFlow local build
  above; the only module not wired into `main.rs` yet.
- `src/replay.rs` — real, working logic, wired into `main.rs`, **verified
  against real downloaded CHB-MIT data end-to-end (2026-08-27)**: a real
  hour-long recording (`chb01_16.edf`, containing a real seizure) exported
  via `pipeline/tools/export_replay_csv.py`, streamed through
  `AuraEvent::Sample`, landed correctly in `storage.rs`'s `samples.csv`,
  and rendered live in a real browser dashboard with the "not live"
  banner visible throughout. This exists because there is no Cyton
  hardware yet and cyton.rs is blocked on the BrainFlow build above — it
  lets `storage.rs` and `dashboard/` be exercised against real human EEG
  in the meantime, instead of staying untested until hardware and
  BrainFlow both land. Set `AURA_REPLAY_CSV` to a CSV from
  `export_replay_csv.py` to enable it; optional
  `AURA_REPLAY_SAMPLE_RATE_HZ` (default `256`, CHB-MIT's native rate),
  `AURA_REPLAY_SPEED` (default `1.0` — realtime; verified with no sample
  drops at 1x, and confirmed the broadcast channel's documented lagged-
  drop behavior kicks in at extreme speeds like 200x, which is expected,
  not a bug), and `AURA_REPLAY_LABEL` (defaults to the CSV path). CHB-MIT
  has no accelerometer channels, so replayed samples always carry
  `accel = [0,0,0]` — a real, honestly-surfaced gap, not fabricated
  motion data. See `src/replay.rs`'s module doc for why this is a
  separate code path from `cyton.rs` rather than a fake board id, and why
  the "not live" banner re-broadcasts every ~2s instead of firing once.
  Optionally, `AURA_REPLAY_ANNOTATIONS_CSV` points at a sidecar file
  (also written by `export_replay_csv.py`, sourced from the dataset's own
  clinician-verified summary via `aura_pipeline.datasets.parse_chbmit_summary`
  — never hand-typed) so `replay.rs` broadcasts a real
  `AuraEvent::Annotation` the moment playback crosses into/out of a real
  seizure interval. **Verified end-to-end (2026-08-27)**: real "SEIZURE
  START"/"SEIZURE END" events landed in the dashboard's Event Log at the
  correct timestamps, with a distinctly-colored marker on the trace at
  the right position — this is dataset ground truth being replayed
  alongside the signal that produced it, never presented as something
  the system detected. `storage.rs` now also writes a chained
  `annotations.csv` per session for the same reason `triggers.csv` is
  chained.

Not done, and deliberately not rushed: encryption at rest (design doc
section 5 — a real hard gate, but not relevant until real patient
sessions happen, which needs the Cyton first). EDF export from a
session's `samples.csv` is now real — `pipeline/tools/session_to_edf.py`
— see `pipeline/README.md` for what it does and doesn't cover (notably:
not the BIDS/anonymization pipeline design doc section 5 requires before
any dataset leaves the machine, which is a separate, larger deliverable).

See `docs/DESIGN_DOCUMENT.md` sections 3.1, 7 (risk #2), and 9 for the
full design rationale and what a Rust engineer should know before
starting here.
