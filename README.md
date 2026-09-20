# 🔥 Autoclave Cure Cycle Deviation Analyzer

A tool that reads autoclave cure run logs, checks them against a cure
specification, flags every deviation, and writes an engineering summary — with a
verification step that confirms the summary only reports what the data actually
shows.

Not a chatbot demo and not a wrapper around an API — a rule-based detection
engine with a language model layered on top for the part language models are
actually good at, and a check on that model because it can be wrong.

> ✅ **Status: stages 1 to 7 working and tested.** Started 3 September 2026.
> Completed stages are ticked below and evidenced with screenshots; stages 8 and
> 9 are marked planned. Nothing is claimed here that isn't running.

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
      │                     from the data, not from the spec
      ▼
[2] Rule engine          →  compare each stage to the spec
      │                     produces structured deviation records
      ▼
[3] Accuracy measurement →  score against injected ground truth
      │                     detection rate and false positives
      ▼
[4] LLM summary          →  turn those records into readable engineering notes
      │
      ▼
[5] Verification         →  confirm every figure in the summary traces back
      │                     to the detection output, or withhold it
      ▼
[6] Grounded Q&A         →  answer questions, citing the spec clause used
                            (planned)
```

The specification lives in a JSON file rather than in the code, because
different parts cure to different specs. The spec is input, not logic.

### What the output looks like

The detector segments the run, applies each rule, and reports findings with the
window where the condition held.

![Deviation report for a short-dwell run](screenshots/08_stage-detection-and-findings.png)

The summary is then written from those findings and checked before it is shown.

![Verified engineering summary](screenshots/09_verified-engineering-summary.png)

---

## ✅ What works today

### The generator

Produces a complete cure run written to CSV, with faults injected at generation
and a ground truth record of which fault went into which run.

| Component | Behaviour |
|---|---|
| Ramp | 70°F → 350°F at 3°F/min, snapping to the setpoint rather than overshooting |
| Soak | Held until the slowest probe has been at temperature for 120 minutes |
| Cool-down | 5°F/min to 150°F |
| Thermocouples | Three probes — one following the air with sensor noise, two with thermal lag at 85% and 70% response |
| Pressure | 85 psi through ramp and soak, then venting at 4 psi/min, clamped at zero |
| Vacuum | 25 inHg held throughout |
| Fault injection | Eight: nominal, slow ramp, fast ramp, short dwell, cold soak, vacuum loss, pressure sag, probe lag |
| Ground truth | Every run labelled with the fault that produced it |

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

![Thermocouple lag during ramp](screenshots/06_multi-thermocouple-lag-ramp.png)

![Thermocouples sitting above the air during cool-down](screenshots/07_thermocouple-lag-cooldown.png)

### Faults

Parameter faults are built in from the start rather than patched into a finished
file, because a slow ramp doesn't just change values — it changes how long the
run *is*, and every timestamp after it shifts.

| Run | Ramp | Soak | Cool | Total |
|---|---|---|---|---|
| Nominal | 91 | 124 | 39 | 253 |
| Slow ramp (1.5°F/min) | 181 | 127 | 39 | 346 |
| Fast ramp (6°F/min) | 46 | 122 | 39 | 206 |
| Short dwell (60 min) | 91 | 64 | 39 | 193 |
| Cold soak (335°F) | 86 | 124 | 36 | 245 |
| Probe lag (15% response) | 91 | 131 | 39 | 260 |

Readings per **detected** stage. The soak column varies by a few readings
between runs because the plateau is found in noisy data rather than read off the
schedule, and it runs longer than 120 because the controller holds until the
slowest probe has had its time.

Cold soak shortens both the ramp and the cool-down, because the run climbs less
far and falls from lower. Probe lag lengthens the soak, because the controller
waits for the laggard.

### Detection

Eight rules, each returning a structured finding with measured value, limit,
severity, and the window where the condition held.

| Code | Checks |
|---|---|
| `RAMP_RATE_HIGH` / `RAMP_RATE_LOW` | Heat-up rate against the specified band |
| `SOAK_DURATION_SHORT` | Time the **part** held at temperature against the minimum |
| `SOAK_TEMP_LOW` | Part temperature below the tolerance band during soak |
| `SOAK_NOT_REACHED` | No soak plateau detected |
| `PRESSURE_LOW` / `PRESSURE_HIGH` | Autoclave pressure through ramp and soak |
| `VACUUM_LOSS` | Bag vacuum before the cure completes |
| `COOLDOWN_RATE_HIGH` | Cool-down rate against the limit |
| `TC_SPREAD_HIGH` | Divergence between probes |

### Measured accuracy

```
Faults detected          7 of 7  (100%)
Nominal runs clean       4 of 4
False positive codes     0
```

![Detection accuracy and the persistence study](screenshots/10_detection-accuracy-and-persistence.png)

The second table answers a question the build log left open: how long a
condition must persist before it counts as a deviation. At nominal noise it
makes no difference. At three times nominal, persistence of 1 produces five
false positives and persistence of 3 produces one, with detection unchanged. So
the spec uses **3**, and the reason is a measurement rather than a feel.

---

## 📋 Build stages

- [x] **[1] Run generator** — temperature, pressure, vacuum, three thermocouples
      with thermal lag, eight faults including point-in-time faults, multi-run
      generation, and a ground-truth record of which fault went into which run.
- [x] **[2] Spec format and loader** — JSON spec with validation that rejects a
      malformed spec loudly instead of producing wrong results quietly.
- [x] **[3] Stage detection** — segment the actual run from the data, which gets
      harder once sensor noise is in there.
- [x] **[4] Deviation detection** — one rule per requirement, each returning a
      structured result with severity and timestamps.
- [x] **[5] Accuracy measurement** — run the full set, compare against ground
      truth, record detection rate and false positives, tune the persistence
      threshold, record the numbers.
- [x] **[6] LLM summary** — a deterministic template writer and a language model
      writer behind one interface, so the pipeline runs with or without an API key.
- [x] **[7] Output verification** — the check described below.
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

**In practice**, every number in the summary is traced back to the detector's
output. Below, a sentence claiming a vacuum loss was appended to a run where
vacuum held at 25.0 inHg throughout:

![The verifier rejecting a fabricated deviation](screenshots/11_verification-catches-fabrication.png)

The whole summary is withheld rather than the bad sentence struck. If one figure
can't be traced, there's no reason to trust the reasoning around it, and a
partially corrected document is more dangerous than none because it looks
reviewed. The fallback isn't silence — it's the detector's findings, which were
never in doubt.

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
- **Accuracy is measured against my own injected faults**, which is the easier
  test. A real log contains conditions I haven't thought to generate, and the
  noise model is Gaussian because that was easy, not because I measured real
  thermocouple behaviour.
- **The thresholds and severity levels are my own judgment**, written down in the
  build log so they can be argued with.
- **Python is new to me.** I've written SQL, VBA and T-SQL before this. I'm
  learning Python by building this, and I note the places where that showed.

---

## ▶️ Running it

```bash
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

python src/generate_run.py --all        # labelled run set with ground truth
python src/main.py data/runs/run_1004.csv
python src/evaluate.py                  # detection accuracy
python src/evaluate.py --noise-study    # persistence against sensor noise
python -m pytest tests/ -v              # 19 tests
```

Exit code is 0 for a conforming run and 1 when deviations are recorded, so the
tool can gate a batch process.

![19 tests passing](screenshots/12_tests-passing.png)

The language model writer is optional. Without an API key the project runs end
to end on the deterministic template writer, and the verifier behaves identically
either way.

```bash
pip install anthropic
export ANTHROPIC_API_KEY=...
```

---

## 🛠️ Tech stack

Python 3.12 · pytest · optional Anthropic API for the language model writer.

The generator, detector and verifier use the standard library only, so the core
runs anywhere. Planned for stage 8: Chroma for retrieval, Streamlit for the
interface.

---

## 📌 About

Part of a deliberate, hands-on return to technical work — documented end to end,
including the parts that didn't work first time.

Other projects:
[Water Utility Operations Database](https://github.com/y-chaitanya/water-utility-operations-database) ·
[AR Aging & Write-Off Risk Analyzer](https://github.com/y-chaitanya/ar-aging-risk-analyzer) ·
[Enterprise CRM Workflow Automation](https://github.com/y-chaitanya/enterprise-crm-workflow-automation-sandbox) ·
[Construction ERP Job Costing](https://github.com/y-chaitanya/construction-erp-jobcosting-sandbox) ·
[Financial Close Controls Engine](https://github.com/y-chaitanya/financial-close-engine) ·
[Ops Data Pipeline & Workflow Automation](https://github.com/y-chaitanya/ops-data-pipeline-workflow-automation)
