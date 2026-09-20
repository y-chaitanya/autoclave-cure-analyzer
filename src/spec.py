"""
Specification loader.

The cure specification is input, not logic. Different parts cure to different
schedules, so thresholds live in JSON where they are visible and arguable
rather than buried in code.

A malformed spec fails loudly here. The alternative is a rule silently
comparing against None and reporting every run as conforming.
"""

import json

REQUIRED = {
    "ramp": ["target_f_per_min", "min_f_per_min", "max_f_per_min"],
    "soak": ["target_f", "tolerance_f", "min_duration_min"],
    "cooldown": ["max_f_per_min"],
    "pressure": ["min_psi", "max_psi"],
    "vacuum": ["min_inhg"],
    "thermocouples": ["channels", "max_spread_f"],
}


class SpecError(ValueError):
    """Raised when a specification is missing or internally inconsistent."""


def load_spec(path):
    with open(path) as fh:
        spec = json.load(fh)
    validate(spec)
    return spec


def validate(spec):
    if "spec_id" not in spec:
        raise SpecError("Specification has no spec_id")

    for section, keys in REQUIRED.items():
        if section not in spec:
            raise SpecError(f"Specification is missing the '{section}' section")
        missing = [k for k in keys if k not in spec[section]]
        if missing:
            raise SpecError(f"Section '{section}' is missing: {', '.join(missing)}")

    r = spec["ramp"]
    if not r["min_f_per_min"] < r["max_f_per_min"]:
        raise SpecError("Ramp minimum rate is not below the maximum rate")
    if not r["min_f_per_min"] <= r["target_f_per_min"] <= r["max_f_per_min"]:
        raise SpecError("Ramp target rate falls outside its own min and max")

    p = spec["pressure"]
    if not p["min_psi"] < p["max_psi"]:
        raise SpecError("Pressure minimum is not below the maximum")

    if spec["soak"]["tolerance_f"] <= 0:
        raise SpecError("Soak tolerance must be positive")
    if spec["soak"]["min_duration_min"] <= 0:
        raise SpecError("Soak minimum duration must be positive")

    channels = spec["thermocouples"]["channels"]
    if not channels:
        raise SpecError("No thermocouple channels defined")

    spec.setdefault("detection", {}).setdefault("min_persistence_min", 3)
    spec["soak"].setdefault("governed_by", "slowest_probe")
    return spec
