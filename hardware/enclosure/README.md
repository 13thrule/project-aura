# TPU enclosure

Design doc section 2.3. **Empty — no CAD exists yet.**

## Do not start this from datasheet dimensions

This project has a standing rule from prior hardware work: CAD that
"validates as a solid" in software is not the same as CAD that fits the
real part. Once the Cyton board and Pico are purchased, measure them
directly (calipers, not the datasheet outline drawing) before modeling
the enclosure cavities.

## Requirements (from the design doc)

- Impact-resistant TPU, 3D-printed.
- Multi-color printing to color-code electrode ports for foolproof
  anatomical placement (Section 2.1's 10-20 system mapping).
- Must route all electrode leads under a tight neoprene skullcap — the
  enclosure's lead exit points need to be positioned with that routing in
  mind, not just wherever is convenient for the PCB layout.

## Suggested workflow once hardware arrives

Use the `cad` skill (STEP-first parametric CAD) to model this once real
measurements exist, and `cad-viewer` / `dfam-check` to review printability
before sending anything to a printer.
