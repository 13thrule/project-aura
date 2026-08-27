# Aura Trigger firmware

MicroPython firmware for the off-grid hardware "clicker" described in
`docs/DESIGN_DOCUMENT.md` section 2.2.

## Status

**Fully verified end-to-end on real hardware with a real button**
(2026-08-27) — a real Pico, MicroPython v1.29.0 official firmware, real
arcade button wired to GND. Real presses produce clean `AURA_TRIGGER`
JSON lines over serial with correctly increasing `ticks_ms` and working
debounce (rate-limited to the 200ms floor rather than firing on every
bit of mechanical contact chatter).

Two real wiring/config mismatches were found and fixed by actually
testing on hardware, not by re-reading the code:

1. **Polarity.** The button is wired between GPIO and **GND**, not 3V3.
   The firmware originally assumed 3V3 + internal pull-down +
   `IRQ_RISING` — with a GND-wired button that never produces an edge
   (pressing it moves the pin from LOW to LOW, since the pull-down
   already rests it there). Now uses `PULL_UP` + `IRQ_FALLING`, which is
   also the more common convention for GND-wired buttons.
2. **Pin number.** The button is physically wired to **GP14**, not GP15.
   Confirmed by polling several candidate GPIOs simultaneously on the
   real board and watching which one actually toggled on a press — a
   more reliable check than trusting a pinout diagram, since it's easy
   to mix up "GP15" (physical pin 20) with "physical pin 15" (a
   different GPIO). `BUTTON_PIN` is now `14` in both firmware files.

Also confirmed while testing: `machine.RTC().datetime()` genuinely
serializes cleanly through `json.dumps()` on real hardware (was an
assumption before), and the `micropython.schedule()` ISR-deferral
pattern (see below) works correctly under real interrupt load, not just
in a manually-simulated call.

Not yet tested: holding the button vs. discrete press-release cycles —
the firmware fires once per 200ms+ of continued contact rather than
detecting release, so a held button fires repeatedly. Worth deciding
whether that's the wanted behavior once real usage patterns are known.

**ISR safety, fixed after a real review caught it:** an earlier draft did
all the real work — `json.dumps()`, `sys.stdout.write()`,
`machine.RTC().datetime()`, a blocking 100ms `sleep` — directly inside
`button.irq(...)`'s handler. MicroPython's own docs are explicit that
heap allocation isn't permitted in a hard interrupt handler; this would
have run fine on a bench test and could fail unpredictably once real
(intermittent `MemoryError`, missed presses during the blocking sleep).
Both `main.py` and `provenance_main.py` now do only integer arithmetic in
the actual IRQ handler and defer everything else to a scheduled function
via `micropython.schedule()` — read the module docstrings, especially
`provenance_main.py`'s, which has an extra ordering note worth knowing
before touching that pattern.

## Flashing

1. Flash standard MicroPython firmware onto the Pico (from micropython.org).
2. Copy `main.py` onto the board (e.g. via Thonny, `mpremote`, or `rshell`).
3. Wire an arcade button between GP14 and GND (internal pull-up —
   pin reads LOW on press). Verify against the real board before wiring
   permanently: physical pin position and GPIO number don't match 1:1 on
   the Pico (e.g. "GP15" is physical pin 20, not physical pin 15) — see
   the Status section above for how this was confirmed empirically
   rather than assumed from a diagram.

## Protocol

One JSON line per accepted press, over USB serial (CDC):

```json
{"event": "AURA_TRIGGER", "ticks_ms": 123456, "rtc_time": [...], "device": "PICO_CLICKER_V1"}
```

- `ticks_ms` — the Pico's own monotonic clock (`time.ticks_ms()`). Always
  trustworthy for relative timing, never trustworthy as wall-clock time.
- `rtc_time` — `machine.RTC().datetime()`. **Not trustworthy** until a
  host-sync-on-boot handshake exists (the Pico has no battery-backed RTC
  and resets to a fixed epoch on every power loss). The broker treats its
  own receipt time as the source of truth for now — see
  `broker/src/trigger.rs`.

## Provenance variant (`provenance_main.py`)

A separate file, not a replacement for `main.py` — adds a hash chain over
trigger events so a released dataset can prove no event was edited,
deleted, or reordered after capture. Read the module docstring in that
file before using it: it explains exactly what this does and does not
prove (tamper-evidence, yes; cryptographic proof of physical human
origin, no — that needs a secure element chip this board doesn't have),
and documents two concrete mistakes an earlier draft made (a
length-extension-vulnerable prefix-secret "signature," and a secret
hardcoded into open-source firmware) so nobody reintroduces them later.

## Next steps

- Decide whether the "fires every 200ms while held" behavior is right
  for the final device, or whether press-release-once semantics are
  wanted instead (see Status above).
- Decide whether an RTC-sync-on-boot handshake is worth building, or
  whether host-receipt-time is accurate enough for this project's
  purposes (likely yes, given USB serial latency is small relative to the
  seizure timescales involved — but validate that assumption, don't
  assume it).
- Wire into the TPU enclosure per `hardware/enclosure/` once it exists.
- Point `broker/` (once its trigger ingestion is pointed at a real serial
  port — see `broker/README.md`) at this Pico and confirm end-to-end
  delivery all the way to the dashboard, not just to a terminal listener.
