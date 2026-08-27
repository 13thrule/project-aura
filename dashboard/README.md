# Aura dashboard

Vanilla HTML5 Canvas live visualization (design doc section 3.2,
CLAUDE.md: no frameworks). Single static file, no build step.

## Status — verified working (browser-tested, no console errors)

Open `index.html` directly in a browser (a `file://` URL works, or serve
the folder statically) — it runs entirely in synthetic-demo mode with no
broker required, and that demo path exercises the *same* binary decode
function real WebSocket data would use, not a separate fake code path.

- 8-channel canvas trace, rendering ~250Hz synthetic data through the
  real wire-format decoder.
- Client-side 50Hz notch filter toggle (real RBJ biquad, not a mock) —
  visibly cleans the synthetic mains-hum component when enabled. This is
  cosmetic for the live trace only; it is not the analysis pipeline's
  real filter (`pipeline/aura_pipeline/filters.py`).
- Seizure-likelihood score panel (formerly a "KAN pre-ictal gauge" that
  was a pure `Math.random()` walk with no data behind it at all — dropped
  the KAN name entirely since it never ran a KAN and now definitely
  doesn't: `pipeline/aura_pipeline/kan_detector.py` remains an offline
  Phase 4 research prototype, design doc section 4.4, with no live
  inference path). Now a **real, live** scikit-learn `LogisticRegression`
  (`pipeline/tools/export_dashboard_model.py`), trained on all of chb01's
  actual CHB-MIT recordings using the same 8 features
  `pipeline/aura_pipeline/features.py` defines, exported to
  `dashboard/model_chb01.json` and scored client-side against features
  this page computes live from its own real buffered signal (see
  "Real live feature extraction" below) — not synthetic, not a
  placeholder. Honestly caveated in the panel itself (loaded straight
  from the model file, so it can't drift out of sync): fit on a single
  subject, and `pipeline/validation/README.md`'s chb02 generalization
  check found this exact model class does not reliably transfer to a
  different person. If `model_chb01.json` fails to load, the panel says
  so plainly ("model unavailable") rather than falling back to a fake
  value.
- Real live feature extraction (`computeLiveFeatures()`, every 500ms) —
  JS ports of `pipeline/aura_pipeline/features.py`'s actual formulas
  (line length, Hjorth mobility/complexity, direct-DFT band power for
  delta/theta/alpha/beta/gamma), run over each channel's real most-recent
  window. Feeds both the topology panel and the seizure-likelihood score
  above — genuinely the same features the validated Python pipeline
  computes, just recomputed client-side from the live buffer instead of
  offline from a file, at a coarser DFT frequency resolution (fixed
  1Hz-spaced sample points per band, not every FFT bin) for CPU headroom.
- Trigger event log — shows `pico_ticks_ms` + local receipt time, plus
  **real client-side hash-chain verification** for
  `hardware/pico_clicker/provenance_main.py`'s protocol: `seq`,
  `chain_hash`, and the exact `chain_ticks_us` value are now propagated
  through `broker/src/trigger.rs` (which used to silently drop every
  provenance_main.py line entirely — it required a `ticks_ms` field that
  protocol never sends), and `verifyChainedTrigger()` recomputes
  `sha256(prev_hash + payload)` with the real Web Crypto API, matching
  the Pico's exact construction byte-for-byte. Browser-tested end to end:
  a legitimate chained event shows green "chain verified"; a deliberately
  corrupted one (the synthetic demo injects one periodically) shows red
  "CHAIN BROKEN — hash mismatch" — both outcomes confirmed live, not just
  asserted in code. Scope limit, stated plainly in the panel: this
  dashboard never sees the Pico's true genesis hash (only printed in the
  firmware's startup line, which the broker doesn't forward), so the
  first chained event in a session is an unverifiable anchor, not a
  confirmed genesis.
- Scalp topology panel — a 2D Canvas (not Three.js/WebGL — see below)
  top-down node map at the actual design doc section 2.1 montage (Fp1,
  Fp2, F7, F8, T3, T4, O1, O2 — an earlier draft of this idea used
  C3/C4/P7/P8, a different montage that doesn't match the hardware this
  project actually specifies). Node color is a **real** per-channel
  alpha/beta FFT power balance (direct DFT, same power-per-band method as
  `pipeline/aura_pipeline/features.py`'s `band_power()`, at a coarser
  frequency resolution — no longer the old biquad-filter approximation);
  node glow size is real line length (Esteller et al. 2001) over the same
  window, normalized against a slowly-decaying running max. Labeled in
  the panel as real, with the resolution caveat stated plainly.
  **Why Canvas 2D and not Three.js:** CLAUDE.md specifies vanilla
  Canvas/WebGL with no heavy frontend deps, and design doc section 3.2
  specifies "no cloud dependency" — a CDN-loaded Three.js would violate
  both (a vendored local copy is possible later if a true 3D view is ever
  worth the maintenance cost, but wasn't for an 8-node display).
  Also fixed a wire-format mismatch in an earlier draft of this
  panel's WS listener: it expected `{"type":"eeg_frame","data":[...]}`
  JSON messages, which this project's actual protocol never sends (EEG
  samples are binary frames — see `broker/src/dashboard.rs`) — that
  listener would have silently never fired against a real broker. The
  topomap now reads from the same decoded sample stream the trace view
  uses, not a second competing listener.
- Health bar — WS status, measured stream rate, a real per-connection
  dropped-frame counter (needs the sequence byte in the wire format —
  see `broker/src/dashboard.rs`), session duration. Electrode impedance
  is explicitly labeled "N/A — not implemented" rather than a fabricated
  number, since neither the broker nor firmware support it yet.
- Spectrogram panel — a real client-side direct DFT (40 bins, 1-50Hz,
  mean across channels), not a decorative animation. Uses a
  slowly-decaying running max for the color scale rather than
  normalizing each column independently, so a real surge actually stands
  out instead of every quiet period looking equally "loud." Display-only
  approximation like the topomap — not `features.py`'s real spectral
  analysis.
- Trigger markers on the EEG trace itself — red vertical lines at the
  exact buffer position each Aura Trigger event fired at, aged out once
  they scroll past the window (browser-tested: confirmed a marker
  renders at the correct position and disappears after the 6-second
  window elapses, not just assumed from the code).
- Full **fully wired, real end-to-end test** (2026-08-27): real button
  presses on a real Pico flowed through the real broker — including
  `storage.rs`, now durably writing every trigger event to a
  hash-chained CSV — into this real dashboard, all running together at
  once. Not a synthetic demo, not isolated unit tests: the whole system,
  live.
- Replay-mode banner — a persistent, unmissable striped orange bar
  spanning the top of the page ("⚠ REPLAY MODE — NOT A LIVE SIGNAL —
  ...") whenever `broker/src/replay.rs` is streaming a recorded file
  instead of live hardware. Exists specifically so replayed data (real
  human EEG, used to exercise this dashboard before Cyton hardware
  exists — see `broker/README.md`) can never be mistaken for a real-time
  patient stream, which would be a genuine safety problem in a real
  seizure-detection tool, not just a labeling nitpick. The broker
  re-sends the banner message every ~2s for as long as replay runs (not
  just once at startup) so a tab that connects mid-replay still sees it;
  this page hides the banner if it stops hearing that message for 6s.
  Browser-tested end to end (2026-08-27) against a real replayed CHB-MIT
  seizure recording: banner visible throughout, real EEG rendering in the
  trace view, zero console errors.
- Event Log (formerly "Trigger Event Log," broadened) — every row is a
  real, sourced event: Aura Trigger presses (unchanged), real
  connection-state changes (this page's own WebSocket connect/disconnect
  — client-side but genuinely real, not simulated), and real
  dataset-ground-truth seizure annotations (`AuraEvent::Annotation` from
  `broker/src/replay.rs`, sourced from the recording's own clinician-
  verified summary file, **never a live detection** — labeled as such in
  the panel and kept visually and semantically distinct from the
  seizure-likelihood score panel's real-but-caveated model output). A
  seizure annotation also draws a thick red (start) / green (end) marker
  directly on the EEG trace, distinct from Aura Trigger's thin red
  marker. Browser-tested end to end (2026-08-27) against a real chb01
  seizure clip: SEIZURE START/END rows appeared at the correct
  timestamps with the correct source-recording offset, markers rendered
  at the correct trace position, zero console errors.
- Real score + topology upgrade browser-tested (2026-08-27): synthetic
  demo mode showed a real, varying score value ("0.458, elevated") with
  the model's real caveat text loaded, and visibly differentiated
  per-channel topology node colors (not the old uniform look) — zero
  console errors, confirmed against a fresh page load with console
  tracking active from before script execution.

Set `BROKER_WS_URL` near the top of the `<script>` block to point at the
real broker (`broker/src/dashboard.rs`) once it's serving a websocket —
the wire format (binary EEG frames, JSON text for trigger events) is
documented in that file's module doc comment and mirrored exactly in
`decodeSampleFrame()` here.

## Not yet built

- No live inference path from the broker itself — the seizure-likelihood
  score is computed entirely client-side (real features, real trained
  weights, but scored in the browser, not by a running model server the
  broker talks to). `kan_detector.py`'s actual KAN architecture (design
  doc section 4.4) remains an offline Phase 4 research prototype with no
  connection to this dashboard at all.
- `model_chb01.json` requires being served alongside `index.html` (a
  `file://` URL can't `fetch()` it in most browsers) — the synthetic
  demo mode's trace still works standalone, but the score panel will
  show "model unavailable" without an HTTP server. Re-run
  `pipeline/tools/export_dashboard_model.py` if `aura_pipeline/features.py`
  or the chb01 training set ever changes, so the exported weights don't
  silently drift from what's actually validated.
