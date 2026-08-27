# Project Aura

An open-source, non-clinical research platform for capturing continuous,
ambulatory EEG data in a home environment, to help identify pre-ictal
(pre-seizure) signatures.

**Status:** design phase — none of the £1,000 grant-budget hardware
purchased yet (the Cyton board specifically doesn't exist). The Aura
Trigger firmware has been flashed and tested on a spare Pico, though
(`hardware/pico_clicker/README.md`). This repo is the software scaffold
plus the full engineering/research spec, ready to hand to a team or use
as the basis for a grant application.

**Start here:** [`docs/DESIGN_DOCUMENT.md`](docs/DESIGN_DOCUMENT.md) — the
full spec: objectives, hardware architecture, data pipeline, safety and
ethics boundaries, budget, roadmap, risks, and the research citations
backing every dataset/standard/algorithm named below.

Agents and contributors should also read [`CLAUDE.md`](CLAUDE.md) for the
tech-stack boundaries and verification workflow before making changes.

## The architecture

Aura separates data acquisition from event logging so that neither
depends on the patient having a screen in front of them during an event:

1. **Acquisition** — an OpenBCI Cyton (8-channel) streaming EEG at 250Hz.
2. **Telemetry** — a local Rust `tokio` broker ingesting the Cyton stream
   (via BrainFlow's Rust bindings) to prevent packet loss, fanning it out
   via a broadcast channel to local storage and a live dashboard so
   neither consumer's slowness affects ingestion.
3. **The Aura Trigger** — a Raspberry Pi Pico physical hardware button.
   Bypasses the need for a mobile UI during a neurological event by
   logging a timestamped event straight to the broker over USB serial.
4. **Pipeline** — an MNE-Python pipeline using the Cyton's onboard 3-axis
   accelerometer for motion-artifact regression, followed by Hjorth
   parameter and line-length feature extraction, validated against public
   datasets (CHB-MIT, TUH) before ever touching patient data.

## Repository structure

```
project-aura/
├── docs/DESIGN_DOCUMENT.md   ← full spec — read this first
├── broker/                   ← Rust, async telemetry broker (runnable — see broker/README.md)
├── pipeline/                 ← Python, MNE-based preprocessing + features + CHB-MIT validation
├── dashboard/                ← Vanilla HTML5 local visualization (see dashboard/README.md)
├── hardware/
│   ├── pico_clicker/         ← MicroPython firmware for the Aura Trigger
│   └── enclosure/            ← TPU enclosure CAD (empty until hw arrives)
└── data/                     ← gitignored; raw/ and derivatives/ (BIDS)
```

## Hardware safety constraints

- **Electrode degradation** — designed around heavy-duty conductive paste
  (e.g. Ten20) for a 4-to-6 hour high-fidelity nocturnal window; this has
  not yet been measured on real hardware.
- **Enclosure** — the Cyton must be housed in an impact-resistant TPU
  3D-printed case to prevent lacerations during convulsive events.
- **Wiring** — all electrode leads must be routed beneath a tight
  neoprene skullcap to eliminate strangulation risk.

## Non-clinical status

Aura is a research and discovery platform. It is **not** an
FDA/MHRA-approved medical device and must never be used for real-time
clinical decisions, automated medication dispensing, or emergency
dispatch. See `docs/DESIGN_DOCUMENT.md` section 5 for the full ethics and
limitations statement.
