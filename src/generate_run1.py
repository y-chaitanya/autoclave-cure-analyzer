"""
Cure run generator.

Builds a complete autoclave cure run and writes it to CSV. Faults are
injected at generation rather than patched into a finished run, because a
slow ramp does not merely change values, it changes how long the run is and
shifts every timestamp after it.

Each generated run is accompanied by a ground truth record naming the fault
that went into it, which is what makes measured detection accuracy possible.
"""

import argparse
import json
import os
import random

# Nominal cycle -----------------------------------------------------------
START_TEMP_F = 70.0
SOAK_TEMP_F = 350.0
RAMP_RATE_F = 3.0
SOAK_MINUTES = 120
COOL_RATE_F = 5.0
COOL_FLOOR_F = 150.0

PRESSURE_PSI = 85.0
VENT_RATE_PSI = 4.0
VACUUM_INHG = 25.0

# Thermocouple response. Each probe closes this fraction of the gap between
# itself and the air each minute. tc1 tracks the air closely; tc2 and tc3 lag.
TC_RESPONSE = {"tc1": 1.00, "tc2": 0.85, "tc3": 0.70}
TC1_NOISE_F = 0.6
AIR_NOISE_F = 0.5

FAULTS = {
    "none":          "Nominal run, no fault injected",
    "slow_ramp":     "Heat-up at 1.5 F/min against a 3.0 F/min schedule",
    "fast_ramp":     "Heat-up at 6.0 F/min, risking exotherm",
    "short_dwell":   "Soak held 60 minutes against a 120 minute minimum",
    "cold_soak":     "Soak held at 335 F, 15 F below setpoint",
    "vacuum_loss":   "Bag vacuum decays mid-run from a developing leak",
    "pressure_sag":  "Autoclave pressure sags during soak",
    "probe_lag":     "One probe responds at 15 percent, indicating poor thermal contact",
}


def _params(fault):
    """Cycle parameters for a given fault."""
    p = {
        "ramp_rate": RAMP_RATE_F,
        "soak_temp": SOAK_TEMP_F,
        "soak_minutes": SOAK_MINUTES,
        "tc_response": dict(TC_RESPONSE),
    }
    if fault == "slow_ramp":
        p["ramp_rate"] = 1.5
    elif fault == "fast_ramp":
        p["ramp_rate"] = 6.0
    elif fault == "short_dwell":
        p["soak_minutes"] = 60
    elif fault == "cold_soak":
        p["soak_temp"] = 335.0
    elif fault == "probe_lag":
        p["tc_response"]["tc3"] = 0.15
    return p


def generate(fault="none", seed=None, noise_scale=1.0):
    """Build one run. Returns (rows, truth).

    noise_scale multiplies sensor noise, so the accuracy harness can measure
    how the rules behave as instrumentation degrades.
    """
    if fault not in FAULTS:
        raise ValueError(f"Unknown fault {fault!r}. Known: {sorted(FAULTS)}")

    rng = random.Random(seed)
    p = _params(fault)
    probes = {k: START_TEMP_F for k in TC_RESPONSE}

    rows = []
    minute = 0
    air = START_TEMP_F
    pressure = PRESSURE_PSI
    vacuum = VACUUM_INHG

    def record():
        rows.append({
            "minute": minute,
            "air_temp_f": round(air + rng.gauss(0, AIR_NOISE_F * noise_scale), 1),
            "tc1_f": round(probes["tc1"] + rng.gauss(0, TC1_NOISE_F * noise_scale), 1),
            "tc2_f": round(probes["tc2"], 1),
            "tc3_f": round(probes["tc3"], 1),
            "pressure_psi": round(pressure, 1),
            "vacuum_inhg": round(vacuum, 1),
        })

    def advance_probes():
        for name, response in p["tc_response"].items():
            probes[name] += (air - probes[name]) * response

    # -- ramp --------------------------------------------------------------
    # Look ahead before stepping, then snap to the setpoint. The step size
    # does not divide evenly into the range, so any loop either overshoots or
    # stops short. A real controller ramps toward a setpoint and holds there,
    # so the generator does the same.
    while air + p["ramp_rate"] <= p["soak_temp"]:
        record()
        air += p["ramp_rate"]
        advance_probes()
        minute += 1
    air = p["soak_temp"]
    ramp_end = minute

    # -- soak --------------------------------------------------------------
    # The soak is held until the slowest probe has been at temperature for the
    # required time, not until the air has. The part is cured when the part
    # reaches temperature, which is why soak time is specified as a minimum.
    slowest = min(p["tc_response"], key=p["tc_response"].get)
    band_lo = p["soak_temp"] - 5.0
    part_at_temp = 0

    while part_at_temp < p["soak_minutes"]:
        record()
        advance_probes()
        minute += 1
        if probes[slowest] >= band_lo:
            part_at_temp += 1
        if minute - ramp_end > p["soak_minutes"] + 60:
            break           # guard against a probe that never arrives
    soak_end = minute

    # -- cool-down ---------------------------------------------------------
    # Pressure vents gradually rather than dropping to zero. An instant drop
    # is a cliff edge that makes every pressure rule trivially satisfiable;
    # a gradual vent leaves a genuine question about when the cure ends, which
    # is the part stage detection has to resolve.
    while air > COOL_FLOOR_F:
        record()
        air = max(COOL_FLOOR_F, air - COOL_RATE_F)
        pressure = max(0.0, pressure - VENT_RATE_PSI)
        advance_probes()
        minute += 1
    record()

    # -- point-in-time faults ---------------------------------------------
    # These change one column and leave the timeline intact, so they are
    # applied to the finished rows rather than built into the loops.
    fault_window = None
    if fault == "vacuum_loss":
        start = ramp_end // 2
        for i, r in enumerate(rows):
            if start <= r["minute"] <= soak_end:
                decay = min(14.0, (r["minute"] - start) * 0.6)
                r["vacuum_inhg"] = round(VACUUM_INHG - decay, 1)
        fault_window = (start, soak_end)
    elif fault == "pressure_sag":
        start = ramp_end + 20
        end = min(start + 45, soak_end)
        for r in rows:
            if start <= r["minute"] <= end:
                r["pressure_psi"] = 62.0
        fault_window = (start, end)

    truth = {
        "fault": fault,
        "description": FAULTS[fault],
        "seed": seed,
        "noise_scale": noise_scale,
        "ramp_end_min": ramp_end,
        "soak_end_min": soak_end,
        "total_minutes": rows[-1]["minute"],
        "fault_window_min": fault_window,
    }
    return rows, truth


def write_run(rows, truth, out_dir, run_id):
    import csv
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"run_{run_id}.csv")
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path


def build_set(out_dir="data/runs", manifest_path="data/ground_truth.json",
              seed=7, noise_scale=1.0):
    """Generate one run per fault plus extra nominal runs, with ground truth."""
    manifest = {}
    plan = list(FAULTS) + ["none"] * 3
    for i, fault in enumerate(plan, start=1):
        run_id = f"{1000 + i}"
        rows, truth = generate(fault, seed=seed + i, noise_scale=noise_scale)
        write_run(rows, truth, out_dir, run_id)
        manifest[run_id] = truth

    os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
    with open(manifest_path, "w") as fh:
        json.dump(manifest, fh, indent=2)
    return manifest


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Generate autoclave cure run logs.")
    ap.add_argument("--fault", default=None, choices=sorted(FAULTS),
                    help="generate a single run with this fault")
    ap.add_argument("--all", action="store_true",
                    help="generate the full labelled set with ground truth")
    ap.add_argument("--out", default="data/runs")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    if args.all or args.fault is None:
        m = build_set(args.out, seed=args.seed)
        print(f"Wrote {len(m)} runs to {args.out} with ground truth.")
        for rid, t in m.items():
            print(f"  run_{rid}  {t['fault']:<14} {t['total_minutes']:>4} min")
    else:
        rows, truth = generate(args.fault, seed=args.seed)
        path = write_run(rows, truth, args.out, "001")
        print(f"Wrote {path}: {truth['fault']}, {truth['total_minutes']} minutes")
