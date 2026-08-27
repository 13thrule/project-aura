"""Aura Trigger firmware, provenance-chained variant.

Adds tamper-evidence to the base main.py (see that file for the core
debounce/button logic — this is a variant, not a replacement, kept as a
separate file so main.py stays the simple baseline).

## What this does and does not prove

This gives you a **hash chain** over the session's trigger events: each
event's hash depends on the previous event's hash, so editing, deleting,
or reordering any event after the fact breaks every hash after it in the
chain — genuinely detectable, verifiable tamper-evidence for a released
dataset (design doc section 1, "Open Data Contribution").

It does **not** give you cryptographic proof that the data came from a
real physical device and human subject. That would need a secret key an
attacker cannot extract even with physical access to the board — i.e. a
secure element (e.g. an ATECC608A, ~£2-3, I2C, hardware-protected key
storage), not the Pico's plain flash. A key stored in RP2040 flash can be
dumped by anyone with physical access to the board, so it cannot serve as
a trust anchor against a motivated attacker. True hardware attestation is
future work, gated on adding that chip — not in this budget.

Two mistakes worth naming explicitly, because an earlier draft of this
file made both:

1. A prefix-secret construction — `sha256(secret + message)` — is NOT a
   safe substitute for HMAC. SHA-256 is a Merkle-Damgard hash and is
   vulnerable to length-extension attacks: someone who observes one
   (message, signature) pair can compute a valid signature for
   `message + padding + attacker_data` without ever knowing `secret`.
   Real HMAC exists specifically to close this hole (two nested hashes,
   not one). This file sidesteps the whole problem by not using a secret
   at all — a hash chain needs no key, so there's nothing to leak.
2. A secret hardcoded in this source file would be fatal for an
   open-source project (design doc section 1: "Open Data Contribution").
   The whole point of a provenance scheme is that a reader of the public
   repo can VERIFY a chain, not forge one — a hardcoded shared secret in
   the code everyone can read defeats that on day one. Hash-chaining
   avoids this because there's no secret in the design at all.

## ISR safety

MicroPython forbids heap allocation inside a hard interrupt handler
(confirmed against MicroPython's own docs). This module does real
allocation-heavy work per event — a `sha256` object, string
concatenation, `.hex()`, `json.dumps()` — none of which is safe to run
directly in `button.irq(...)`'s handler. `handle_chained_trigger()` below
does only integer arithmetic (debounce check, sequence counter,
`time.ticks_us()` — MicroPython's small-int values don't heap-allocate)
and writes into two pre-allocated single-element lists, then defers the
actual chain-hash computation and serial write to `_emit_chained_trigger()`
via `micropython.schedule()`. Passing `None` (a singleton, no allocation)
as schedule()'s argument and reading the real values back out of the
pre-allocated lists avoids allocating a tuple/argument at the point of
the schedule() call itself, which would reintroduce the same problem one
level up.

Ordering note: this relies on `micropython.schedule()` processing queued
callbacks FIFO and fast relative to the 200ms debounce window, so two
button presses can't have their deferred chain-hash computations run out
of order or overwrite each other's pending values before being read.
That holds for realistic human button-press rates (nobody presses faster
than the scheduler drains its queue) but isn't a formally proven bound
for arbitrary trigger rates — worth knowing if this pattern is ever
reused somewhere presses could arrive faster than a human finger allows.
"""

import machine
import time
import sys
import json
import micropython
from uhashlib import sha256

micropython.alloc_emergency_exception_buf(100)  # lets exceptions raised in the ISR actually get reported

BUTTON_PIN = 14  # confirmed on real hardware — see main.py's comment on this constant
LED_PIN = "LED"
DEBOUNCE_MS = 200

button = machine.Pin(BUTTON_PIN, machine.Pin.IN, machine.Pin.PULL_UP)  # button wired to GND, not 3V3 — see main.py's docstring
led = machine.Pin(LED_PIN, machine.Pin.OUT)

last_trigger_time = 0
event_sequence_id = 0

# Genesis hash for this boot session. Not a secret — it's public in every
# emitted event and exists only to make each session's chain distinct, not
# to authenticate anything. A real session identifier (synced from the
# host on boot) would be better than os.urandom here; left simple for now.
import os
chain_hash = sha256(os.urandom(16)).digest()

# Pre-allocated at module load (safe: this happens once, at import time,
# never inside the ISR) so the ISR can hand values to the deferred
# function by mutating existing objects rather than constructing new ones.
_pending_seq = [0]
_pending_ticks_us = [0]


def _emit_chained_trigger(_arg):
    """Runs via micropython.schedule() — NOT hard IRQ context — so heap
    allocation and blocking calls are safe here, unlike in
    handle_chained_trigger() below."""
    global chain_hash

    event_sequence_id = _pending_seq[0]
    monotonic_ticks = _pending_ticks_us[0]

    raw_payload = "{}:{}:AURA_TRIGGER".format(event_sequence_id, monotonic_ticks)
    h = sha256()
    h.update(chain_hash)          # previous entry's hash -> this is the chain link
    h.update(raw_payload.encode("utf-8"))
    chain_hash = h.digest()

    packet = {
        "seq": event_sequence_id,
        "event": "AURA_TRIGGER",
        "ticks_us": monotonic_ticks,
        "chain_hash": chain_hash.hex(),
        "device": "PICO_CLICKER_V1",
    }
    sys.stdout.write(json.dumps(packet) + "\n")

    led.value(1)
    time.sleep_ms(100)
    led.value(0)


def handle_chained_trigger(pin):
    """Hard IRQ context — see module docstring. Integer arithmetic and
    pre-allocated-list mutation only; no object construction, no I/O."""
    global last_trigger_time, event_sequence_id

    current_time = time.ticks_ms()
    if time.ticks_diff(current_time, last_trigger_time) <= DEBOUNCE_MS:
        return
    last_trigger_time = current_time
    event_sequence_id += 1

    _pending_seq[0] = event_sequence_id
    _pending_ticks_us[0] = time.ticks_us()
    try:
        micropython.schedule(_emit_chained_trigger, None)
    except RuntimeError:
        # Scheduler queue full (rare — only under very rapid repeat
        # presses). Drop this one event rather than raise inside the ISR.
        pass


button.irq(trigger=machine.Pin.IRQ_FALLING, handler=handle_chained_trigger)

print(json.dumps({
    "status": "Provenance-chained Aura Trigger initialized.",
    "genesis_hash": chain_hash.hex(),
}))
while True:
    machine.idle()
