# 🔥 Autoclave Cure Cycle Deviation Analyzer

A tool that reads autoclave cure run logs, checks them against a cure
specification, flags every deviation, and writes an engineering summary — with a
verification step that confirms the summary only reports what the data actually
shows.

Not a chatbot demo and not a wrapper around an API — a rule-based detection
engine with a language model layered on top for the part language models are
actually good at, and a check on that model because it can be wrong.

> ⚠️ **Status: in development.** Started 3 September 2026. Completed stages are
> ticked below and evidenced with screenshots; everything else is marked planned.
> Nothing is claimed here that isn't working yet.

**Decisions and reasoning are recorded in [BUILD_LOG.md](BUILD_LOG.md).**

---

## 🎯 Why I'm building this

I wanted to build something in a real manufacturing domain rather than another
generic assistant, and to work out where a language model genuinely helps and
where it should be kept away from the decision.

The honest answer, as far as I can tell so far, is that the model shouldn't
decide anything. Rules decide. The model explains. And something has to check
that the explanation matches the rules — which is the part most demos skip.

---

## 🏭 The problem

In aerospace composite manufacturing, parts are cured in an autoclave under a
controlled cycle — heat at a controlled rate, hold at temperature for a set
time, cool at a controlled rate, with vacuum and pressure held throughout. A run
takes hours.

The cure record is a quality document. If the run drifts outside spec, that part
may need engineering disposition or be scrapped. Someone has to read the log and
decide.

That review is manual and repetitive, and a short deviation buried in hours of
data is easy to miss. It's the kind of task where rules and a language model
each do the half they're suited to.

### What the process involves

*My notes from learning the domain. Written in my own words as I read — I'm not
a composites engineer, and I'd welcome corrections.*

- **Ramp** — the controlled temperature rise, in degrees per minute. Too slow
  and the cure doesn't proceed as intended; too fast risks an exotherm, where
  the resin's own reaction heat runs ahead of the controller.
- **Soak / dwell** — holding at cure temperature long enough for the resin to
  fully cross-link. Time spent below target doesn't count toward cure.
- **Vacuum** — pulls air and volatiles out of the laminate. A bag leak part-way
  through can leave voids in the finished part.
- **Pressure** — consolidates the plies and suppresses void growth.
- **Thermocouple spread** — several probes are placed on and around the part and
  they don't read the same. A wide spread means some of the part isn't seeing
  the cycle the controller thinks it is.

---

## 🔄 How it works

```
Run log (CSV)
      │
      ▼
[1] Stage detection      →  split the run into ramp / soak / cool-down
      │
      ▼
[2] Rule engine          →  compare each stage to the spec
      │                     produces structured deviation records
      ▼
[3] LLM summary          →  turn those records into readable engineering notes
      │
      ▼
[4] Verification         →  confirm every deviation named in the summary
      │                     actually exists in the detection output
      ▼
[5] Grounded Q&A         →  answer questions, citing the spec clause used
```

The specification lives in a JSON file rather than in the code, because
different parts cure to different specs. The spec is input, not logic.

---

## ✅ What works today

The generator produces a complete cure run written to CSV, and can inject
deliberate faults.

| Component | Behaviour |
|---|---|
| Ramp | 70°F → 350°F at 3°F/min, snapping to the setpoint rather than overshooting |
| Soak | Held at 350°F for 120 minutes |
| Cool-down | 5°F/min to 150°F |
| Thermocouples | Three probes — one following the air with sensor noise, two with thermal lag at 85% and 70% response |
| Pressure | 85 psi through ramp and soak, then venting at 4 psi/min, clamped at zero |
| Vacuum | 25 inHg held throughout |
| Fault injection | Four parameter faults: slow ramp, fast ramp, short dwell, cold soak |
```
minute,air_temp_f,tc1_f,tc2_f,tc3_f,pressure_psi,vacuum_inhg
91,343.0,339.6,339.5,338.7,85.0,25.0
92,346.0,342.7,342.5,341.7,85.0,25.0
93,350.0,345.7,345.5,344.7,85.0,25.0
...
213,350.0,349.9,350.0,350.0,85.0,25.0
214,345.0,350.5,350.0,350.0,81.0,25.0
215,340.0,345.2,345.8,346.5,77.0,25.0
```

The probes lag behind the air on the way up and sit *above* it on the way down —
thermal mass works in both directions, and the same formula handles both without
a special case.

### Faults

Faults are injected at generation rather than patched into a finished file,
because a slow ramp doesn't just change values — it changes how long the run
*is*. At 1.5°F/min the ramp takes 186 minutes instead of 93, and every timestamp
after it shifts.

| Run | Ramp | Soak | Cool | Total |
|---|---|---|---|---|
| Nominal | 93 | 120 | 40 | 253 |
| Slow ramp (1.5°F/min) | 186 | 120 | 40 | 346 |
| Fast ramp (6°F/min) | 46 | 120 | 40 | 206 |
| Short dwell (60 min) | 93 | 60 | 40 | 193 |
| Cold soak (335°F) | 88 | 120 | 37 | 245 |

Cold soak shortens both the ramp and the cool-down, because the run climbs less
far and falls from lower.

Two decisions worth reading about in the [build log](BUILD_LOG.md): **why the
ramp snaps to the setpoint** instead of stepping past it, and **why pressure
vents gradually** rather than dropping instantly.

---

## 📋 Build stages

- [ ] **[1] Run generator** — *in progress.* Temperature, pressure, vacuum and
      three thermocouples with thermal lag are done, along with four parameter
      faults. Still to add: point-in-time faults (vacuum loss, pressure sag,
      sensor dropout), multi-run generation, and a ground-truth record of which
      fault went into which run.
- [ ] **[2] Spec format and loader** — JSON spec with validation that rejects a
      malformed spec loudly instead of producing wrong results quietly.
- [ ] **[3] Stage detection** — segment the actual run from the data, which gets
      harder once sensor noise is in there.
- [ ] **[4] Deviation detection** — one rule per requirement, each returning a
      structured result with severity and timestamps.
- [ ] **[5] Accuracy measurement** — run the full set, compare against ground
      truth, record detection rate and false positives, tune, record the numbers
      before and after.
- [ ] **[6] LLM summary** — with a prompt changelog showing what changed and why.
- [ ] **[7] Output verification** — the check described above.
- [ ] **[8] Grounded Q&A** — retrieval over the spec documents with citations.
- [ ] **[9] Interface and write-up.**

---

## 🔍 Why the verification step exists

A summary that invents a deviation is worse than no summary. It sends someone
looking for a problem that isn't there, and once that happens nobody trusts the
tool again.

This is the same lesson as the tie-out check in my [AR aging
analyzer](https://github.com/y-chaitanya/ar-aging-risk-analyzer). There, a
fixed-range formula understated reported exposure by $30,750 once the dataset
grew, and nothing on screen looked wrong. The fix wasn't to be more careful with
the formula — it was to make the sheet check its own arithmetic so that class of
error surfaces immediately.

Same idea here, applied to model output. The model is useful. It isn't
authoritative. Something has to check it.

---

## 📓 Notes on scope, so nothing here is oversold

- **The data is synthetic.** I generate the run logs myself. This is not real
  equipment data.
- **The spec parameters are illustrative**, taken from publicly available
  descriptions of composite cure processes. They aren't any manufacturer's
  actual specification. A real version would take real values from process
  engineering.
- **Nothing here has been validated against real equipment or a real quality
  process.** It demonstrates the approach, not a qualified system.
- **The thresholds and severity levels are my own judgment**, written down in the
  build log so they can be argued with.
- **Python is new to me.** I've written SQL, VBA and T-SQL before this. I'm
  learning Python by building this, and I note the places where that showed.

---

## ▶️ Running it

```bash
python3.12 -m venv venv
source venv/bin/activate
pip install pandas numpy matplotlib
python src/generate_run.py
```

Writes `data/run_001.csv`.

---

## 🛠️ Tech stack

Python 3.12 · pandas · numpy · matplotlib · Chroma · LLM API · Streamlit

---

## 📌 About

Part of a deliberate, hands-on return to technical work — documented end to end,
including the parts that didn't work first time.

Other projects:
[Water Utility Operations Database](https://github.com/y-chaitanya/water-utility-operations-database) ·
[AR Aging & Write-Off Risk Analyzer](https://github.com/y-chaitanya/ar-aging-risk-analyzer) ·
[CRM Member Retention Automation](https://github.com/y-chaitanya/crm-member-retention-automation)
