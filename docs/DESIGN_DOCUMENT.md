# Project Aura — Master Engineering & Research Specification

**Status:** Pre-hardware / design phase
**Document purpose:** Handoff specification for a technical team and supporting material for grant/funding applications.
**Maintainer:** 13thrule
**Last updated:** 2026-08-27

> Read this document top to bottom before touching code. Section 9 ("Handoff & Team Roles") tells you where to start if you're joining fresh. Section 10 ("Research References") is the citation list backing every dataset, standard, and algorithm named below — check it before you assume a claim is unsourced.

---

## 1. Executive Summary & Research Objectives

Project Aura is an open-source, non-clinical research platform designed to capture continuous, ambulatory electroencephalogram (EEG) data in a home environment. Clinical EEGs are episodic — typically a 20-60 minute lab session — and routinely fail to capture the pre-ictal (pre-seizure) state or the environmental/behavioral triggers that precede it, simply because the recording window is too short and too artificial. Aura bridges this gap by providing an affordable, robust hardware/software stack for long-term monitoring, annotated event logging, and localized machine learning analysis, run by the patient in their own home.

**Core Objectives:**

1. **Continuous Acquisition** — Capture 8-channel EEG at 250 Hz during prolonged sleep and wake windows, at a duty cycle no clinical ambulatory rig can match at this price point.
2. **Accurate Annotation** — Provide a foolproof hardware interrupt for users to log auras and seizures without relying on a phone screen or app during a neurological event.
3. **Pre-Ictal Discovery** — Build an open pipeline to identify pre-seizure signatures using spectral analysis and thresholded detectors, validated first against gold-standard public datasets before ever touching patient data.
4. **Open Data Contribution** — Generate anonymized datasets formatted to BIDS/EEG-BIDS standards to share with the open-source neurology community, closing the loop back to the research that made this project possible.

**Why this is fundable:** the gap Aura targets — long-duration, low-cost, home ambulatory EEG with reliable event annotation — is a recognized bottleneck in epilepsy research (short clinical monitoring windows under-sample seizures and miss most pre-ictal periods). Aura's contribution is not a new algorithm; it is an accessible acquisition and annotation platform that lets pre-ictal signature research scale beyond hospital monitoring units. That framing (infrastructure + open data, not a clinical claim) is what Section 5 ("Safety, Ethics, and Limitations") exists to protect.

---

## 2. Hardware Architecture & Fabrication

The hardware stack balances research-grade acquisition against physical safety and comfort during a neurological event. **None of the £1,000 grant-budget hardware has been purchased yet** (Section 6 has the itemized budget and procurement order) — the Cyton board specifically does not exist. One exception: a spare Raspberry Pi Pico (not one bought against this budget) was used to flash and test the Aura Trigger firmware on real hardware — see Section 2.2.

### 2.1 Core Acquisition: OpenBCI Cyton

- **Board:** OpenBCI Cyton, 8-channel, 24-bit ADC (TI ADS1299), sampling at 250 Hz.
- **Spatial coverage:** Electrodes mapped to the international 10-20 system — Fp1/Fp2, F7/F8, T3/T4, O1/O2 — targeting frontal and temporal lobes, which are the most common focal-seizure origin sites.
- **Electrode constraints:** Reusable gold-plated cup electrodes with heavy-duty conductive paste (Ten20 or equivalent). Wet electrodes degrade over time; the protocol is built around a 4-to-6-hour nocturnal window before impedance drift becomes a problem. This is a real operational constraint, not a nice-to-have — any pipeline change that assumes longer stable impedance needs to be validated against real drift data first.
- **Auxiliary sensors:** The Cyton's built-in 3-axis accelerometer is actively polled to capture convulsive movement, and feeds the artifact-regression step in the ML pipeline (Section 4.2).

### 2.2 The "Aura Trigger" (hardware interrupt)

Relying on a smartphone during aura onset is a known usability failure — motor control and vision are frequently compromised in the seconds before a seizure.

- **Microcontroller:** Raspberry Pi Pico.
- **Function:** An off-grid physical clicker — one large, tactile, arcade-style button. No screen, no app, no unlock step.
- **Firmware (MicroPython):** Hardware-debounced input (200ms), USB serial (CDC) connection to the local host. On press, it emits a JSON event line (`{"event": "AURA_TRIGGER", "ticks_ms": ..., "rtc_time": ..., "device": "PICO_CLICKER_V1"}`) to the local data broker over serial, annotating the exact moment of the aura without requiring the user to look at anything.
- **Timestamp caveat:** the Pico has no battery-backed RTC — `rtc_time` resets on every power loss and is untrustworthy until a host-sync-on-boot handshake is built and tested. Until then, the broker's own receipt time (paired with the Pico's monotonic `ticks_ms`) is the source of truth for wall-clock alignment with the Cyton stream.
- **Status:** fully verified end-to-end on a real Pico with a real button (MicroPython v1.29.0) — see `hardware/pico_clicker/README.md`. Two real wiring/config mismatches were found and fixed by testing on hardware rather than by re-reading the code: the button turned out to be wired to GND (not 3V3, fixed to `PULL_UP`+`IRQ_FALLING`), and to GP14 (not GP15, confirmed by polling several candidate GPIOs on the real board and watching which one toggled on a press). Real presses now produce correct `AURA_TRIGGER` JSON with working debounce.

### 2.3 Ruggedized enclosure & safety

Wearing a bare PCB during a seizure is a laceration hazard, full stop — this is not optional hardening.

- **Enclosure material:** Impact-resistant TPU (thermoplastic polyurethane), 3D-printed.
- **Visual coding:** Multi-color printing to color-code electrode ports, so correct anatomical placement is foolproof for the patient or a caregiver working from memory or a printed card.
- **Wire management:** All electrode leads routed under a tight neoprene skullcap to eliminate strangulation risk during sleep or convulsions.
- **Scaffold status:** `hardware/enclosure/` is a placeholder — no CAD exists yet because real hardware dimensions haven't been measured. **Do not design the enclosure from datasheet dimensions alone; measure the actual Cyton board and Pico once purchased.** (This project has a standing rule from prior hardware work: CAD that "validates as a solid" in software is not the same as CAD that fits the real part — verify against physical measurements before committing to a print.)

### 2.4 Ambient environmental sensing (stretch, not in core budget)

Clinical EEG isolates the brain from its physical environment. There is a real, if genuinely mixed, research literature on meteorological correlates of seizure occurrence — worth adding a cheap sensor for, but worth being honest about the evidence quality in any grant narrative.

- **Barometric pressure (BME280, ~£6, I2C):** Multiple epilepsy-monitoring-unit and case-crossover studies have looked at atmospheric pressure and seizure timing, with genuinely mixed results — one study found close to a 14% increase in seizure risk per 10.7 hPa pressure drop (36% in a lower-severity subgroup), while other case-crossover analyses (including one in children) found no significant association once other weather variables were controlled for, with at least one study pointing to temperature as the more robust factor. See Section 10. **Frame any finding from this project's own single-subject data as exploratory correlation, not a validated trigger** — that's consistent with the existing "no overclaiming" stance in Section 7.
- **Magnetometer — reframed, not an "EMF trigger sensor":** an earlier draft of this idea proposed a magnetometer specifically to detect "ambient EMF/RF fluctuations" as a possible seizure trigger. There is no credible neurological literature supporting ambient (non-therapeutic) environmental EMF as a seizure trigger — the field strengths involved (WiFi, mains wiring, phones) are far below anything shown to interact with neural tissue, and the closest related literature (electromagnetic hypersensitivity) has consistently failed to show a real effect under blinded conditions. Including that specific framing in a grant application is a credibility risk with any scientifically literate reviewer — **don't use it.** A magnetometer is still worth adding for a legitimate reason: paired with the existing 3-axis accelerometer, it gives a fuller 6-DOF motion reference for the ICA motion-regression step, directly addressing the "only a 3-axis accelerometer" weakness already flagged in risk #3 (Section 7). That's the framing to use if this sensor is added.
- **Budget note:** neither sensor is in the core £1,000 ask (Section 6) — they're a natural Phase-2/3 add-on if the team decides to pursue them, itemized separately so they don't muddy the primary funding request.

### 2.5 Data integrity / provenance (stretch, not hardware-attested yet)

The "Open Data Contribution" objective (Section 1) implies released datasets should be tamper-evident — a reader should be able to tell if a session log was edited after capture. `hardware/pico_clicker/provenance_main.py` implements this for the trigger-event stream as a **hash chain**: each event's hash depends on the previous event's hash, so any post-hoc edit, deletion, or reordering breaks every hash after it — detectable, no secret required. `broker/src/trigger.rs` propagates `seq`/`chain_hash`/`chain_ticks_us` through to the dashboard, and `dashboard/index.html`'s `verifyChainedTrigger()` recomputes the SHA-256 client-side with the real Web Crypto API and reports a genuine verified/broken result — browser-tested against both a legitimate chain and a deliberately corrupted one (dashboard/README.md has the detail). Scope limit that still applies: the dashboard never sees the Pico's true genesis hash (only printed in the firmware's startup line, not currently forwarded by the broker), so it verifies "internally consistent since this session started watching," not "provably unmodified since device boot" — don't blur that distinction in a grant narrative. The same hash-chain principle still belongs in `broker/storage.rs` for the actual EEG data (see Section 3.1) since that's the data volume that actually matters for "Open Data Contribution," not just the much smaller trigger stream — not implemented yet.

**What this does not give you:** cryptographic proof that the data came from a real physical device and human subject. That requires a secret an attacker can't extract even with physical access to the board — a secure element (e.g. ATECC608A, ~£2-3, I2C, hardware-protected key storage), not the Pico's plain flash, which anyone with physical access can dump. True hardware attestation is real future work, not achievable in this budget or this phase — don't claim it in a grant narrative until the secure element is actually in the design. See `hardware/pico_clicker/provenance_main.py`'s module docstring for two concrete cryptographic mistakes (a length-extension-vulnerable prefix-secret construction, and a secret hardcoded into open-source firmware) that an earlier draft of this feature made and that this document exists partly to make sure don't get reintroduced.

---

## 3. Telemetry & Data Architecture

The Cyton generates a high, continuous data rate for hours at a stretch. The stock Bluetooth dongle path is prone to dropping packets under sustained streaming, which is fatal to downstream ML feature extraction (a single dropped window corrupts any sliding-window feature computed across it).

### 3.1 Local data broker

- **Architecture:** A local bridge process, not raw Bluetooth streaming to the visualization layer.
- **Implementation:** A low-latency async publish/subscribe broker in Rust (`tokio`), using a broadcast-channel fan-out so the 250 Hz Cyton stream is routed simultaneously to (a) local storage and (b) the live dashboard, without either consumer's slowness dropping frames for the other.
- **Cyton acquisition path:** via BrainFlow's Rust bindings (`BoardShim`), not a hand-rolled serial parser — BrainFlow already solves Cyton packet framing and the retry/error handling around dropped bytes. Its Rust binding is **not** a plain crates.io dependency: it requires building the BrainFlow C/C++ core locally, then building the Rust binding against it (see `broker/Cargo.toml` for the exact commands and the readthedocs link). Budget setup time for this before assuming `cargo build` "just works" on a fresh checkout.
- **Aura Trigger path:** the Pico talks directly to the broker over plain USB serial (JSON lines — see Section 2.2), independent of BrainFlow. Uses blocking I/O on a dedicated thread, not `tokio-serial`'s async API — confirmed on real hardware that async serial reads never complete on Windows with current Tokio (a real, documented library limitation, not a config mistake — see `broker/README.md` and `broker/src/trigger.rs`'s module doc for the specific GitHub issues). **Verified fully working end-to-end** (2026-08-27): real button presses on a real Pico, through this broker, into a real browser dashboard over a live WebSocket — not a synthetic demo.
- **Redundancy:** The Cyton's onboard SD card logging stays on at all times as the primary, unbroken data repository — the broker's job is to give you a *live* view and a structured copy, not to be the only copy.
- **Status:** `main.rs` is runnable today (`cargo run`, zero warnings) — it wires up the two modules with real implementations: `trigger.rs` (opens the Pico's serial port, parses both firmware protocols, publishes trigger events — set `AURA_PICO_SERIAL_PORT`) and `dashboard.rs` (accepts WebSocket connections, streams events; binds unconditionally on `AURA_DASHBOARD_ADDR`, default `127.0.0.1:9001`). Browser-tested: a real dashboard against a real running broker completes the WebSocket handshake correctly with no data source connected. `cyton.rs` (blocked on the BrainFlow local build above) and `storage.rs` (not started) are typed stubs, not wired into `main.rs` yet. See `broker/README.md` and Section 9.
- **Storage — real and wired up** (2026-08-27): `storage.rs` writes `samples.csv` and `triggers.csv` per session, each with its own hash chain (same principle as `hardware/pico_clicker/provenance_main.py` — Section 2.5), so a released session is tamper-evident, not just the trigger-event stream. Verified against real hardware: real button presses produced real chained rows, independently re-verified (recomputed every hash from scratch in a separate script, all matched — not just trusted to look right). `samples.csv` is ready but empty — no Cyton data exists yet. Encryption at rest (Section 5) is a real remaining gate, deliberately not rushed since it's not relevant until real patient sessions happen.

### 3.2 Visualization dashboard

- **Stack:** Vanilla HTML5 Canvas, single self-contained file, served locally — no cloud dependency, no build step, no third-party JS (a Three.js-based redesign was proposed and rejected for exactly this reason — see `dashboard/README.md`).
- **Status — working, not a skeleton, verified end-to-end against real hardware and real recorded EEG (2026-08-27):** 8-channel EEG trace (with visual trigger and seizure-annotation markers overlaid, not just a separate text log) with channel labels matching Section 2.1's montage; a client-side 50Hz notch filter (real biquad, toggleable, display-only); a real client-side DFT spectrogram; a 2D scalp topology panel showing real per-channel alpha/beta FFT power balance (direct DFT, same method as `aura_pipeline/features.py`'s `band_power()`) at the correct electrode positions; a health bar with a real per-connection dropped-frame counter, measured stream rate, and session timer; an Event Log with **real client-side SHA-256 verification** of `provenance_main.py`'s hash chain (Web Crypto API, browser-tested against both a valid chain and a deliberately corrupted one — see Section 2.5), real connection-state events, and real dataset ground-truth seizure annotations (never a live detection — see below); a "REPLAY MODE — NOT A LIVE SIGNAL" banner whenever the broker is streaming a recorded file (Section 9) instead of live hardware. Runs entirely offline in a synthetic-demo mode that exercises the same decode/verification code real broker data would use, and has also been browser-tested end-to-end against a real running `broker/` with a real Pico, and separately against real replayed CHB-MIT recordings including a real seizure.
- **Seizure-likelihood score panel** — a real, live `LogisticRegression` (scikit-learn, `pipeline/tools/export_dashboard_model.py`) trained on all of chb01's actual CHB-MIT recordings, scored client-side against features this page computes live from its own real buffered signal. This is NOT the KAN prototype (Section 4.4) — an earlier version of this panel was literally a decorative `Math.random()` walk with the KAN name attached to it, which was replaced (2026-08-27) rather than kept, since the honest label "synthetic demo value" wasn't itself sufficient once a real computation was feasible instead. Real, but honestly caveated in the panel itself: fit on a single subject, and the chb02 generalization check (Section 4.1 / `pipeline/validation/README.md`) found this model class doesn't reliably transfer across subjects. `kan_detector.py`'s actual KAN architecture remains a fully separate, offline Phase 4 research prototype with no live inference path — see Section 4.4.

---

## 4. Signal Processing & Machine Learning Pipeline

Built on existing open-source Python tooling (MNE-Python, scikit-learn, NumPy/SciPy) rather than reinventing EEG signal processing. **No model gets near patient data until it's validated on public data first** — that ordering is a hard requirement, not a suggestion, given how easy it is to overfit a pre-ictal detector to a handful of a single patient's seizures.

### 4.1 Baseline datasets for pre-training

- **CHB-MIT Scalp EEG Database** — continuous pediatric recordings with intractable seizures: 664 EDF files, 198 annotated clinical seizures, 23 cases from 22 subjects (one subject has two cases, recorded 1.5 years apart), total 42.6GB. Hosted on PhysioNet. See Section 10 for the citation. `pipeline/validation/validate_chbmit.py` (Section 4.4 / 4.1) validates against one case (chb01, 7 seizures) — see that script for why the full dataset isn't needed for a first baseline result.
- **TUH EEG Seizure Corpus (Temple University Hospital)** — the largest publicly available EEG corpus, widely used for training deep learning seizure-detection models. See Section 10.

Both datasets ship with clinician-annotated seizure onset/offset times, which is what makes them usable as ground truth for validating Aura's detectors before any patient session runs.

### 4.2 Preprocessing & artifact regression

Ambulatory EEG — recorded while the person is awake, moving, sleeping — is flooded with EMG (muscle) and EOG (eye) noise in a way a seated clinical recording is not.

- **Filtering:** 1-50 Hz bandpass, plus a 50/60 Hz notch filter for AC mains noise (50 Hz or 60 Hz depending on region — this needs to be a config flag, not hardcoded, since the team may test in either).
- **Motion regression:** Jaw clenching and walking mask cortical signal. The pipeline uses the Cyton's accelerometer channel as a reference for Independent Component Analysis (ICA), dynamically subtracting motion artifact components from the EEG.

### 4.3 Feature extraction

- **Hjorth parameters** — lightweight time-domain descriptors, cheap enough to run continuously on modest hardware:

  Mobility:
  $$Mobility = \sqrt{\frac{var(x')}{var(x)}}$$

  Complexity:
  $$Complexity = \frac{Mobility(x')}{Mobility(x)}$$

- **Line length** — a fast time-domain metric, effective at flagging the rapid amplitude/frequency shifts characteristic of seizure onset (Esteller et al. 2001, Section 10).
- **Spectral bands** — FFT-based tracking of delta/theta/alpha/beta/gamma power shifts leading up to an aura.

### 4.4 Kolmogorov-Arnold Networks — Phase 4 exploratory, not core Phase 2

**This is real, published, active research** — not speculative. Multiple 2024-2025 papers apply KANs specifically to EEG seizure detection: "KAN-EEG: Towards Replacing Backbone-MLP for an Effective Seizure Detection System" (tested across three datasets from different countries/hardware, published in Royal Society Open Science) and "SeizureNet-KAN" (KAN layers inside a graph convolutional network for seizure prediction). See Section 10. KANs replace an MLP's fixed activation functions with learnable per-edge spline functions, which the published results report as more parameter-efficient and more interpretable than a comparable MLP/CNN — a genuinely good fit for a patient-facing "explainable pre-ictal rule" goal, not just a fashionable architecture choice.

That said, this is Phase 4 exploratory work, deliberately gated behind the Phase 2 baseline (Section 4.1-4.3):

- **Do not replace the scikit-learn threshold classifier** that CLAUDE.md specifies as the Phase 2 baseline. A KAN prototype is an addition to compare against that baseline, not a substitute for it — the baseline is what a grant reviewer or a clinician collaborator can sanity-check without needing to trust a novel architecture.
- **Implement the spline basis correctly or don't ship it.** An earlier draft of this idea computed `spline_weight.mean(dim=-1)` before ever touching the input — that collapses the whole point of a KAN (a per-edge function whose *shape* depends on where the input falls on the grid) into an ordinary elementwise-gated linear layer wearing a KAN's variable names. It would train and run without erroring, and would deliver none of the accuracy or interpretability properties the KAN literature actually reports. Use a real, validated reference implementation (e.g. the `efficient-kan` approach, or code released alongside the KAN-EEG papers if available) rather than hand-rolling the spline math from scratch — this is exactly the kind of thing worth getting from a tested source rather than reinventing under time pressure.
- **Validate against CHB-MIT/TUH before ever touching patient data**, same as every other detector in this document (Section 4.1) — a novel architecture on top of already-thin single-subject data (risk #4, Section 7) is exactly where overclaiming risk compounds.

`pipeline/aura_pipeline/` — status, not a stub list: `filters.py` and `features.py` are implemented and tested (bandpass/notch, Hjorth mobility/complexity, line length, FFT band power). `ica_motion.py` has both the experimental ICA path and a tested linear-regression fallback (risk #3). `datasets.py` has a real, tested CHB-MIT summary parser (`parse_chbmit_summary`) — TUH/TUSZ is not implemented (needs a data use agreement). `kan_detector.py` is the correctness-tested Phase 4 KAN prototype this section describes. `pipeline/validation/validate_chbmit.py` and `validate_chbmit_multifeature.py` run the actual Phase 2 baseline-detector validation this section and Section 4.1 require, against real downloaded CHB-MIT data — now two subjects (chb01, 7 seizures; chb02, 3 seizures), enough to reveal a real cross-subject generalization gap (see Section 7 risk #4 and `pipeline/validation/README.md`), not just a within-subject result. See `pipeline/README.md` for current status and how to reproduce.

**Three real results exist**, all run ahead of the nominal Phase 2 schedule since none needed hardware. Baseline (`results_chb01.json`): the simplest possible detector — mean line length, one threshold, no cleaned input — scores 28.6% sensitivity (2/7 seizures) at 4.5 FP/hour on chb01. Improved, same subject (`results_chb01_multifeature.json`): combining line length with Hjorth mobility/complexity and band power into a real `sklearn.LogisticRegression`, evaluated with leave-one-seizure-out cross-validation, plus consecutive-window smoothing — a **neighborhood** of moderate settings (0.9-0.99 threshold, 2-3 window smoothing) consistently holds 7/7 sensitivity at roughly 1-4 FP/hour on chb01, an honest order-of-magnitude improvement.

**The generalization check (`results_chb02_multifeature.json`) is the important one, and it's a real miss, not a success story.** The identical methodology run on a second subject (chb02, 3 seizures) does not reproduce chb01's neighborhood: the same settings that held 7/7 at 1-4 FP/hr on chb01 drop to 2/3 sensitivity at 18-25 FP/hr on chb02 — both meaningfully worse, at once. This is not a bug or a setback to hide; it's the methodology correctly catching that a population-shared threshold doesn't transfer across people, which is actually **consistent with** this project's own stated premise (Section 1: a *personal* pre-ictal signature per patient, not a one-size-fits-all detector) rather than a contradiction of it.

**A per-patient calibration extension now exists** (`pipeline/aura_pipeline/calibration.py`) — exactly the mechanism the personal-signature premise implies: a new patient has no labeled seizures yet, only baseline recordings (Phase 3's existing protocol), so it calibrates their personal alarm threshold from baseline data alone. Tested honestly with leave-one-subject-out (`results_chbmit_calibrated.json`): calibration hits its false-positive target (chb01: 0/hr against a 2/hr target) but sensitivity drops to 33-43% — not yet good enough to be useful. The important caveat: with only 2 subjects, "population classifier" here means "trained on exactly one other person," not a real population model, so this doesn't mean calibration fails — it means 2 subjects isn't enough training diversity to fairly test it yet. More subjects is the honest next step before drawing a real conclusion either way.

The honest claim for a grant narrative right now is "strong within-subject performance; a calibration mechanism for new patients exists and behaves correctly, but hasn't yet been tested with enough subjects to know if it closes the generalization gap" — not "multi-feature combination works," not "calibration solves it," and definitely not the chb01 numbers presented alone. See `pipeline/validation/README.md` for the full comparison tables and read.

---

## 5. Safety, Ethics, and Limitations

Read this section before writing a line of the detection pipeline — it sets the boundaries everything else operates inside.

- **Non-clinical status.** Aura is strictly a research and discovery platform. It is **not** an FDA/MHRA-approved medical device and must never be used for real-time clinical decisions, automated medication dispensing, or emergency dispatch. Any UI copy, alert, or dashboard element that could read as a medical alarm needs an explicit non-clinical disclaimer.
- **Data privacy.** All stored EEG data and timestamps must be encrypted at rest. Before any dataset leaves the local machine — including sharing with the open-source community — it must be stripped of personally identifiable information and reformatted to BIDS/EEG-BIDS and SzCORE conventions (Section 10). This is a hard gate, not a cleanup pass done later.
- **Informed consent & IRB.** If this project ever moves beyond a single self-monitoring user (i.e., recruits other participants), that requires an IRB/ethics review before data collection, not after. This document does not currently plan for multi-subject recruitment; if a grant reviewer asks about it, the honest answer is "future work, contingent on ethics approval."
- **Spatial limitations.** An 8-channel setup cannot match the spatial resolution of a 64-channel clinical cap. Deep-brain or highly localized seizure foci may be missed entirely — this is a stated limitation, not a gap to paper over in a grant narrative.
- **False negatives are the dangerous failure mode.** A missed seizure has real consequences; a false alarm is merely annoying. Any threshold tuning in Section 4 should be biased toward sensitivity over specificity, with the tradeoff made explicit and documented per threshold change.

---

## 6. Budget & Execution Roadmap

**Funding request: £1,000**

| Item | Cost |
|---|---|
| OpenBCI Cyton 8-channel board | £933 |
| Reusable cup electrodes & Ten20 paste | £40 |
| Raspberry Pi Pico & tactile arcade button (Aura Trigger) | £10 |
| TPU filament (multi-color) | £17 |
| **Total** | **£1,000** |

### Phase 1 — Hardware Integration (Weeks 1-4)

- Print the TPU Cyton enclosure and wire the Pico Aura Trigger.
- Establish the Rust zero-copy serial bridge (`broker/`).
- Verify 250 Hz data ingestion with zero packet loss over a multi-hour soak test.

### Phase 2 — Pipeline Validation (Weeks 5-8)

- Build the MNE-Python artifact-regression pipeline (`pipeline/`).
- **ICA motion regression is explicitly experimental in this phase** (see risk #3 below). The ML engineer has standing backlog permission to abandon full ICA and switch to a simpler linear regression/subtraction approach against the accelerometer channels if ICA components start eating true EEG signal variance rather than motion artifact — that decision does not need to be re-litigated with the rest of the team, it's a known fallback, not a scope change.
- Validate spike-detection algorithms against CHB-MIT and TUH to establish baseline sensitivity/specificity **before any patient data is collected.**

### Phase 3 — Live Pilot & Data Collection (Weeks 9-12)

- Baseline daily sessions (10-20 min, resting) to characterize this specific setup's noise floor.
- 10 scheduled night sessions.
- Correlate Pico trigger timestamps with spectral anomalies to begin mapping a personal pre-ictal signature.

### Phase 4 — Exploratory extensions (stretch goal, outside the £1,000 core ask)

Not part of the funded scope above — listed here so the roadmap is honest about what's core vs. aspirational, and so a reviewer sees the team knows the difference.

- **Ambient sensing** (Section 2.4): BME280 barometric pressure (~£6) as an exploratory correlate; a magnetometer (~£5) as a motion-regression aid, not an "EMF trigger" sensor.
- **Data integrity hardening** (Section 2.5): an ATECC608A-class secure element (~£2-3) to upgrade the hash-chain provenance scheme into real hardware-rooted attestation.
- **KAN pre-ictal detector** (Section 4.4): prototype and validate against CHB-MIT/TUH alongside the Phase 2 baseline, using a correct reference spline implementation.

---

## 7. Risks & Open Engineering Challenges

Ranked roughly by how likely each is to actually bite, based on where the design is thinnest.

1. **Electrode impedance drift overnight.** The whole nocturnal-window premise (Section 2.1) depends on Ten20 paste holding a usable impedance for 4-6 hours. This has not been measured with this exact hardware. First soak test should log impedance over a full night before anything else is built on top of it.
2. **Zero packet loss is a hard real-time claim.** The Rust broker's "no dropped frames" requirement (Section 3.1) needs an actual soak test under realistic USB serial jitter, not just a happy-path demo. Budget real engineering time here — this is the piece most likely to eat the schedule.
3. **Motion-artifact ICA is fragile with only one accelerometer reference.** Standard ICA motion regression literature usually assumes richer reference channels than a single 3-axis accelerometer feeding an 8-channel EEG. Treat full ICA as an **experimental** Phase 2 step, not a settled choice — the ML engineer has standing permission (Section 6, Phase 2) to fall back to a simpler linear regression/subtraction approach against the accelerometer channels the moment ICA components start eating true EEG signal variance instead of motion artifact, without needing to re-justify that call to the rest of the team.
4. **Single-subject data is not enough to validate a personal pre-ictal signature — now with real evidence, not just a stated principle.** Phase 3 explicitly frames this as *mapping toward* a signature, not claiming one. Section 4.1's chb01→chb02 generalization check confirms exactly why: a multi-feature detector tuned to a strong, consistent operating point on chb01 (7/7 sensitivity, 1-4 FP/hr) drops to 2/3 sensitivity at 18-25 FP/hr on chb02 using the identical settings. A grant narrative should match that framing exactly — this is evidence *for* the personal-signature premise (population thresholds don't transfer), not evidence against the project, but only if reported honestly as such.
5. **BIDS/SzCORE formatting is nontrivial to get right.** Both standards have real structural requirements (Section 10) — treat the anonymization/formatting step as its own deliverable with its own validation pass (there are open-source BIDS validators), not a quick script at the end.
6. **Security-flavored claims are easy to overclaim by accident.** The provenance work in Section 2.5 is a real, useful tamper-evidence property — but it is not hardware attestation, and it would be a mistake to describe it as such in a grant narrative or to any collaborator. General rule for any Phase 4 security work: don't claim a property the current hardware can't actually back (e.g. don't call a hash chain "cryptographic proof of origin," don't call a plain-flash-stored key "tamper-proof").
7. **Meteorological correlates are genuinely contested science.** The barometric-pressure literature in Section 2.4 has real studies on both sides. Any result from this project's own single-subject data is a correlation observed in n=1, not a validated trigger — report it that way.
8. **A hand-rolled novel ML architecture can look correct while being wrong.** The KAN spline-collapse bug described in Section 4.4 would have shipped silently — it trains, it runs, the shapes all line up, and it just doesn't do what a KAN is supposed to do. Any Phase 4 model work should be checked against a reference implementation or a known-good test case (e.g. "does this layer's output actually change shape as a function of *where* the input falls on the grid, not just its magnitude"), not just "does it run without erroring."
9. **Async Rust serial I/O silently doesn't work on Windows.** Found the hard way while wiring the Aura Trigger up to a real Pico: `tokio-serial`'s async API opens a COM port without any error, then simply never receives a byte — no crash, no timeout, no log line, just permanent silence that looks exactly like a wiring or hardware fault. Root cause is a real, documented gap (modern Tokio removed the Windows-compatible async polling primitive `tokio-serial` depended on, and there's no replacement yet — see `broker/src/trigger.rs`'s module doc for the specific issues), not something fixable by tweaking serial parameters. Fixed by using blocking I/O on a dedicated thread instead, bridged into the async broadcast channel. Worth remembering for any *future* serial-touching Rust code in this project (not just this one file) — don't reach for `tokio-serial`'s async API on Windows without testing on real Windows hardware first, the failure mode is silent.

---

## 8. Software Repository Layout

```
project-aura/
├── CLAUDE.md                   ← tech-stack boundaries & verification rules
├── docs/
│   └── DESIGN_DOCUMENT.md      ← this file
├── broker/                     ← Rust, tokio broker (BrainFlow + serial trigger)
├── pipeline/
│   ├── aura_pipeline/          ← Python, MNE-based preprocessing + features
│   └── validation/             ← Phase 2 baseline validation against real CHB-MIT data
├── dashboard/                  ← HTML5/Canvas live visualization
├── hardware/
│   ├── pico_clicker/           ← MicroPython, Aura Trigger firmware
│   └── enclosure/              ← TPU enclosure CAD (empty until hw arrives)
└── data/                       ← gitignored; raw/ and derivatives/ (BIDS)
```

---

## 9. Handoff & Team Roles

If you're picking this project up fresh, here's where each skill set plugs in:

- **Embedded/firmware engineer** — `hardware/pico_clicker/`. Small, well-scoped, and now verified on real hardware (Section 2.2) — the remaining work is wiring an actual button and confirming press/bounce behavior, not writing new logic. Good first task for someone new to the project.
- **Systems/Rust engineer** — `broker/`. `cargo run` already does something real today, verified end-to-end against a real Pico (trigger ingestion + dashboard websocket + storage, see Section 3.1) — the remaining work is Cyton ingestion itself, blocked on the BrainFlow local build (Risk #2). In the meantime, `broker/src/replay.rs` streams real recorded EEG (via `pipeline/tools/export_replay_csv.py`) through the same event path `cyton.rs` will eventually use, so `storage.rs` and `dashboard/` don't have to sit untested until both hardware and BrainFlow are ready — see `broker/README.md` for the verified result and why it's a separate, clearly-labeled code path rather than a fake board id. Read risk #9 before writing any new serial-facing Rust code — async serial I/O has a real, silent failure mode on Windows. Needs someone comfortable with async Rust, serial I/O, and writing real soak tests, not just unit tests.
- **ML/signal-processing engineer (Python, MNE-Python background ideal)** — `pipeline/`. Should start with Section 4.1's baseline datasets, not patient data, and should read Risk #3 before committing to full ICA.
- **Frontend/dashboard engineer** — `dashboard/`. Lowest-risk piece; a good on-ramp task once the broker emits a stable stream.
- **Mechanical/CAD** — `hardware/enclosure/`. Blocked until hardware is purchased and measured (Section 2.3) — don't start from datasheet dimensions.
- **Data governance / ethics** — owns Section 5 and the BIDS/SzCORE export pipeline (Risk #5). This role matters even at single-subject scale, because the anonymization pipeline needs to be built and validated before it's needed under time pressure.
- **Phase 4 stretch work** (Sections 2.4, 2.5, 4.4) — not core-scoped, doesn't need a dedicated owner yet. Whoever picks it up should read risks #6-8 first; all three stretch items have a documented way to overclaim what they actually deliver if the caveats in their sections get dropped along the way.

Whoever owns the grant application should pull Sections 1, 5, 6, and 7 directly — that's the significance/objectives, ethics/limitations, budget, and honest-risk framing a reviewer will look for, in that order.

---

## 10. Research References

Datasets, standards, and prior-art the design above depends on. Look these up directly rather than trusting secondhand summaries of them.

**Datasets**

- Shoeb, A. (2009). *Application of Machine Learning to Epileptic Seizure Onset Detection and Treatment.* PhD thesis, MIT. — Source of the CHB-MIT Scalp EEG Database, hosted on PhysioNet.
- Goldberger, A. L., et al. (2000). "PhysioBank, PhysioToolkit, and PhysioNet: Components of a New Research Resource for Complex Physiologic Signals." *Circulation*, 101(23), e215-e220. — PhysioNet, which hosts CHB-MIT.
- Obeid, I., & Picone, J. (2016). "The Temple University Hospital EEG Data Corpus." *Frontiers in Neuroscience*, 10:196. — TUH EEG Corpus and its seizure subset (TUSZ).

**Standards**

- Pernet, C. R., et al. (2019). "EEG-BIDS, an extension to the brain imaging data structure for electroencephalography." *Scientific Data*, 6:103. — the BIDS extension referenced in Sections 1 and 5.
- Dan, J., et al. (2024). "SzCORE: A Seizure Community Open-Source Research Evaluation framework for the validation of EEG-based automated seizure detection algorithms." *Epilepsia*. — the seizure-detection benchmarking standard referenced in Section 5/7. No longer citation-only: `pipeline/aura_pipeline/timescore.py` wraps the group's real scoring implementation ([esl-epfl/timescoring](https://github.com/esl-epfl/timescoring)), and `pipeline/tools/export_chbmit_bids.py` uses their [epilepsy2bids](https://github.com/esl-epfl/epilepsy2bids) library to write the double-banana montage + `events.tsv` format their tooling expects — see `pipeline/validation/README.md`'s SzCORE cross-check section for what that integration found.

**Methods**

- Gramfort, A., et al. (2013). "MEG and EEG data analysis with MNE-Python." *Frontiers in Neuroscience*, 7:267. — the toolkit underpinning `pipeline/`.
- Hjorth, B. (1970). "EEG analysis based on time domain properties." *Electroencephalography and Clinical Neurophysiology*, 29(3), 306-310. — origin of the Hjorth parameters in Section 4.3.
- Esteller, R., et al. (2001). "Line length: an efficient feature for seizure onset detection." *Proceedings of the 23rd Annual International Conference of the IEEE EMBS.* — origin of the line-length feature in Section 4.3.
- "KAN-EEG: towards replacing backbone-MLP for an effective seizure detection system." *Royal Society Open Science* (2024/2025; also on medRxiv and PubMed, PMID 40078924). — real, published, and specifically applies KANs to EEG seizure detection across three datasets; referenced in Section 4.4. Pull the exact author list/date from the publisher page before citing formally, since it wasn't fully captured here.
- "Graph-based EEG analysis for seizure prediction enhanced with Kolmogorov-Arnold Networks and Self-Supervised Learning" ("SeizureNet-KAN"), *ScienceDirect*. — KAN layers inside a GCN for seizure prediction; referenced in Section 4.4. Same caveat: confirm full citation details from the publisher page directly.
- Meteorological/seizure correlation literature (Section 2.4) is genuinely mixed — see e.g. epilepsy-monitoring-unit studies on atmospheric pressure and seizure frequency (ScienceDirect, AES abstracts) alongside case-crossover studies finding no significant association (PubMed 28480567, and a pediatric case-crossover analysis). Don't cite this as settled; check current literature directly and represent the disagreement honestly if it goes in a grant narrative.

**Hardware references**

- OpenBCI Cyton board documentation — openbci.com — 8-channel spec, SD logging, accelerometer, serial protocol.
- Raspberry Pi Pico datasheet — for the Aura Trigger microcontroller.
- BrainFlow — brainflow.org / brainflow.readthedocs.io — the acquisition library used by `broker/` for Cyton ingestion (Section 3.1). Its Rust binding requires a local build against the BrainFlow C/C++ core; see the readthedocs "Build BrainFlow" Rust section for the exact steps before assuming it's a normal crates.io dependency.

---

*This document is the living spec for Project Aura. Update it as design decisions change — don't let the code and this document drift apart.*
