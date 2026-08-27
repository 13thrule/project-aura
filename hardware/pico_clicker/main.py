"""
Aura Trigger — Raspberry Pi Pico firmware.

Single physical button -> debounced interrupt -> JSON event line over USB
serial (CDC). No screen, no app: the button is meant to be usable during
an aura without looking at anything.

Wiring (see docs/DESIGN_DOCUMENT.md section 2.2):
  - Arcade button between BUTTON_PIN and GND, using an internal pull-up
    (button pulls the pin LOW when pressed -> IRQ_FALLING). Confirmed
    against the actual wired hardware, not assumed — an earlier version
    of this file assumed 3V3+pull-down+IRQ_RISING, which does not detect
    anything when the button is wired to GND instead: pressing it moves
    the pin from LOW to LOW (already resting there via the pull-down),
    so no edge ever fires. Caught by testing on real hardware with the
    real wiring, not by reasoning about it.
  - Onboard LED blinks once per accepted press as physical confirmation
    for the user, independent of whether the host is even listening.

Timestamp caveat (read before trusting this in the field): the Pico has
no battery-backed RTC. `machine.RTC()` resets to a fixed epoch on every
power loss/reboot and is only meaningful if something syncs it from the
host on boot. Until that host-sync handshake is actually built and
tested, treat `rtc_time` in the emitted payload as untrustworthy and let
the broker's own receipt time (host clock) be the source of truth for
wall-clock alignment with the Cyton stream — see broker/src/trigger.rs.

ISR safety: MicroPython forbids heap allocation inside a hard interrupt
handler (confirmed against MicroPython's own docs, not assumed) — no
`dict`/string construction, no `json.dumps()`, no blocking I/O, no
blocking `sleep`. `handle_trigger()` below does none of that; it does
integer arithmetic only and hands off to `_emit_trigger()` via
`micropython.schedule()`, which is the documented mechanism for exactly
this "defer real work out of IRQ context" situation. An earlier version
of this file did all of that work directly inside the IRQ handler — it
would run fine on a bench test and could fail unpredictably
(intermittent `MemoryError`, missed button presses during the 100ms
blocking LED sleep) in the field, which is a far worse place to discover
it than now, before real hardware exists.
"""

import machine
import time
import sys
import json
import micropython

micropython.alloc_emergency_exception_buf(100)  # lets exceptions raised in the ISR actually get reported

# Configuration
BUTTON_PIN = 14      # GPIO pin for the tactile arcade button — confirmed
                      # against real hardware by polling several candidate
                      # GPIOs and watching which one actually toggled on a
                      # real press. Was 15 in an earlier draft; the wired
                      # button turned out to be on GP14, not GP15 (easy to
                      # mix up: physical pin 15 on the board is a different
                      # GPIO than "GP15", which is physical pin 20).
LED_PIN = "LED"       # Onboard Pico LED for visual feedback
DEBOUNCE_MS = 200     # Milliseconds to ignore mechanical bounce

# Setup Hardware
button = machine.Pin(BUTTON_PIN, machine.Pin.IN, machine.Pin.PULL_UP)
led = machine.Pin(LED_PIN, machine.Pin.OUT)

last_trigger_time = 0


def _emit_trigger(current_time):
    """Runs via micropython.schedule() — NOT hard IRQ context — so heap
    allocation and blocking calls are safe here, unlike in
    handle_trigger() below."""
    # NOT wall-clock-accurate until an RTC sync-on-boot handshake
    # exists — see module docstring. Included for forward-compat with
    # that handshake, not currently trustworthy on its own.
    rtc_time = machine.RTC().datetime()

    payload = {
        "event": "AURA_TRIGGER",
        "ticks_ms": current_time,   # monotonic, always trustworthy
        "rtc_time": rtc_time,       # untrustworthy until RTC sync exists
        "device": "PICO_CLICKER_V1",
    }

    # Emit over USB Serial to the Rust broker
    sys.stdout.write(json.dumps(payload) + "\n")

    # Visual feedback for the user
    led.value(1)
    time.sleep_ms(100)
    led.value(0)


def handle_trigger(pin):
    """Hard IRQ context — see module docstring. Integer arithmetic only;
    no object construction, no I/O."""
    global last_trigger_time
    current_time = time.ticks_ms()

    # Hardware debouncing
    if time.ticks_diff(current_time, last_trigger_time) > DEBOUNCE_MS:
        last_trigger_time = current_time
        try:
            micropython.schedule(_emit_trigger, current_time)
        except RuntimeError:
            # Scheduler queue full (rare — only under very rapid repeat
            # presses). Drop this one event rather than raise inside the
            # ISR or block waiting for space.
            pass


# Attach hardware interrupt
button.irq(trigger=machine.Pin.IRQ_FALLING, handler=handle_trigger)

# Main loop keeps the script alive
print(json.dumps({"status": "Aura Trigger initialized and waiting..."}))
while True:
    # Sleeps to save power until the hardware interrupt wakes it
    machine.idle()
