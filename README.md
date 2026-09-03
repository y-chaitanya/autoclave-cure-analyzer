# 🔥 Autoclave Cure Cycle Deviation Analyzer

A tool that reads autoclave cure run logs, checks them against a cure
specification, flags every deviation, and writes an engineering summary — with a
verification step that confirms the summary only reports what the data actually
shows.

Not a chatbot demo and not a wrapper around an API — a rule-based detection
engine with a language model layered on top for the part language models are
actually good at, and a check on that model because it can be wrong.

> ⚠️ **Status: in development.** Started 3 September 2026. This README describes
> what is being built. Completed stages are ticked and evidenced with
> screenshots; everything else is marked planned. Nothing is claimed here that
> isn't working yet.

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
different parts cure to different specs. The tool takes the spec as input.

---

## 📋 Build stages

- [ ] **[1] Run generator** — synthetic multi-hour logs with temperature,
      pressure, vacuum and multiple thermocouples, plus deliberate fault
      injection (slow ramp, fast ramp, cold soak, short dwell, vacuum loss,
      pressure sag, sensor dropout) and a ground-truth record of what went into
      which run.
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

This is the same lesson as the tie-out check in my
[AR aging analyzer](https://github.com/y-chaitanya/ar-aging-risk-analyzer).
There, a fixed-range formula understated reported exposure by $30,750 once the
dataset grew, and nothing on screen looked wrong. The fix wasn't to be more
careful with the formula — it was to make the sheet check its own arithmetic so
that class of error surfaces immediately.

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
- **The thresholds and severity levels are my own judgment**, written down so
  they can be argued with.
- **Python is new to me.** I've written SQL, VBA and T-SQL before this. I'm
  learning Python by building this, and I'll note the places where that showed.

---

## 🛠️ Tech stack

Python 3.12 · pandas · numpy · matplotlib · Chroma · LLM API · Streamlit

---

## 📌 About

Part of a deliberate, hands-on return to technical work — documented end to end,
including the parts that didn't work first time.

Other projects:
[Water Utility Operations Database](https://github.com/y-chaitanya/water-utility-operations-database) ·
[AR Aging & Write-Off Risk Analyzer](https://github.com/y-chaitanya/ar-aging-risk-analyzer)