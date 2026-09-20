"""
Tests for the detector, the specification loader, and verification.

Each labelled run carries a known injected fault, so these confirm the
detector flags what it should and stays quiet on a nominal run.

    python -m pytest tests/ -v
"""

import json
import os
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "src"))

from spec import load_spec, validate, SpecError               # noqa: E402
from detect import (load_run, analyze, detect_stages,          # noqa: E402
                    probe_channels, sustained_windows)
from summarize import TemplateWriter, facts_for_summary        # noqa: E402
from verify import verify, supported_values                    # noqa: E402
from evaluate import evaluate, score, EXPECTED                 # noqa: E402

DATA = os.path.join(ROOT, "data")
RUNS = os.path.join(DATA, "runs")


@pytest.fixture(scope="module")
def spec():
    return load_spec(os.path.join(DATA, "cure_spec.json"))


@pytest.fixture(scope="module")
def truth():
    with open(os.path.join(DATA, "ground_truth.json")) as fh:
        return json.load(fh)


def analysis_for(run_id, spec):
    return analyze(load_run(os.path.join(RUNS, f"run_{run_id}.csv")), spec, run_id)


# --------------------------------------------------------------------------
# Specification
# --------------------------------------------------------------------------

def test_spec_loads(spec):
    assert spec["spec_id"] == "CS-350-2A"


def test_spec_missing_section_is_rejected():
    with pytest.raises(SpecError, match="missing the 'ramp' section"):
        validate({"spec_id": "X"})


def test_spec_with_inverted_ramp_band_is_rejected(spec):
    broken = json.loads(json.dumps(spec))
    broken["ramp"]["min_f_per_min"] = 9.0
    with pytest.raises(SpecError, match="not below the maximum"):
        validate(broken)


# --------------------------------------------------------------------------
# Detection
# --------------------------------------------------------------------------

def test_every_fault_is_detected(spec, truth):
    results = evaluate(spec, truth, RUNS)
    s = score(results)
    assert s["detection_rate"] == 1.0, [r for r in results
                                        if r["detected"] is False]


def test_no_false_positives_on_nominal_runs(spec, truth):
    s = score(evaluate(spec, truth, RUNS))
    assert s["false_positive_codes"] == 0
    assert s["nominal_clean"] == s["nominal_runs"]


def test_expected_codes_cover_every_fault(truth):
    faults = {t["fault"] for t in truth.values()}
    assert faults <= set(EXPECTED), faults - set(EXPECTED)


def test_stages_are_ordered(spec):
    rows = load_run(os.path.join(RUNS, "run_1001.csv"))
    stages = detect_stages(rows, spec, probe_channels(rows, spec))
    assert stages["ramp"] and stages["soak"] and stages["cool"]
    assert max(stages["ramp"]) < min(stages["soak"])
    assert max(stages["soak"]) < min(stages["cool"])


def test_cold_soak_does_not_manufacture_extra_faults(spec):
    """A plateau below setpoint must not collapse the run into one ramp."""
    a = analysis_for("1005", spec)
    assert a.stages["soak"] is not None
    assert "PRESSURE_LOW" not in a.codes
    assert "RAMP_RATE_LOW" not in a.codes


def test_credited_soak_never_exceeds_the_plateau(spec, truth):
    """Time at temperature is credited on the part, so it cannot exceed the
    plateau the air actually held."""
    for run_id in truth:
        a = analysis_for(run_id, spec)
        soak = a.stages["soak"]
        if soak:
            assert a.metrics["soak_minutes_at_temp"] <= soak["readings"]


def test_air_holds_longer_than_the_minimum_so_the_part_catches_up(spec):
    """The part is cured when the part reaches temperature, not when the air
    does, so a conforming run holds the air past the specified minimum."""
    a = analysis_for("1001", spec)
    required = spec["soak"]["min_duration_min"]
    assert a.metrics["soak_minutes_at_temp"] >= required
    assert a.stages["soak"]["readings"] > required


def test_a_slow_probe_lengthens_the_run(spec, truth):
    """A probe at 15 percent response takes longer to reach temperature, so
    the controller holds the soak longer to credit the part its full time."""
    nominal = next(r for r, t in truth.items() if t["fault"] == "none")
    lagged = next(r for r, t in truth.items() if t["fault"] == "probe_lag")
    assert truth[lagged]["total_minutes"] > truth[nominal]["total_minutes"]


def test_persistence_suppresses_brief_crossings():
    minutes = list(range(10))
    flags = [False, True, False, True, True, True, True, False, False, False]
    assert sustained_windows(flags, minutes, 1)
    assert len(sustained_windows(flags, minutes, 3)) == 1
    assert sustained_windows(flags, minutes, 6) == []


def test_missing_columns_are_rejected(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("minute,air_temp_f\n0,70.0\n1,73.0\n")
    with pytest.raises(ValueError, match="missing required columns"):
        load_run(str(bad))


def test_every_finding_carries_detail_and_severity(spec, truth):
    for run_id in truth:
        for f in analysis_for(run_id, spec).findings:
            assert f.detail
            assert f.severity in {"pass", "minor", "major"}


# --------------------------------------------------------------------------
# Summary and verification
# --------------------------------------------------------------------------

def test_template_summaries_verify_clean(spec, truth):
    for run_id in truth:
        a = analysis_for(run_id, spec)
        text = TemplateWriter().write(facts_for_summary(a))
        ok, claims = verify(text, a)
        assert ok, f"run {run_id} produced unsupported claims"
        assert claims


def test_fabricated_number_is_caught(spec):
    a = analysis_for("1004", spec)
    text = TemplateWriter().write(facts_for_summary(a))
    ok, claims = verify(text + " Vacuum reached 3.7 inHg.", a)
    assert not ok
    assert any(c.value == 3.7 and not c.supported for c in claims)


def test_rounding_is_not_treated_as_fabrication(spec):
    a = analysis_for("1001", spec)
    peak = a.metrics["peak_part_temp_f"]
    ok, _ = verify(f"Part temperature peaked at {peak:.1f} F.", a)
    assert ok


def test_writer_receives_findings_not_run_data(spec):
    facts = facts_for_summary(analysis_for("1004", spec))
    assert set(facts) == {"run_id", "spec_id", "conforming",
                          "stages", "metrics", "deviations", "passed"}


def test_shortfall_figure_verifies(spec):
    """A writer may say "short by 60 minutes"; that figure must trace."""
    a = analysis_for("1004", spec)
    f = next(f for f in a.deviations if f.code == "SOAK_DURATION_SHORT")
    gap = round(abs(f.measured - f.limit), 2)
    assert any(abs(gap - v) < 0.01 for v in supported_values(a))
