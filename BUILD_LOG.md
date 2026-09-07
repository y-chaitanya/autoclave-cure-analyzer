# Build Log

Decisions I made while building this, and why. Written as I go, so the reasoning
is recorded rather than reconstructed later.

Every entry here is something a reader could reasonably disagree with. That's the
point of writing them down.

---

## Sampling interval: one reading per minute

Real autoclave controllers sample faster, often every few seconds. At one reading
per second, a six-hour run is over 21,000 rows — impossible to eyeball while
developing.

One per minute gives around 250 rows for a four-hour run: realistic in shape,
small enough to read. The detection logic works from timestamps, so the interval
isn't baked into it and can change later without touching the rules.

---

## The setpoint problem

The spec says soak at 350°F. My first generator held the soak at **352**.

The ramp loop ran `while temperature < SOAK_TEMP`. At minute 93 the temperature
was 349. Is 349 below 350? Yes — so the loop ran once more, added 3°F, landed on
352, and *then* stopped. Every "good" run I generated was already 2°F above spec.

Nothing errored. Nothing looked wrong on screen. The number was just wrong.

**Second attempt** — check ahead before stepping:

```python
while temperature + RAMP_RATE <= SOAK_TEMP:
```

Now it held at **349**. Undershooting by 1 instead of overshooting by 2.

**Why neither worked.** 350 − 70 = 280 degrees to climb. At 3°F per minute that's
93.33 minutes. There is no minute at which a 3-degree step lands exactly on 350.
The step size doesn't divide evenly into the range, so any loop must stop short
or overshoot. No loop condition fixes that.

**What I settled on** — keep the look-ahead condition, then snap to the setpoint
before the soak begins:

```python
temperature = SOAK_TEMP
```

Not because it's simpler, but because it's what the equipment does. A real
controller doesn't march in blind fixed steps and hold wherever it lands. It
ramps toward a setpoint and holds *at* the setpoint.

**The generator should model the machine, not my loop.**

### A consequence worth recording

The snap makes the final ramp step 4°F instead of 3°F:

```
91,343.0
92,346.0
93,350.0    ← 4-degree step
```

Acceptable while the spec's maximum ramp rate is 5°F/min. But if I ever set a
maximum below 4, my own generator would produce a "good" run that my own detector
flags as a violation — a false positive built into the test data rather than into
the detection logic.

The generator and the spec are coupled at this point. When accuracy numbers look
wrong later, check upstream before assuming the detector is at fault.

---

## Pressure: gradual vent, not an instant drop

Pressure holds at 85 psi through ramp and soak, then vents during cool-down.

My first instinct was an instant drop to zero — the cure ends, the pressure goes.
I chose a gradual vent at 4 psi per minute instead, for a reason that isn't about
realism.

**An instant drop is a cliff edge in the data.** Every rule I write about pressure
becomes trivially easy to satisfy, because the transition is unmistakable. A
gradual vent creates a genuine question: *when does the cure actually end?*
Pressure is falling, temperature is falling, and there's a window where "still
curing" and "cooling down" overlap. Stage detection has to make a judgment call
there.

That ambiguity is the interesting part of the problem. Clean transitions prove
nothing.

There's a practical reason too. When I inject a pressure-sag fault later, the
detector has to distinguish *pressure dropping because we're venting normally*
from *pressure dropping because something failed*. With an instant vent that
distinction doesn't exist — any mid-run drop is obviously a fault. With a gradual
vent, the detector has to use stage context to decide.

Which is why stage detection comes before deviation detection in the pipeline.

---

## Clamping pressure at zero

```python
pressure = max(0.0, pressure - VENT_RATE_PSI)
```

85 psi at 4 psi/min reaches zero after 22 minutes, but cool-down runs 40. Without
a floor, the last rows would read about −72 psi — physically meaningless, and it
would have quietly poisoned any pressure rule written against it.

`max()` enforces the floor in one line rather than an if-statement.

---

## Specification in JSON, not in code

Different parts cure to different specs. If the thresholds live in the code, then
changing the part means editing the program.

The spec is **input**, not logic. It also means the parameters are visible and
arguable rather than buried — which matters, because they're my judgment, not
anyone's actual process specification.

---

## Open questions

Things I haven't resolved. Recorded rather than guessed at.

**Should vacuum still be held at the end of the run?** The cure ends at minute
213, pressure reaches zero around 234, and the run continues to 252. So there's a
stretch with the part still cooling, no pressure, and vacuum still on. I don't
know whether that's right.

**How long should a deviation persist before it counts?** Sensor noise will make
readings cross a threshold briefly. Flagging every crossing produces false
positives; requiring too much persistence misses real short excursions. I'll have
a number once I can measure it against known injected faults — not before.

---

## A pattern I've noticed

The bugs that worry me aren't the ones that crash. They're the ones where the
program runs happily and produces a number that's wrong — 352 instead of 350, or
the fixed-range SUMIF in my [AR
analyzer](https://github.com/y-chaitanya/ar-aging-risk-analyzer) that understated
reported exposure by $30,750 once the dataset grew. Nothing on screen looked
broken in either case.

Which is why I keep building the same thing: something that checks its own
output. The tie-out check there, and the verification step planned for the LLM
summary here.

I don't think that's a coincidence.
