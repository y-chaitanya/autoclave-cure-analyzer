"""
Command line entry point.

    python src/main.py data/runs/run_1004.csv
    python src/main.py data/runs/run_1004.csv --json
    python src/main.py data/runs/run_1004.csv --no-llm
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from spec import load_spec                              # noqa: E402
from detect import load_run, analyze                    # noqa: E402
from summarize import get_writer, facts_for_summary     # noqa: E402
from verify import verify, format_report                # noqa: E402

MARK = {"pass": "  ok  ", "minor": " MINOR", "major": " MAJOR"}


def run_id_from_path(path):
    return os.path.splitext(os.path.basename(path))[0].replace("run_", "")


def print_report(a, summary, ok, claims, writer_name):
    print("=" * 80)
    print(f"  Run {a.run_id}   specification {a.spec_id}")
    print(f"  {'CONFORMING' if a.conforming else 'DEVIATIONS RECORDED'}")
    print("=" * 80)

    print("\nSTAGES")
    for name, st in a.stages.items():
        if st:
            print(f"  {name:<6} minute {st['start_min']:>4} to {st['end_min']:<4} "
                  f"({st['readings']} readings)")
        else:
            print(f"  {name:<6} not detected")

    print("\nFINDINGS")
    for f in a.findings:
        measured = f"{f.measured:g} {f.units}" if f.measured is not None else "n/a"
        print(f"  [{MARK[f.severity]}] {f.code:<22} {measured}")
        print(f"           {f.detail}")

    print("\nMETRICS")
    for k, v in a.metrics.items():
        print(f"  {k:<26} {v}")

    print("\nENGINEERING SUMMARY")
    if ok:
        print()
        for line in summary.splitlines():
            print(f"  {line}" if line.strip() else "")
    else:
        print("\n  [withheld — failed verification]")

    print("\nVERIFICATION")
    for line in format_report(ok, claims).splitlines():
        print(f"  {line}")
    print(f"\n  summary written by: {writer_name}\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Analyze an autoclave cure run log.")
    ap.add_argument("run", help="path to a run log CSV")
    ap.add_argument("--spec", default="data/cure_spec.json")
    ap.add_argument("--no-llm", action="store_true",
                    help="force the deterministic template writer")
    ap.add_argument("--persistence", type=int, default=None,
                    help="override the spec's persistence threshold, in minutes")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    spec = load_spec(args.spec)
    rows = load_run(args.run)
    a = analyze(rows, spec, run_id_from_path(args.run), persistence=args.persistence)

    writer = get_writer(prefer_llm=not args.no_llm)
    summary = writer.write(facts_for_summary(a))
    ok, claims = verify(summary, a)

    if args.json:
        print(json.dumps({
            **a.to_dict(),
            "summary": summary if ok else None,
            "summary_writer": writer.name,
            "verification_passed": ok,
            "claims_checked": len(claims),
            "unsupported_claims": [{"value": c.value, "context": c.context}
                                   for c in claims if not c.supported],
        }, indent=2))
    else:
        print_report(a, summary, ok, claims, writer.name)

    return 0 if a.conforming else 1


if __name__ == "__main__":
    # Piping into head closes stdout early. Without this the tool exits with
    # a traceback on what is a perfectly ordinary way to read long output.
    try:
        sys.exit(main())
    except BrokenPipeError:
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        sys.exit(0)
