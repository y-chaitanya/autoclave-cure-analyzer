"""
Summary layer.

The detector has already decided whether the run conformed. This module turns
those findings into prose an engineer can read. It evaluates nothing.

Two writers sit behind one interface: a deterministic template writer that
always works, and a language model writer used when an API key is configured.
Whichever writes, the verifier checks the result the same way.
"""

import os
import textwrap


def facts_for_summary(analysis):
    """The only information a writer receives.

    Writers are given the detector's output, never the run log. A writer
    cannot reach past this into the data and form a conclusion of its own.
    """
    return {
        "run_id": analysis.run_id,
        "spec_id": analysis.spec_id,
        "conforming": analysis.conforming,
        "stages": analysis.stages,
        "metrics": analysis.metrics,
        "deviations": [f.to_dict() for f in analysis.deviations],
        "passed": [f.code for f in analysis.findings if f.passed],
    }


class TemplateWriter:
    """Deterministic summary. The same findings always produce the same text."""

    name = "template"

    def write(self, facts):
        m = facts["metrics"]
        lines = []

        if facts["conforming"]:
            lines.append(
                f"Run {facts['run_id']} conformed to specification "
                f"{facts['spec_id']}. Every checked parameter stayed within limits."
            )
        else:
            devs = facts["deviations"]
            major = sum(1 for d in devs if d["severity"] == "major")
            lines.append(
                f"Run {facts['run_id']} deviated from specification "
                f"{facts['spec_id']}. {len(devs)} deviation(s) were recorded"
                + (f", {major} classified major." if major else ".")
            )

        soak = facts["stages"].get("soak")
        soak_text = (
            f"The soak plateau ran from minute {soak['start_min']} to "
            f"{soak['end_min']}, with part temperature inside tolerance for "
            f"{m['soak_minutes_at_temp']} minutes. "
        ) if soak else "No soak plateau was detected. "

        lines.append(
            f"The run covered {m['total_duration_min']} minutes across "
            f"{m['readings']} readings. Air temperature peaked at "
            f"{m['peak_air_temp_f']} F and part temperature at "
            f"{m['peak_part_temp_f']} F. " + soak_text +
            f"Through ramp and soak, pressure fell no lower than "
            f"{m['min_pressure_psi_in_cure']} psi, vacuum no lower than "
            f"{m['min_vacuum_inhg_in_cure']} inHg, and the widest probe spread "
            f"was {m['max_tc_spread_f_in_cure']} F."
        )

        for d in facts["deviations"]:
            window = ""
            if d["window_min"]:
                window = (f" The condition was sustained between minute "
                          f"{d['window_min'][0]:.0f} and {d['window_min'][1]:.0f}.")
            lines.append(f"{d['code']}: {d['detail']}{window}")

        if not facts["conforming"]:
            lines.append(
                "This run needs engineering disposition against the part's "
                "material allowables before the affected hardware is accepted."
            )

        return "\n\n".join(textwrap.fill(ln, 88) for ln in lines)


class LLMWriter:
    """Language model summary, used when ANTHROPIC_API_KEY is configured.

    The prompt carries only the detector's findings and instructs the model to
    introduce no figure it was not given. That instruction is a request, not a
    guarantee, which is why verify.py checks the output regardless.
    """

    name = "llm"

    PROMPT = (
        "You are writing a short process engineering note about an autoclave "
        "cure run for an aerospace composites manufacturer.\n\n"
        "The findings below were produced by a rule engine. They are "
        "authoritative and already decided.\n\n"
        "Write three to five short paragraphs for a process engineer. State "
        "whether the run conformed, describe each deviation and what it means "
        "physically for the cure, and note what should be reviewed.\n\n"
        "Use only the numbers given below. Do not calculate, estimate, or "
        "introduce any figure that does not appear here. Do not reach a "
        "conformance conclusion of your own.\n\n"
        "FINDINGS:\n{facts}"
    )

    def __init__(self, model="claude-sonnet-4-5", max_tokens=900):
        self.model = model
        self.max_tokens = max_tokens

    @staticmethod
    def available():
        return bool(os.environ.get("ANTHROPIC_API_KEY"))

    def write(self, facts):
        import json
        from anthropic import Anthropic

        response = Anthropic().messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[{"role": "user",
                       "content": self.PROMPT.format(facts=json.dumps(facts, indent=2))}],
        )
        return response.content[0].text.strip()


def get_writer(prefer_llm=True):
    """An LLM writer when one is usable, otherwise the template writer."""
    if prefer_llm and LLMWriter.available():
        try:
            import anthropic  # noqa: F401
            return LLMWriter()
        except ImportError:
            pass
    return TemplateWriter()
