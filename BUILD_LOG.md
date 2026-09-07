# Build Log — Autoclave Cure Cycle Deviation Analyzer

A record of what I built, what broke, and what I decided — written as I go.

I'm keeping this for two reasons. It's how I remember what I learned. And when
someone asks me why the code does something a particular way, the answer should
be written down rather than reconstructed.

---

## Day 1 — 3 September 2026

### Setting up

**Python.** macOS ships with Python 3.9.6, from 2021. I installed 3.12.14
alongside it via Homebrew rather than replacing it, because macOS uses the system
Python for its own purposes and breaking that is a bad idea. Two Pythons now
coexist — `python3` is the system one, `python3.12` is mine.

**Virtual environment.** Created a venv inside the project. Everything I install
lives in that folder rather than in the system Python, so this project's package
versions can't collide with anything else's. Same isolation idea as the Docker
container I used for the SQL Server project — different mechanism, same reason.

The thing nobody warns you about: the environment turns off when you close
Terminal. Every session starts with `source venv/bin/activate`. Forget it and
your packages appear to have vanished.

**Packages.** pandas, numpy, matplotlib. Worth noting I'm on **pandas 3.x** —
most examples online are written for 2.x, so if something doesn't behave, a
version difference is a likely first suspect.

**`.gitignore` before the first commit.** Excluded `venv/`, `.env`, and Python
cache files. `venv` is thousands of files anyone can regenerate. `.env` will hold
an API key later, and a committed key in a public repo is a real security
incident — so I set the exclusion up before the key existed rather than after.

---

## Day 1 — the first working cycle

### What I built

`src/generate_run.py` — produces a synthetic cure run, one reading per minute.

**Why one reading per minute.** Real controllers sample faster, often every few
seconds. At one per second a six-hour run is over 21,000 rows, which is
impossible to eyeball while developing. One per minute gives ~250 rows for a
four-hour run: realistic in shape, small enough to read. The detection logic
reads timestamps, so the interval isn't baked into it.

**Structure.** Three stages:

| Stage | Mechanism | Result |
|---|---|---|
| Ramp up | `while` loop, +3°F/min from 70°F | 93 minutes |
| Soak | `for` loop, fixed 120 repeats | 120 minutes |
| Cool down | `while` loop, −5°F/min to 150°F | 40 minutes |

Total: **253 minutes.** That duration came out of the physics I specified, not
from me choosing it — which was the first moment the thing felt real.

`while` runs until a condition changes. `for ... in range(n)` runs exactly n
times. The soak is a fixed duration, so it's a `for`.

---

### The setpoint problem

**This is the one I want to remember.**

First version held the soak at **352°F** when the spec said 350.

**Why.** The ramp loop condition was `while temperature < SOAK_TEMP`. At minute
93 the temperature was 349. Is 349 less than 350? Yes — so the loop ran once
more, added 3, landed on 352, and *then* stopped. Every "good" run I generated
was already 2°F above spec.

Nothing errored. Nothing looked broken. The number was just wrong.

**That's the same shape as the SUMIF bug in my AR analyzer** — a silent error
inside a calculation that looks fine on screen. Different language, same failure
mode: the code did exactly what I told it, and what I told it was subtly wrong.

**Second attempt.** Changed the condition to check ahead before stepping:

```python
while temperature + RAMP_RATE <= SOAK_TEMP:
```

Now it held at **349** — undershooting by 1 instead of overshooting by 2.

**Why neither worked.** 350 − 70 = 280 degrees to climb. At 3°F per minute
that's 93.33 minutes. There is no minute at which a 3-degree step lands exactly
on 350. The step size doesn't divide evenly into the range, so any loop must
stop short or overshoot. No condition fixes that.

**What I settled on.** Keep the look-ahead condition, then snap to the setpoint
before the soak begins:

```python
temperature = SOAK_TEMP
```

**Not because it's easier — because it's what the equipment does.** A real
autoclave controller doesn't march in blind fixed steps and hold wherever it
lands. It ramps toward a setpoint and holds *at* the setpoint. The controller
knows what 350 is.

The generator should model the machine, not my loop.

**Also noted:** the ramp's final printed reading is the value at the last step
before the snap. Worth checking later that the transition row looks right, since
boundary rows are exactly where stage detection will be most fragile.

---

## Day 2 — 5 September 2026: Git, the hard way

Four separate problems in one morning. None of them Python.

### 1. Commit is not push

The repo on GitHub showed only `.gitignore` and `README.md` — no `src` folder.
I'd committed the generator the night before and assumed it was published.

`git commit` saves to the local repository. `git push` uploads it. Two steps.

Like writing a page in a notebook versus posting it. The notebook is safe either
way; nobody else sees it until you post.

`git status` said it plainly: *"Your branch is ahead of 'origin/main' by 1
commit."*

### 2. `fatal: bad object refs/heads/main 2`

Push failed with a branch reference called `main 2` — with a space and a "2".
That's macOS's file-duplication naming.

**Cause:** the project lived in `~/Documents`, which syncs to iCloud. iCloud
doesn't understand Git's internal files and duplicated one.

**Fix:** deleted the stray reference.

```bash
rm ".git/refs/heads/main 2"
```

**Real fix:** moved the project out of the synced folder entirely. This would
have kept happening, and next time it might corrupt something less recoverable.

### 3. Divergent branches

I had a local commit; GitHub had a commit from an edit I'd made in the browser.
Two histories from one starting point.

Git refused to reconcile them without being told how:

- **merge** — keep both timelines, add a commit that joins them
- **rebase** — replay my commit on top of theirs, one straight line

**Chose merge.** For a solo project the history is a record of how the work
actually happened, and rebase rewrites that. Tidiness isn't worth losing the
truth of the sequence.

```bash
git config pull.rebase false
git pull
```

### 4. Authentication

GitHub stopped accepting account passwords for Git operations in 2021. Needed a
personal access token with `repo` scope. The token is shown exactly once —
copy it immediately.

### 5. Moving the project broke the virtual environment

After relocating out of `~/Documents`, `python` stopped resolving —
`zsh: command not found`.

**Why.** A venv stores the absolute path it was created at. Move the project and
every internal reference points somewhere that no longer exists.

**Fix.** Delete it and rebuild:

```bash
deactivate
rm -rf venv
python3.12 -m venv venv
source venv/bin/activate
pip install pandas numpy matplotlib
```

Thirty seconds, and nothing was lost — the venv is only installed packages, which
is exactly why it's in `.gitignore` and never committed. It wouldn't work on
anyone else's machine anyway. Disposable by design.

---

---

## Day 3 — 6 September 2026: writing to a file

### CSV output

Replaced printing with writing to `data/run_001.csv`. The readings collect into a
list as the run proceeds; the whole thing is written at the end with a header
row. **253 rows.**

Printed output vanishes when you close Terminal. A file is something the rest of
the tool can actually read — this is the step where it stops being a script that
demonstrates and starts being a component.

### What I noticed at the ramp/soak boundary

Every ramp step is 3°F. Except the last one, which is 4°F:

```
91,343.0
92,346.0
93,350.0    ← 4-degree step
94,350.0
```

That's the snap-to-setpoint from Day 1. The loop stops at 346 because another
3-degree step would overshoot, then the temperature is set directly to 350.

**Why I'm writing this down.** Acceptable while the spec's maximum ramp rate is
5°F/min. But if I ever set a maximum below 4, my own generator would produce a
"good" run that my own detector flags as a violation — a false positive built
into the test data rather than into the detection logic.

The generator and the spec are coupled at this point. When accuracy numbers look
wrong in Stage 5, check upstream before assuming the detector is at fault.

---

## SCREENSHOTS — what to capture and when

Every claim in the README needs visual evidence. Capture at the moment something
first works, not at the end — by then you've moved on and the interesting state
is gone. Capture the failures too; those are what make a build log credible.

Naming: `NN_short-description.png`, numbered in build order.

| # | Filename | Status |
|---|---|---|
| 00 | `00_git-setup-and-first-run.png` | ✅ captured |
| 01 | `01_first-cure-cycle-output.png` | ✅ captured — correct 350 hold |
| 02 | `02_setpoint-overshoot-352.png` | ✅ captured — the bug |
| 02b | `02b_setpoint-undershoot-349.png` | ✅ captured — the failed fix |
| 03 | `03_csv-written.png` | ✅ captured |
| 04 | `04_run-log-csv-sample.png` | ✅ captured |
| 05 | `05_csv-ramp-to-soak-transition.png` | to do — the 4°F step |
| 06 | `06_multi-thermocouple-spread.png` | to do |
| 07 | `07_fault-injected-vacuum-loss.png` | to do |
| 08 | `08_ground-truth-file.png` | to do |
| 09 | `09_spec-validation-rejects-bad-spec.png` | to do |
| 10 | `10_stage-detection-segments.png` | to do |
| 11 | `11_deviation-output.png` | to do |
| 12 | `12_accuracy-before-tuning.png` | to do |
| 13 | `13_accuracy-after-tuning.png` | to do |
| 14 | `14_llm-summary-output.png` | to do |
| 15 | `15_verification-catches-mismatch.png` | to do |
| 16 | `16_rag-answer-with-citation.png` | to do |

**The two that matter most:** `02` and `15`. A screenshot of a bug found and
fixed is more persuasive than ten screenshots of things working. And the
verification step is the argument of the whole project — a picture of the system
catching its own model inventing a deviation *is* the thesis.

---

## Decisions log

Choices someone might reasonably question, and why I made them.

| Decision | Reason |
|---|---|
| One reading per minute | Realistic shape, readable while developing. Detection reads timestamps, so interval isn't baked in. |
| Snap to setpoint after ramp | Models what a real controller does — reaches target and holds. |
| Spec in JSON, not in code | Different parts cure to different specs. The spec is input, not logic. |
| Synthetic data | I don't have real run data. Better to say so than to imply otherwise. |
| Merge over rebase | The history is evidence of how the work happened. |
| Python 3.12 alongside 3.9 | Newer libraries need it; the system Python belongs to macOS. |

---

## Still to do

- [x] Write to CSV instead of printing
- [ ] Add pressure and vacuum columns
- [ ] Add three thermocouples with lag and sensor noise
- [ ] Fault injection + ground-truth file
- [ ] Spec loader with validation
- [ ] Stage detection from the data
- [ ] Deviation rules
- [ ] Accuracy measurement against ground truth
- [ ] LLM summary + verification
- [ ] Retrieval-grounded Q&A

---

## What I've noticed about myself so far

The bugs that worry me aren't the ones that crash. They're the ones where the
program runs happily and produces a number that's wrong — the 352 instead of
350, the SUMIF that understated exposure by $30,750. Nothing on screen looks
broken.

Which is why I keep ending up building the same thing: something that checks its
own output. It's the tie-out check in the AR tool, and it's the verification step
planned for the LLM summary here.

I don't think that's a coincidence. It might be the most useful instinct I have.
