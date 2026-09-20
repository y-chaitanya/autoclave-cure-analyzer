"""
Accuracy measurement.

Detection rules are opinions until they are measured. This module runs the
detector over the labelled run set and compares what it found against the
fault that was injected, so the rules can be tuned against numbers rather
than against how the output feels.

It also sweeps the persistence threshold, which is the open question the
build log recorded: how long a condition must hold before it counts as a
deviation. Too low and sensor noise produces deviations that never happened;
too high and genuine short excursions are missed.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from spec import load_spec                       # noqa: E402
from detect import load_run, analyze             # noqa: E402


# The codes each injected fault should produce. A fault may legitimately
# raise more than one: a cold soak means the part both missed temperature
# and never accumulated cure time, and both are true statements about it.
EXPECTED = {
    "none":         set(),
    "slow_ramp":    {"RAMP_RATE_LOW"},
    "fast_ramp":    {"RAMP_RATE_HIGH"},
    "short_dwell":  {"SOAK_DURATION_SHORT"},
    "cold_soak":    {"SOAK_TEMP_LOW", "SOAK_DURATION_SHORT"},
    "vacuum_loss":  {"VACUUM_LOSS"},
    "pressure_sag": {"PRESSURE_LOW"},
    "probe_lag":    {"TC_SPREAD_HIGH", "SOAK_TEMP_LOW"},
}


def evaluate(spec, truth, runs_dir, persistence=None):
    """Score the detector against ground truth. Returns per-run results."""
    results = []
    for run_id, t in truth.items():
        path = os.path.join(runs_dir, f"run_{run_id}.csv")
        analysis = analyze(load_run(path), spec, run_id, persistence=persistence)
        found = analysis.codes
        expected = EXPECTED[t["fault"]]

        results.append({
            "run_id": run_id,
            "fault": t["fault"],
            "expected": sorted(expected),
            "found": sorted(found),
            "detected": bool(expected & found) if expected else None,
            "false_positives": sorted(found - expected),
        })
    return results


def score(results):
    faulted = [r for r in results if r["fault"] != "none"]
    nominal = [r for r in results if r["fault"] == "none"]

    caught = sum(1 for r in faulted if r["detected"])
    fp_runs = sum(1 for r in results if r["false_positives"])
    fp_codes = sum(len(r["false_positives"]) for r in results)
    clean_nominal = sum(1 for r in nominal if not r["found"])

    return {
        "faulted_runs": len(faulted),
        "faults_detected": caught,
        "detection_rate": round(caught / len(faulted), 3) if faulted else None,
        "nominal_runs": len(nominal),
        "nominal_clean": clean_nominal,
        "runs_with_false_positives": fp_runs,
        "false_positive_codes": fp_codes,
    }


def sweep(spec, truth, runs_dir, values=range(1, 11)):
    """Measure detection and false positives across persistence thresholds."""
    table = []
    for p in values:
        s = score(evaluate(spec, truth, runs_dir, persistence=p))
        table.append({"persistence_min": p, **s})
    return table


def print_results(results, summary):
    print("=" * 74)
    print("  Detection accuracy against ground truth")
    print("=" * 74)
    for r in results:
        if r["fault"] == "none":
            verdict = "clean" if not r["found"] else "FALSE POSITIVE"
        else:
            verdict = "detected" if r["detected"] else "MISSED"
        print(f"  run_{r['run_id']}  {r['fault']:<14} {verdict}")
        if r["found"]:
            print(f"            found: {', '.join(r['found'])}")
        if r["false_positives"]:
            print(f"            unexpected: {', '.join(r['false_positives'])}")

    print("\n  " + "-" * 70)
    print(f"  Faults detected          {summary['faults_detected']} of "
          f"{summary['faulted_runs']}  "
          f"({summary['detection_rate']:.0%})")
    print(f"  Nominal runs clean       {summary['nominal_clean']} of "
          f"{summary['nominal_runs']}")
    print(f"  False positive codes     {summary['false_positive_codes']}")
    print()


def print_sweep(table):
    print("=" * 74)
    print("  Persistence threshold sweep")
    print("=" * 74)
    print(f"  {'minutes':>8}  {'detected':>10}  {'rate':>6}  "
          f"{'nominal clean':>14}  {'false pos':>10}")
    for row in table:
        print(f"  {row['persistence_min']:>8}  "
              f"{row['faults_detected']:>4} of {row['faulted_runs']:<3}  "
              f"{row['detection_rate']:>5.0%}  "
              f"{row['nominal_clean']:>6} of {row['nominal_runs']:<5}  "
              f"{row['false_positive_codes']:>10}")
    print()


def noise_study(spec, out_root="/tmp/noise_study",
                scales=(1, 2, 3, 4), persistences=(1, 3, 5)):
    """How the persistence threshold behaves as instrumentation degrades.

    Regenerates the labelled set at increasing sensor noise and scores each
    persistence threshold against it, so the value chosen in the spec rests
    on a measurement rather than a guess.
    """
    import shutil
    sys.path.insert(0, os.path.dirname(__file__))
    from generate_run import build_set

    rows = []
    for scale in scales:
        run_dir = os.path.join(out_root, f"noise_{scale}")
        truth_path = os.path.join(run_dir, "ground_truth.json")
        shutil.rmtree(run_dir, ignore_errors=True)
        truth = build_set(run_dir, truth_path, seed=7, noise_scale=scale)

        for p in persistences:
            s = score(evaluate(spec, truth, run_dir, persistence=p))
            rows.append({"noise_scale": scale, "persistence_min": p, **s})
    return rows


def print_noise_study(rows, persistences):
    print("=" * 74)
    print("  Persistence against sensor noise")
    print("=" * 74)
    print("  Sensor noise multiplied; false positive codes reported per setting.")
    print()
    header = "  noise  " + "".join(f"  persistence={p:<2}" for p in persistences)
    print(header)
    scales = sorted({r["noise_scale"] for r in rows})
    for scale in scales:
        cells = []
        for p in persistences:
            r = next(x for x in rows
                     if x["noise_scale"] == scale and x["persistence_min"] == p)
            cells.append(f"  {r['false_positive_codes']:>2} fp, "
                         f"{r['detection_rate']:>4.0%}")
        print(f"  {scale:>4}x  " + "".join(cells))
    print()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Measure detection accuracy.")
    ap.add_argument("--spec", default="data/cure_spec.json")
    ap.add_argument("--runs", default="data/runs")
    ap.add_argument("--truth", default="data/ground_truth.json")
    ap.add_argument("--persistence", type=int, default=None)
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--noise-study", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    spec = load_spec(args.spec)
    with open(args.truth) as fh:
        truth = json.load(fh)

    if args.noise_study:
        persistences = (1, 3, 5)
        rows = noise_study(spec, persistences=persistences)
        print(json.dumps(rows, indent=2)) if args.json else print_noise_study(rows, persistences)
        return 0

    if args.sweep:
        table = sweep(spec, truth, args.runs)
        print(json.dumps(table, indent=2)) if args.json else print_sweep(table)
        return 0

    results = evaluate(spec, truth, args.runs, persistence=args.persistence)
    summary = score(results)
    if args.json:
        print(json.dumps({"summary": summary, "runs": results}, indent=2))
    else:
        print_results(results, summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
