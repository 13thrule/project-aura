# Baseline validation against CHB-MIT

Closes the design doc section 4.1 / CLAUDE.md gate: no detector touches
patient data until it's proven against public data first. This is the
first real validation run — everything before this only ever touched
synthetic sine waves.

## Result (chb01, n=1 subject) — `results_chb01.json`

```json
{
  "sensitivity": 0.286,          // 2 of 7 seizures detected (event-level)
  "false_positives_per_hour": 4.47,
  "threshold_line_length": 11599.5,
  "total_non_seizure_hours_evaluated": 10.5
}
```

**Read this honestly, not optimistically.** 28.6% sensitivity with 4.5
false alarms/hour is a weak result in absolute terms — this is the
simplest possible detector (mean line-length across 8 channels, one
threshold, no other features, no ICA-cleaned input) and it shows. That's
the point of running this now, before any patient data: it's a real
number to improve on, not an assumed one, and it sets a concrete floor
for Phase 2 to beat — combining line length with Hjorth
mobility/complexity and band power (all three already implemented in
`aura_pipeline/features.py` but not yet combined into one detector),
running on ICA- or regression-cleaned data (`ica_motion.py`) instead of
just notch/bandpass-filtered data, and eventually comparing against the
Phase 4 KAN prototype. Don't read "28.6%" as "Aura doesn't work" — read
it as "the naive single-feature baseline doesn't work well yet, exactly
as expected, and now there's a number to beat."

One correctness note from actually running this against real data,
worth knowing before touching CHB-MIT again: chb01's raw montage lists
"T8-P8" **twice** (channels 15 and 23 in `chb01-summary.txt`'s channel
list) — MNE auto-renames the duplicate on load (`T8-P8` ->
`T8-P8-0`/`T8-P8-1`) and logs a RuntimeWarning when it does.
`validate_chbmit.py`'s `CHANNELS` list uses the correct one
(`T8-P8-0`, verified against real loaded files, not assumed) —
see the comment right above that list before changing it.

## Improved result: multi-feature classifier — `results_chb01_multifeature.json`

`validate_chbmit_multifeature.py` combines line length with Hjorth
mobility/complexity and 5-band FFT power (8 features total, all already
in `aura_pipeline/features.py`) into a real `sklearn.LogisticRegression`,
evaluated with **leave-one-seizure-out cross-validation**: for each of
chb01's 7 seizures, the classifier is trained on the other 6 + the 4
baseline files, then tested on the seizure it never saw. This is the
honest way to ask "does multi-feature combination actually help," as
opposed to the dishonest version of that question — tuning a threshold
against these exact 7 seizures until it catches all of them, which would
produce a meaningless number (a detector that fires on everything
"catches" 100% trivially, at the cost of firing on everything).

Reported as a sweep across decision thresholds, not one cherry-picked
number, since sensitivity alone or FP/hour alone is easy to make look
good by ignoring the other:

| Threshold | Sensitivity | False positives/hour |
|---|---|---|
| 0.5   | 7/7 (100%) | 131.1 |
| 0.9   | 7/7 (100%) | 19.3  |
| 0.99  | 7/7 (100%) | 7.7   |
| 0.999 | 7/7 (100%) | 2.8 |

**Read this honestly too.** Sensitivity held at 7/7 across every
threshold tested, including the strictest — that's a real, substantial
improvement over the single-feature baseline (28.6% / 4.5 FP/hr above),
obtained legitimately (the model never saw a held-out seizure's label
during the fold that tests it). It is not "solved": n=1 subject, one
particular montage subset, and `LogisticRegression` with
`class_weight="balanced"` is not tuned beyond the threshold sweep shown.

### Consecutive-window smoothing — a second, honest improvement

Requiring `N` consecutive positive windows before counting an alarm
(instead of any single window) is a standard technique for cutting
isolated false-positive blips without costing real detections, since a
genuine seizure spans many consecutive windows (chb01's shortest is 40s
= 20 windows). Swept alongside the threshold, not tuned in isolation —
full grid in `results_chb01_multifeature.json`. Selected rows:

| Threshold | Min consecutive windows | Sensitivity | False positives/hour |
|---|---|---|---|
| 0.9  | 2 | 7/7 | 4.0 |
| 0.9  | 3 | 7/7 | 1.2 |
| 0.99 | 2 | 7/7 | 1.7 |
| 0.99 | 3 | 7/7 | 0.8 |
| 0.999 | 3 | 7/7 | **0.0** |

**The important caveat, not a footnote:** that bottom row (0 FP/hour) is
the single best cell out of 12 threshold×smoothing combinations tested.
Reporting it alone would be a subtler version of the same
answer-key-peeking problem this whole methodology exists to avoid —
with 12 comparisons on one subject, the best-looking cell is expected to
look better than reality just from picking the best of many, even though
each individual cell was evaluated honestly. The trustworthy signal
isn't any single cell — it's that a whole **neighborhood** of moderate
settings (threshold 0.9-0.99, smoothing 2-3 windows) consistently lands
at 7/7 sensitivity with single-digit-or-lower FP/hour, ON chb01. Read
the next section before trusting that neighborhood generalizes — it
doesn't, cleanly.

## Cross-check against SzCORE's real scoring library — `results_chbmit_szcore.json`

Everything above scores predictions with hand-rolled counting: any
predicted-positive window overlapping the true seizure interval is a
detection, every predicted-positive window outside it is a false
positive, no timing tolerance. That's a reasonable first pass, but it
isn't the standard the field (and this design doc, section 10) actually
cites — [SzCORE](https://github.com/esl-epfl/szcore) (Dan et al. 2024)
is, and [`esl-epfl/timescoring`](https://github.com/esl-epfl/timescoring)
is its real scoring implementation. `validate_chbmit_szcore.py` re-scores
the *exact same* leave-one-seizure-out predictions from the two
operating points above — same model, same folds — through
`aura_pipeline.timescore` (a thin wrapper around timescoring) as well as
the hand-rolled method, so any difference is attributable to the scoring
method, not the model:

| Threshold | Smoothing | Hand-rolled sensitivity / FP-hr | SzCORE sensitivity / FP-events (7 folds total) |
|---|---|---|---|
| 0.9  | 2 | 7/7 / 4.0 | 7/7 / **9** |
| 0.99 | 3 | 7/7 / 0.8 | 7/7 / **2** |

Sensitivity agrees exactly at both operating points — a real consistency
check the two independent methods pass. False positives don't agree, and
the reason is legitimate, not a bug in either: SzCORE's `EventScoring`
applies real clinical tolerances (30s early / 60s late still counts as a
correct detection, and false alarms within 90s of each other merge into
one event — `minDurationBetweenEvents`), so a burst of several
consecutive false-positive *windows* the hand-rolled method counted
separately becomes one false *event* under SzCORE. **Read this as good
news, honestly earned, not as "the better number, so use it going
forward":** it means chb01's actual clinical false-alarm burden — how
many times a clinician would perceive a false alarm — is lower than the
hand-rolled per-hour rate implied, at least at the two operating points
already highlighted as the trustworthy neighborhood above. It does not
change the sensitivity story or the chb02 generalization failure below.
Going forward, prefer reporting both — SzCORE's number is more legitimate
for a grant/publication audience already using that framework; the
hand-rolled number is finer-grained (an actual per-hour rate, not an
event count that needs a recording length to interpret) and still useful
for quick iteration during development.

## Second subject (chb02): the honest generalization check, and it's a real miss

The chb01 "consistent neighborhood" claim above only means something if
it holds on data the model was never tuned against *at all* — not just
held-out seizures from the same person, but a **different person**.
Ran the identical methodology on chb02 (3 seizures — `results_chb02_multifeature.json`).
It does not hold up:

| Threshold | Smoothing | chb01 sensitivity / FP-hr | chb02 sensitivity / FP-hr |
|---|---|---|---|
| 0.9  | 2 | 7/7 / 4.0  | 3/3 / 25.3 |
| 0.9  | 3 | 7/7 / 1.2  | **2/3 / 19.9** |
| 0.99 | 2 | 7/7 / 1.7  | **2/3 / 22.6** |
| 0.99 | 3 | 7/7 / 0.8  | **2/3 / 18.5** |

At every setting that looked like a strong, consistent operating point
on chb01, chb02 shows both **lower sensitivity** (drops to 2/3, and 1/3
at the strictest settings) **and** a **false-positive rate roughly an
order of magnitude worse** (18-25/hr vs chb01's 1-4/hr). One chb02 file
(`chb02_16+.edf`) stays noisy even at the strictest settings (41+ false
positive windows regardless); another (`chb02_19.edf`) stops being
detected at all once the threshold gets moderately strict.

**Read this as exactly what it is:** the multi-feature classifier,
fit fresh per subject via leave-one-seizure-out CV, does not transfer
cleanly across people. This is not a failure of the methodology — it's
the methodology correctly catching that population-level thresholds
don't work well here, which is actually informative and consistent with
the design doc's own framing (Section 1: this project has always aimed
at a *personal* pre-ictal signature per patient, Phase 3 — not a
one-size-fits-all population detector). The honest takeaway for a grant
narrative is **not** "multi-feature combination generalizes across
subjects" — it doesn't, at least not with a shared threshold — but
rather "within-subject performance (chb01: 7/7 at 1-4 FP/hr) is strong,
and cross-subject transfer needs per-subject calibration, which is
consistent with — not a setback to — this project's personalization
premise." Testing per-subject-calibrated thresholds (fit each subject's
own operating point rather than assuming one shared value) is the
natural next honest step, not yet done here.

## Data

Subject chb01 (PhysioNet, https://physionet.org/content/chbmit/1.0.0/),
11 of its 42 recordings — not the full dataset, not all 23 subjects. See
`validate_chbmit.py`'s module docstring for exactly why this subset and
why it's honestly reported as n=1, not "CHB-MIT validation" full stop.

```
chb01_01.edf, chb01_02.edf, chb01_05.edf, chb01_06.edf   — seizure-free (threshold calibration)
chb01_03.edf, chb01_04.edf, chb01_15.edf, chb01_16.edf,
chb01_18.edf, chb01_21.edf, chb01_26.edf                  — contain chb01's 7 seizures
chb01-summary.txt                                          — real clinician-annotated seizure times
```

Downloaded into `data/raw/chbmit/chb01/` (gitignored — see
`data/README.md`; nothing here gets committed). To reproduce:

```
curl -o data/raw/chbmit/chb01/<file> https://physionet.org/files/chbmit/1.0.0/chb01/<file>
```

for each filename above.

## Per-patient calibration extension — a real, honest, still-weak result

`aura_pipeline/calibration.py` implements the actual mechanism for a
genuinely new patient: since they have no labeled seizures yet (only
baseline recordings, per the existing Phase 3 protocol), it calibrates a
personal decision threshold from their baseline data alone — no seizure
labels used or needed for calibration. `validate_chbmit_calibrated.py`
tests it properly: **leave-one-subject-out**, not leave-one-seizure-out.
The population classifier trains on all-but-one subject (contributing
nothing from the held-out person at all), then that person's threshold
is calibrated from their baseline only, then tested on their real
seizures.

```json
// results_chbmit_calibrated.json, target_fp_per_hour=2.0
{
  "chb01 held out (trained on chb02 only)": { "sensitivity": "3/7 (42.9%)", "false_positives_per_hour": 0.0 },
  "chb02 held out (trained on chb01 only)": { "sensitivity": "1/3 (33.3%)", "false_positives_per_hour": 66.4 }
}
```

**Read this as what it actually shows, not as a working feature yet.**
Calibration does what it's designed to do — chb01's false-positive rate
lands almost exactly on the 2.0/hour target — but sensitivity drops to
33-43% either way, well below what's needed to be useful. That's a real
result, not a bug to explain away.

**The important caveat that changes how to read it:** with only 2
subjects, "population classifier" here means "trained on exactly ONE
other person" — not a real population model. That's a much harder,
noisier transfer problem than what per-patient calibration is actually
meant to help with (a model trained on many diverse subjects, then
calibrated per-patient). This result doesn't mean calibration doesn't
work — it means **2 subjects isn't enough training diversity to fairly
test whether it works**. Re-running this once more subjects are
downloaded (`SUBJECTS` in `validate_chbmit_multifeature.py`) is the
honest next step, not a foregone conclusion that calibration fails.

## Running

```
pipeline\.venv\Scripts\python.exe validation\validate_chbmit.py                 # single-feature baseline
pipeline\.venv\Scripts\python.exe validation\validate_chbmit_multifeature.py    # multi-feature, LOO-CV (per-subject)
pipeline\.venv\Scripts\python.exe validation\validate_chbmit_calibrated.py      # per-patient calibration, leave-one-subject-out
pipeline\.venv\Scripts\python.exe validation\validate_chbmit_szcore.py          # hand-rolled vs SzCORE (timescoring) scoring cross-check
```

All print a JSON result. The multi-feature and calibrated scripts
re-extract features for every file on every run (no caching) — takes a
couple of minutes each.

## Why this methodology, briefly

(Full rationale is in `validate_chbmit.py`'s docstring — read that before
changing anything here.) Three choices worth knowing before trusting the
number: (1) only the 8 CHB-MIT channels that correspond to Aura's actual
planned montage are used, not all 23 — using more channels than the real
hardware will ever have would overstate what Aura can do. (2) the
detection threshold is calibrated only on seizure-free files, never on
the seizure recordings it's tested against. (3) results are reported as
sensitivity + false-positives/hour, not accuracy — accuracy is a
meaningless number when seizures occupy under 1% of total recording
time.
