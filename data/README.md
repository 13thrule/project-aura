# data/

Gitignored. Not committed, ever — this is where real acquisition sessions
land once hardware exists.

- `raw/` — untouched CSV/EDF straight from `broker/` and the Cyton's own
  SD card log. Never mutated (CLAUDE.md "Data constraints").
- `derivatives/` — output of `pipeline/`: filtered signals, extracted
  features, and eventually BIDS/EEG-BIDS-formatted exports for anything
  leaving this machine (design doc section 5).

No participant data should exist in this repo's git history under any
circumstance — if something ends up staged here, unstage it before
committing.
