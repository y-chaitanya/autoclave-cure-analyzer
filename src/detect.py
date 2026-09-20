"""
Stage detection and deviation rules.

This module decides. Every conformance judgement in the project is made here,
from the run data and the specification, with no model involved. The summary
layer downstream explains these findings; it cannot produce or overturn them.

Two choices in here are worth arguing with, and both are recorded in the
build log:

  Rules evaluate part temperature, not air temperature. The controller reads
  the air, but the part is what cures. Soak duration is governed by the
  slowest probe, so a part that lagged behind the air is not credited with
  time it did not spend at temperature.

  A deviation must persist before it counts. Sensor noise puts individual
  readings across a threshold; treating each crossing as a deviation produces
  false positives. The persistence threshold lives in the spec and its value
  was chosen by measurement, not by feel.
"""

from dataclasses import dataclass, field, asdict
from typing import Optional
import csv


REQUIRED_COLUMNS = {"minute", "air_temp_f", "pressure_psi", "vacuum_inhg"}


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------

def load_run(path):
    """Read a run log into a list of dicts with numeric values."""
    with open(path) as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise ValueError(f"{path} contains no readings")

    missing = REQUIRED_COLUMNS - set(rows[0])
    if missing:
        raise ValueError(f"Run log is missing required columns: {sorted(missing)}")

    out = []
    for r in rows:
        out.append({k: (int(v) if k == "minute" else float(v)) for k, v in r.items()})
    out.sort(key=lambda r: r["minute"])

    minutes = [r["minute"] for r in out]
    if len(set(minutes)) != len(minutes):
        raise ValueError("Run log contains duplicate minute values")
    return out


def probe_channels(rows, spec):
    """Thermocouple channels named by the spec and present in the data."""
    present = [c for c in spec["thermocouples"]["channels"] if c in rows[0]]
    if not present:
        raise ValueError("Run log contains none of the specified thermocouple channels")
    return present


def part_temp(row, channels):
    """The part temperature at a reading: the coldest probe.

    The coldest probe governs because it represents the part of the laminate
    furthest through cure. A part is not cured until its coldest point is.
    """
    return min(row[c] for c in channels)


# --------------------------------------------------------------------------
# Findings
# --------------------------------------------------------------------------

@dataclass
class Finding:
    code: str
    passed: bool
    severity: str            # pass, minor, major
    parameter: str
    measured: Optional[float]
    limit: Optional[float]
    units: str
    detail: str
    window_min: Optional[tuple] = None

    def to_dict(self):
        return asdict(self)


@dataclass
class RunAnalysis:
    run_id: str
    spec_id: str
    conforming: bool
    stages: dict = field(default_factory=dict)
    findings: list = field(default_factory=list)
    metrics: dict = field(default_factory=dict)

    @property
    def deviations(self):
        return [f for f in self.findings if not f.passed]

    @property
    def codes(self):
        return {f.code for f in self.deviations}

    def to_dict(self):
        return {
            "run_id": self.run_id,
            "spec_id": self.spec_id,
            "conforming": self.conforming,
            "stages": self.stages,
            "metrics": self.metrics,
            "findings": [f.to_dict() for f in self.findings],
        }


# --------------------------------------------------------------------------
# Persistence
# --------------------------------------------------------------------------

def sustained_windows(flags, minutes, persistence):
    """Windows where a condition held for at least `persistence` readings.

    flags and minutes are parallel sequences. Returns a list of
    (start_minute, end_minute, indices) for each qualifying run.
    """
    windows, start = [], None
    for i, flag in enumerate(list(flags) + [False]):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            if i - start >= persistence:
                windows.append((minutes[start], minutes[i - 1], list(range(start, i))))
            start = None
    return windows


# --------------------------------------------------------------------------
# Stage detection
# --------------------------------------------------------------------------

def detect_stages(rows, spec, channels):
    """Split the run into ramp, soak, and cool-down from the data itself.

    The soak is found as the plateau the run actually held, not as the band
    the specification asked for. Segmenting against the spec looks correct
    until a run misses temperature: a cold soak never enters the specified
    band, the whole run collapses into one long ramp, and the cool-down is
    then read as a falling ramp and a pressure loss. Two rules fire that have
    nothing to do with the real fault.

    Detection describes what happened. The rules decide whether it was
    acceptable. Keeping those separate is what stops one fault from
    manufacturing others.
    """
    tol = spec["soak"]["tolerance_f"]
    air = [r["air_temp_f"] for r in rows]
    peak = max(air)

    # The plateau is the longest stretch the run held near its own maximum.
    near_peak = [a >= peak - tol for a in air]
    best_start, best_len, start = None, 0, None
    for i, flag in enumerate(near_peak + [False]):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            if i - start > best_len:
                best_start, best_len = start, i - start
            start = None

    if best_start is None:
        return {"ramp": list(range(len(rows))), "soak": [], "cool": []}

    first, last = best_start, best_start + best_len - 1
    return {
        "ramp": list(range(0, first)),
        "soak": list(range(first, last + 1)),
        "cool": list(range(last + 1, len(rows))),
    }


def _rate_series(rows, idx, key, window):
    """Change per minute in `key` across a rolling window, with its index."""
    out = []
    for j in range(window, len(idx)):
        a, b = rows[idx[j - window]], rows[idx[j]]
        dt = b["minute"] - a["minute"]
        if dt > 0:
            out.append((idx[j], (b[key] - a[key]) / dt))
    return out


# Thermocouple readings carry sensor noise. On a 3 F/min ramp, consecutive
# readings swing several degrees per minute on noise alone. The rate is
# measured across a window wide enough for the trend to exceed the noise.
RATE_WINDOW_MIN = 5


# --------------------------------------------------------------------------
# Rules
# --------------------------------------------------------------------------

def check_ramp(rows, spec, stages, channels, persistence):
    lo = spec["ramp"]["min_f_per_min"]
    hi = spec["ramp"]["max_f_per_min"]
    idx = stages["ramp"]
    out = []

    if len(idx) <= RATE_WINDOW_MIN:
        return [Finding("RAMP_NO_DATA", False, "major", "ramp rate", None, None,
                        "F/min", "No ramp stage was detected before the soak band.")]

    rates = _rate_series(rows, idx, "air_temp_f", RATE_WINDOW_MIN)
    minutes = [rows[i]["minute"] for i, _ in rates]
    values = [v for _, v in rates]

    fast = sustained_windows([v > hi for v in values], minutes, persistence)
    if fast:
        peak = max(v for v in values if v > hi)
        out.append(Finding(
            "RAMP_RATE_HIGH", False, "major", "ramp rate", round(peak, 2), hi, "F/min",
            f"Heat-up reached {peak:.2f} F/min against a {hi:.1f} F/min limit, "
            f"sustained across {len(fast)} window(s). A ramp above the limit "
            f"risks an exotherm, where the resin's own reaction heat runs ahead "
            f"of the controller.",
            (fast[0][0], fast[-1][1])))

    slow = sustained_windows([v < lo for v in values], minutes, persistence)
    if slow:
        least = min(v for v in values if v < lo)
        out.append(Finding(
            "RAMP_RATE_LOW", False, "minor", "ramp rate", round(least, 2), lo, "F/min",
            f"Heat-up fell to {least:.2f} F/min against a {lo:.1f} F/min minimum, "
            f"sustained across {len(slow)} window(s).",
            (slow[0][0], slow[-1][1])))

    if not out:
        mean = sum(values) / len(values)
        out.append(Finding(
            "RAMP_RATE", True, "pass", "ramp rate", round(mean, 2), hi, "F/min",
            f"Heat-up averaged {mean:.2f} F/min and stayed within the "
            f"{lo:.1f} to {hi:.1f} F/min band."))
    return out


def check_soak(rows, spec, stages, channels, persistence):
    target = spec["soak"]["target_f"]
    tol = spec["soak"]["tolerance_f"]
    required = spec["soak"]["min_duration_min"]
    idx = stages["soak"]
    out = []

    if not idx:
        peak = max(part_temp(r, channels) for r in rows)
        return [Finding(
            "SOAK_NOT_REACHED", False, "major", "soak temperature",
            round(peak, 1), target, "F",
            f"No soak plateau was detected. Part temperature peaked at "
            f"{peak:.1f} F against a {target:.0f} F setpoint.")]

    # Duration is credited on part temperature, not air temperature.
    at_temp = [i for i in idx if part_temp(rows[i], channels) >= target - tol]
    duration = float(len(at_temp))

    if duration < required:
        out.append(Finding(
            "SOAK_DURATION_SHORT", False, "major", "soak duration",
            duration, float(required), "min",
            f"Part temperature held within tolerance for {duration:.0f} minutes "
            f"against a {required} minute minimum, short by {required - duration:.0f} "
            f"minutes. Time spent below target does not count toward cure.",
            (rows[idx[0]]["minute"], rows[idx[-1]]["minute"])))
    else:
        out.append(Finding(
            "SOAK_DURATION", True, "pass", "soak duration",
            duration, float(required), "min",
            f"Part temperature held within tolerance for {duration:.0f} minutes "
            f"against a {required} minute minimum."))

    below = [i for i in idx if part_temp(rows[i], channels) < target - tol]
    if len(below) >= persistence:
        coldest = min(part_temp(rows[i], channels) for i in below)
        out.append(Finding(
            "SOAK_TEMP_LOW", False, "major", "soak temperature",
            round(coldest, 1), round(target - tol, 1), "F",
            f"Part temperature fell to {coldest:.1f} F during soak, below the "
            f"{target - tol:.0f} F tolerance band, across {len(below)} reading(s). "
            f"The resin may not fully cross-link at that temperature.",
            (rows[below[0]]["minute"], rows[below[-1]]["minute"])))
    else:
        mean = sum(part_temp(rows[i], channels) for i in idx) / len(idx)
        out.append(Finding(
            "SOAK_TEMP", True, "pass", "soak temperature",
            round(mean, 1), target, "F",
            f"Part temperature during soak averaged {mean:.1f} F, within "
            f"{tol:.0f} F of the {target:.0f} F setpoint."))
    return out


def check_pressure(rows, spec, stages, channels, persistence):
    lo = spec["pressure"]["min_psi"]
    hi = spec["pressure"]["max_psi"]
    idx = stages["ramp"] + stages["soak"]
    if not idx:
        return []

    minutes = [rows[i]["minute"] for i in idx]
    values = [rows[i]["pressure_psi"] for i in idx]

    low = sustained_windows([v < lo for v in values], minutes, persistence)
    if low:
        least = min(v for v in values if v < lo)
        return [Finding(
            "PRESSURE_LOW", False, "major", "autoclave pressure",
            round(least, 1), lo, "psi",
            f"Pressure fell to {least:.1f} psi against a {lo:.0f} psi minimum, "
            f"sustained from minute {low[0][0]:.0f} to {low[-1][1]:.0f}. "
            f"Pressure consolidates the plies and suppresses void growth.",
            (low[0][0], low[-1][1]))]

    high = sustained_windows([v > hi for v in values], minutes, persistence)
    if high:
        peak = max(values)
        return [Finding(
            "PRESSURE_HIGH", False, "minor", "autoclave pressure",
            round(peak, 1), hi, "psi",
            f"Pressure reached {peak:.1f} psi against a {hi:.0f} psi maximum.",
            (high[0][0], high[-1][1]))]

    return [Finding(
        "PRESSURE", True, "pass", "autoclave pressure",
        round(min(values), 1), lo, "psi",
        f"Pressure held between {min(values):.1f} and {max(values):.1f} psi "
        f"through ramp and soak, inside the {lo:.0f} to {hi:.0f} psi band.")]


def check_vacuum(rows, spec, stages, channels, persistence):
    required = spec["vacuum"]["min_inhg"]
    idx = stages["ramp"] + stages["soak"]
    if not idx:
        return []

    minutes = [rows[i]["minute"] for i in idx]
    values = [rows[i]["vacuum_inhg"] for i in idx]

    lost = sustained_windows([v < required for v in values], minutes, persistence)
    if lost:
        least = min(values)
        return [Finding(
            "VACUUM_LOSS", False, "major", "bag vacuum",
            round(least, 1), required, "inHg",
            f"Bag vacuum fell to {least:.1f} inHg against a {required:.0f} inHg "
            f"minimum, from minute {lost[0][0]:.0f} to {lost[-1][1]:.0f}. Vacuum "
            f"draws air and volatiles out of the laminate; a leak can leave voids.",
            (lost[0][0], lost[-1][1]))]

    return [Finding(
        "VACUUM", True, "pass", "bag vacuum",
        round(min(values), 1), required, "inHg",
        f"Bag vacuum held at or above {min(values):.1f} inHg through ramp and soak.")]


def check_cooldown(rows, spec, stages, channels, persistence):
    limit = spec["cooldown"]["max_f_per_min"]
    idx = stages["cool"]
    if len(idx) <= RATE_WINDOW_MIN:
        return []

    rates = _rate_series(rows, idx, "air_temp_f", RATE_WINDOW_MIN)
    minutes = [rows[i]["minute"] for i, _ in rates]
    values = [-v for _, v in rates]

    fast = sustained_windows([v > limit for v in values], minutes, persistence)
    if fast:
        peak = max(values)
        return [Finding(
            "COOLDOWN_RATE_HIGH", False, "major", "cooldown rate",
            round(peak, 2), limit, "F/min",
            f"Cooldown reached {peak:.2f} F/min against a {limit:.1f} F/min limit, "
            f"sustained from minute {fast[0][0]:.0f} to {fast[-1][1]:.0f}.",
            (fast[0][0], fast[-1][1]))]

    return [Finding(
        "COOLDOWN_RATE", True, "pass", "cooldown rate",
        round(max(values), 2), limit, "F/min",
        f"Cooldown peaked at {max(values):.2f} F/min, within the "
        f"{limit:.1f} F/min limit.")]


def check_tc_spread(rows, spec, stages, channels, persistence):
    limit = spec["thermocouples"]["max_spread_f"]
    if len(channels) < 2:
        return []

    idx = stages["ramp"] + stages["soak"]
    minutes = [rows[i]["minute"] for i in idx]
    spreads = [max(rows[i][c] for c in channels) - min(rows[i][c] for c in channels)
               for i in idx]

    wide = sustained_windows([s > limit for s in spreads], minutes, persistence)
    if wide:
        peak = max(spreads)
        return [Finding(
            "TC_SPREAD_HIGH", False, "major", "thermocouple spread",
            round(peak, 1), limit, "F",
            f"Probes diverged by up to {peak:.1f} F against a {limit:.0f} F limit, "
            f"sustained from minute {wide[0][0]:.0f} to {wide[-1][1]:.0f}. A wide "
            f"spread means part of the laminate is not seeing the cycle the "
            f"controller believes it is.",
            (wide[0][0], wide[-1][1]))]

    return [Finding(
        "TC_SPREAD", True, "pass", "thermocouple spread",
        round(max(spreads), 1), limit, "F",
        f"Probe spread peaked at {max(spreads):.1f} F, within the {limit:.0f} F limit.")]


RULES = [check_ramp, check_soak, check_pressure,
         check_vacuum, check_cooldown, check_tc_spread]


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def analyze(rows, spec, run_id, persistence=None):
    channels = probe_channels(rows, spec)
    stages = detect_stages(rows, spec, channels)
    if persistence is None:
        persistence = spec.get("detection", {}).get("min_persistence_min", 3)

    findings = []
    for rule in RULES:
        findings += rule(rows, spec, stages, channels, persistence)

    soak_idx = stages["soak"]
    target = spec["soak"]["target_f"]
    tol = spec["soak"]["tolerance_f"]

    # Metrics are scoped the way the rules are scoped. Reporting minimum
    # pressure across the whole run would report the vented value at the end
    # of cool-down, which is not what the pressure rule evaluates, and a
    # summary quoting it would read as a contradiction of the finding.
    cure_idx = stages["ramp"] + stages["soak"]
    cure = [rows[i] for i in cure_idx] or rows

    metrics = {
        "total_duration_min": rows[-1]["minute"],
        "readings": len(rows),
        "peak_air_temp_f": round(max(r["air_temp_f"] for r in rows), 1),
        "peak_part_temp_f": round(max(part_temp(r, channels) for r in rows), 1),
        "soak_minutes_at_temp": len([i for i in soak_idx
                                     if part_temp(rows[i], channels) >= target - tol]),
        "min_pressure_psi_in_cure": round(min(r["pressure_psi"] for r in cure), 1),
        "min_vacuum_inhg_in_cure": round(min(r["vacuum_inhg"] for r in cure), 1),
        "max_tc_spread_f_in_cure": round(max(
            max(r[c] for c in channels) - min(r[c] for c in channels) for r in cure), 1),
        "persistence_min": persistence,
    }

    stage_summary = {
        name: {"start_min": rows[i[0]]["minute"], "end_min": rows[i[-1]]["minute"],
               "readings": len(i)} if i else None
        for name, i in stages.items()
    }

    return RunAnalysis(
        run_id=run_id,
        spec_id=spec["spec_id"],
        conforming=all(f.passed for f in findings),
        stages=stage_summary,
        findings=findings,
        metrics=metrics,
    )
