"""
Verification layer.

A generated summary is not trusted because the prompt asked it to be accurate.
Every number in the prose is extracted and traced back to the detector's
output. Anything that cannot be traced is reported and the summary is withheld.

A summary that invents a deviation is worse than no summary. It sends someone
looking for a problem that is not there, and once that happens nobody trusts
the tool again. This is the same lesson as the tie-out check in the AR aging
analyzer, applied to model output instead of a spreadsheet formula.
"""

import re
from dataclasses import dataclass

# Rounding tolerance. A summary reporting 349.7 F where the detector holds
# 349.68 is stating the same measurement, not a different one.
TOLERANCE = 0.06

NUMBER = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)(?![\w.])")


@dataclass
class Claim:
    value: float
    context: str
    supported: bool


def supported_values(analysis):
    """Every figure the summary is entitled to state.

    Drawn from the detector's own output: the metrics, each finding's measured
    value and limit, the gap between them, which a writer may express as
    "short by", the stage boundaries, and counts of findings.
    """
    values = set()

    for v in analysis.metrics.values():
        if isinstance(v, (int, float)):
            values.add(float(v))

    for stage in analysis.stages.values():
        if stage:
            for v in stage.values():
                if isinstance(v, (int, float)):
                    values.add(float(v))

    for f in analysis.findings:
        for v in (f.measured, f.limit):
            if isinstance(v, (int, float)):
                values.add(float(v))
        if isinstance(f.measured, (int, float)) and isinstance(f.limit, (int, float)):
            values.add(round(abs(f.measured - f.limit), 2))
        if f.window_min:
            values.update(float(x) for x in f.window_min)
        # Counts the detector itself stated inside its detail text
        values.update(float(n) for n in NUMBER.findall(f.detail))

    devs = analysis.deviations
    values.add(float(len(devs)))
    values.add(float(len(analysis.findings)))
    values.add(float(sum(1 for f in devs if f.severity == "major")))
    values.add(float(sum(1 for f in devs if f.severity == "minor")))

    values.update(float(n) for n in NUMBER.findall(analysis.run_id))
    values.update(float(n) for n in NUMBER.findall(analysis.spec_id))
    return values


def verify(summary_text, analysis):
    """Trace every number in the summary back to the detector's output."""
    allowed = supported_values(analysis)
    claims = []

    for match in NUMBER.finditer(summary_text):
        value = float(match.group(1))
        start, end = max(0, match.start() - 45), min(len(summary_text), match.end() + 45)
        context = " ".join(summary_text[start:end].split())
        supported = any(abs(value - a) <= TOLERANCE for a in allowed)
        claims.append(Claim(value, context, supported))

    return all(c.supported for c in claims), claims


def format_report(ok, claims):
    if ok:
        return f"Verification passed. {len(claims)} numeric claim(s) traced to run data."

    bad = [c for c in claims if not c.supported]
    lines = [f"Verification FAILED. {len(bad)} of {len(claims)} numeric claim(s) "
             f"could not be traced to run data:", ""]
    for c in bad:
        lines.append(f"  unsupported value {c.value:g}")
        lines.append(f"    context: ...{c.context}...")
    lines += ["", "The summary has been withheld. Review the detector findings directly."]
    return "\n".join(lines)
