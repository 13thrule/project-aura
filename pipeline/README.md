# aura_pipeline

MNE-Python preprocessing and feature-extraction pipeline. See
`docs/DESIGN_DOCUMENT.md` section 4 for the full spec this implements.

## Setup

```
py -3 -m venv .venv
.venv\Scripts\pip install --cache-dir .pip-cache -e . pytest
.venv\Scripts\pytest
```

(Or `python3 -m venv .venv` / `source .venv/bin/activate` on non-Windows.)

`--cache-dir .pip-cache` keeps pip's downloaded wheels on this drive —
pip's real default cache lives under the user profile (`C:\Users\...\AppData\Local\pip\Cache`
on Windows), which for a large install like the `kan` extra's PyTorch
means real GBs landing on C: instead of D:. `.pip-cache/` is gitignored.

## Status

- `filters.py` — bandpass + mains notch, implemented and covered by
  `tests/test_filters.py` (synthetic 8-channel signal, no hardware
  needed).
- `features.py` — Hjorth mobility/complexity, line length, FFT band
  power, implemented and covered by `tests/test_features.py`.
- `ica_motion.py` — two implementations, both tested:
  - `remove_motion_components` — accelerometer-referenced ICA, marked
    EXPERIMENTAL. Originally used `ica.find_bads_ref()`, which was
    **confirmed broken** by actually running it (always raises
    `ValueError: ICA solution must contain both reference and MEG
    channels` — hardcoded to MEG channel types, not just "untested" as
    an earlier version of this note said). Now uses manual correlation
    between `ica.get_sources()` and the accel channels instead —
    verified to reliably improve signal correlation on synthetic
    contaminated data (`tests/test_ica_motion.py`).
  - `regress_out_motion` — the pre-authorized fallback (design doc risk
    #3 / Phase 2 backlog note): plain linear regression against the
    accel channels. Tested and working.
  Switch to the fallback the moment ICA starts eating true EEG signal
  variance instead of motion artifact — that's a standing decision, not
  one that needs re-approval.
- `datasets.py` — EDF loading via MNE works out of the box. CHB-MIT
  annotation parsing (`parse_chbmit_summary`) is implemented and tested
  against the real downloaded summary file, not a synthetic fixture. TUH
  annotation parsing is not implemented (needs a data use agreement
  first — check current access terms).
- `kan_detector.py` — **Phase 4 exploratory only** (design doc section
  4.4, CLAUDE.md), not the Phase 2 baseline. A from-scratch,
  correctness-tested piecewise-linear KAN implementation — install the
  optional `kan` extra (`pip install -e ".[kan]"`) to pull in `torch`
  before running `tests/test_kan_detector.py`. That test file is worth
  reading even if you never touch this module: it exists specifically to
  catch a real bug an earlier draft had (a "spline" that didn't actually
  depend on its input — see the module docstring).
- `validation/validate_chbmit.py` — the actual Phase 2 baseline-detector
  validation (design doc section 4.1): a simple line-length threshold
  classifier, run against real downloaded CHB-MIT data. Has a real
  result — see `validation/README.md` for the number and how to read it
  honestly (it's a weak first-pass baseline, deliberately).
- `validation/validate_chbmit_multifeature.py` — combines line length
  with Hjorth mobility/complexity and band power into a real
  `sklearn.LogisticRegression`, evaluated with leave-one-seizure-out
  cross-validation, now subject-parametrized (`python
  validate_chbmit_multifeature.py chb01` or `chb02`). Strong on chb01
  (7/7 sensitivity, 1-4 FP/hr at moderate settings) — but running the
  identical methodology on chb02 shows that DOESN'T transfer (drops to
  2/3 sensitivity at 18-25 FP/hr with the same settings). That gap is the
  actually important result — see `validation/README.md`'s
  generalization-check section before assuming the chb01 number means
  anything on its own.
- `calibration.py` — the per-patient calibration extension this
  generalization gap implies: calibrates a personal alarm threshold from
  a new patient's baseline-only data (no seizure labels needed, matching
  what a real new patient actually has). Tested honestly with
  leave-one-subject-out in `validation/validate_chbmit_calibrated.py` —
  hits its false-positive target but sensitivity is still weak (33-43%)
  with only 2 subjects to train from. See `validation/README.md` for why
  that's not yet a verdict on whether calibration works.
- `tools/export_replay_csv.py` — exports one CHB-MIT recording (real
  data, same channel montage and filtering the validation scripts already
  use) to the flat CSV `broker/src/replay.rs` streams through the
  broker's normal Sample event path. This is the concrete way to exercise
  `broker/src/storage.rs` and `dashboard/` with real human EEG before
  Cyton hardware exists — see `broker/README.md`'s replay.rs entry for
  the verified end-to-end result. Also writes a `*_annotations.csv`
  sidecar (start_seconds, end_seconds, label) whenever the source file
  has known seizures, via the same `parse_chbmit_summary` the validation
  scripts already trust — never hand-typed — for
  `AURA_REPLAY_ANNOTATIONS_CSV` to broadcast real "seizure start/end"
  events during replay (see broker/README.md and dashboard/README.md's
  Event Log entries). Optional `--start`/`--end` crop to a time window
  (e.g. centered on a real seizure) instead of replaying an entire hour;
  annotation times are clipped to the crop window. Usage: `python
  tools/export_replay_csv.py chb01 chb01_16.edf` or `... --start 940
  --end 1150`; output goes to `data/derivatives/replay/` (gitignored,
  per `data/README.md`).
- `aura_pipeline/chain_verify.py` — re-implements
  `broker/src/storage.rs`'s hash-chain verification in Python
  (`verify_chained_csv()`), mirroring `ChainedCsv::append_chained` byte
  for byte. Before this existed, chain verification only lived in
  `dashboard/index.html`'s JS, for live trigger events only — there was
  no way to check a session file already on disk. Tested against both a
  correctly-chained synthetic file and deliberately tampered/truncated
  ones (`tests/test_chain_verify.py`), and cross-checked against a real
  file written by the actual Rust broker (not just Python-generated
  fixtures) during development.
- `tools/session_to_edf.py` — converts one `broker/src/storage.rs`
  session's `samples.csv` into a standard EDF file via
  `chain_verify.py` + MNE's EDF export backend, refusing to export a
  session whose chain doesn't verify. Closes the loop `export_replay_csv.py`
  /`replay.rs` opened: real (or replayed) EEG now flows broker ->
  storage.rs, and this is what turns that back into something MNE (or any
  other EEG tool) can load. Round-trip tested — synthetic data survives
  CSV -> EDF -> reload within EDF's 16-bit quantization precision
  (`tests/test_session_to_edf.py`) — and handles two real issues found
  while building it against actual broker output: samples.csv only has
  wall-clock timestamps, not a nominal rate, so the effective rate is
  inferred and rounded to a whole Hz (loud jitter warning if that's a
  poor fit — genuinely happens under replay speeds other than 1x, where
  broadcast-channel backpressure makes timing bursty, not a bug in this
  script); and EDF requires an integer number of samples per whole
  second, so a trailing partial second is trimmed rather than erroring.
  **Not** the BIDS/anonymization export design doc section 5 requires
  before any dataset leaves this machine — that's explicitly flagged
  there as its own deliverable needing its own validation pass, not
  something to fold into this smaller conversion utility.
- `tools/export_chbmit_bids.py` — converts a CHB-MIT recording to the
  double-banana bipolar montage + `events.tsv` that
  [`esl-epfl/epilepsy2bids`](https://github.com/esl-epfl/epilepsy2bids)
  (the reference implementation behind SzCORE, design doc section 10)
  expects, using that library's own `Eeg`/`Annotations` classes to write
  the files. Found and fixed a real montage mismatch along the way —
  epilepsy2bids's own loader rejects CHB-MIT files as-is
  (`Unrecognized electrode: FP1-F7`) because CHB-MIT uses modern 10-20
  naming (`FP1`, `T7`/`T8`/`P7`/`P8`) while epilepsy2bids's fixed
  double-banana channel list uses the older `Fp1`/`T3`/`T4`/`T5`/`T6`
  naming those positions used to go by — a real ACNS nomenclature era
  difference (verified against the ACNS electrode-nomenclature
  guidelines, not assumed), not a bug in either library. The explicit
  mapping table + rationale is in that script's module doc; the exported
  file was confirmed to round-trip through epilepsy2bids's own
  `loadEdfAutoDetectMontage()` (its own auto-detection recognizes the
  montage, not just "the script didn't crash" — `tests/test_export_chbmit_bids.py`),
  and the exported seizure event timing was cross-checked against
  `chb01-summary.txt` directly. **Scope**: writes a re-referenced EDF +
  a real BIDS-style `events.tsv` per recording, not a complete
  `dataset_description.json`/`participants.tsv`/sidecar-JSON/
  `sub-XX/ses-XX/eeg/` BIDS dataset tree — that fuller structure is
  still design doc section 5's separately-scoped deliverable. Usage:
  `python tools/export_chbmit_bids.py chb01 chb01_16.edf`; output goes
  to `data/derivatives/bids_chbmit/`.
- `aura_pipeline/timescore.py` — wraps
  [`esl-epfl/timescoring`](https://github.com/esl-epfl/timescoring), the
  actual scoring library behind SzCORE, so validation results can be
  reported in the field's real standard metric instead of only the
  hand-rolled counting `validate_chbmit_multifeature.py` has used.
  `validation/validate_chbmit_szcore.py` re-scores that script's exact
  chb01 leave-one-seizure-out predictions (same model, same operating
  points) both ways side by side — see `validation/README.md`'s SzCORE
  section for a real, honest finding this surfaced: SzCORE's event-level
  false-positive counting is meaningfully lower than the hand-rolled
  window-rate at the same operating points, because it merges nearby
  false alarms the way a clinician actually would, and the hand-rolled
  version didn't. `tests/test_timescore.py` cross-checks the wrapper
  against timescoring's own documented example, not just against itself.
- `tools/export_dashboard_model.py` — trains a real `LogisticRegression`
  on ALL of chb01's recordings (not a CV fold — a "production" fit for
  live display, a different purpose than `validate_chbmit_multifeature.py`'s
  evaluation), using `compute_window_features` from that same module so
  the exported model can't drift from what's actually been validated.
  Exports weights + the honest generalization caveat (chb02's known gap)
  to `dashboard/model_chb01.json`, which `dashboard/index.html` loads and
  scores live against features it computes client-side from its own real
  buffered signal — replaced what used to be a decorative
  `Math.random()` gauge with a real (if single-subject, honestly
  caveated) computation. See `dashboard/README.md` for the browser-tested
  result. Usage: `python tools/export_dashboard_model.py` (re-run if
  `aura_pipeline/features.py` or chb01's data ever changes).

## What's NOT here yet

- Validation beyond chb01 — both validation scripts are n=1 subject.
  Running the same methodology against more CHB-MIT subjects (and
  eventually TUH) is the natural next step to see if the multi-feature
  result holds up outside one person's data.
- Using `ica_motion.py` in the validation scripts — **not actually
  applicable to CHB-MIT**, on reflection: `remove_motion_components()`
  and `regress_out_motion()` both require real accelerometer reference
  channels to work against, and CHB-MIT (clinical scalp EEG, patients
  resting in an epilepsy monitoring unit) has none — there's no motion
  signal to regress out. An earlier version of this note suggested trying
  it here anyway; that was wrong and is corrected now rather than left as
  a misleading roadmap item. `ica_motion.py` stays relevant for real Aura
  sessions once the Cyton + its onboard accelerometer exist (or for
  `broker/src/replay.rs` sessions, which also always carry
  `accel = [0,0,0]` for the same CHB-MIT-has-no-accelerometer reason —
  see `tools/export_replay_csv.py`). General (non-motion-referenced) ICA
  artifact removal on CHB-MIT's EEG channels alone would be a legitimate,
  different thing to try — not yet done, and would need new code, not
  reuse of `ica_motion.py` as-is.
- BIDS/EEG-BIDS export — needed before any dataset leaves this machine
  (design doc section 5). Not started; explicitly scoped there as its
  own deliverable with its own validation pass, not a quick script —
  don't fold it into `tools/session_to_edf.py`, which is a smaller,
  separate thing (see that entry above).
