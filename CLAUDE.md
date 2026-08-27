# Project Aura: Architecture & Conventions

Full design rationale, research citations, risks, and team-role guidance
live in `docs/DESIGN_DOCUMENT.md` — read that before making architectural
changes. This file is the fast-reference guardrail list for day-to-day
work in the repo.

## Tech stack boundaries

- **Telemetry broker (Rust, `broker/`):** Use the BrainFlow Rust bindings
  to handle Cyton acquisition (Board ID for Cyton, see BrainFlow docs) —
  do not hand-roll a raw Cyton serial byte parser. **Caveat:** BrainFlow's
  Rust binding is not a plain `cargo add` from crates.io — it requires
  building the BrainFlow C/C++ core locally first, then building the Rust
  binding against it (`cd rust_package/brainflow && cargo build --features
  generate_binding`, per https://brainflow.readthedocs.io/en/stable/BuildBrainFlow.html#rust).
  Vendor that build step into `broker/README.md` once it's done — don't
  assume a fresh `cargo build` on this repo alone will pull it in.
  Use `tokio` for async routing of the stream to local CSV/EDF storage and
  the dashboard websocket. The Aura Trigger (Pico) still talks plain
  serial to the broker directly — BrainFlow doesn't know about it — so
  `tokio-serial` stays for that half.
- **Hardware trigger (`hardware/pico_clicker/`):** MicroPython only, for
  the Raspberry Pi Pico. Standard `machine`, `time`, `sys`, `json`
  libraries — no external dependencies. Do not attempt to execute
  MicroPython on the host machine; output `.py` files for manual flashing.
- **Data pipeline & ML (Python, `pipeline/`):** Python 3.11+. Use `mne`
  (MNE-Python) for EEG preprocessing, filtering, and ICA artifact
  regression. Use `scikit-learn` for threshold classifiers — this is the
  Phase 2 baseline and stays the thing every other detector is compared
  against. Do not hand-roll filtering math MNE already provides.
  **One explicit, gated exception:** a PyTorch-based Kolmogorov-Arnold
  Network (KAN) prototype is in scope as Phase 4 exploratory work only
  (design doc section 4.4) — real published research (KAN-EEG, Section
  10), not core architecture. Don't let "we're trying a KAN" become an
  excuse to add other heavy DL frameworks elsewhere in `pipeline/`; this
  is a scoped, single exception, not a green light to switch the stack.
- **Dashboard (`dashboard/`):** Vanilla HTML5 Canvas or WebGL. No React /
  Vue / Angular. Keep it lightweight and locally served, no cloud
  dependency.

## Development workflow & verification

- **Rust:** Run `cargo check` and `cargo clippy` after any broker change.
- **Python:** Run `pytest` for all signal-processing pipeline changes.
  Generate synthetic 8-channel noise arrays to test MNE filters — do not
  require real hardware to validate filter logic.
- **Hardware:** A spare Pico exists and `hardware/pico_clicker/main.py`
  has been flashed and tested on it (see that folder's README) — no
  Cyton exists yet. Firmware/broker code touching the Cyton should still
  be written and unit-tested against synthetic/mocked data; flag
  anything that can only be verified on real hardware rather than
  silently assuming it works, same as before.

## Data constraints

- Cyton sampling rate is strictly 250Hz — don't hardcode a different rate
  anywhere in the pipeline.
- All EEG event timestamps must be reconciled to a single clock (UTC) so
  the Pico trigger and the Cyton stream line up. The Pico has no
  battery-backed RTC, so `machine.RTC()` resets on power loss — the
  broker, not the Pico, should be treated as the source of truth for wall
  time unless/until an RTC sync-on-boot handshake is actually built and
  tested.
- Raw data MUST be written to local storage (CSV/EDF) before any ML
  transform or filter runs. Never mutate the raw data file in place.
- No patient/participant data gets processed by any detector until that
  detector has been validated against the public baseline datasets
  (CHB-MIT, TUH — see design doc section 4.1). This is a hard gate.
- This is a non-clinical research platform (design doc section 5). Never
  add code paths that treat a detection as a clinical alert, medication
  trigger, or emergency dispatch.
