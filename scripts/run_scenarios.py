"""Run the disruption scenario suite.

    uv run python scripts/run_scenarios.py                  # rails only
    uv run python scripts/run_scenarios.py --model local
    uv run python scripts/run_scenarios.py --model anthropic

The two numbers measure different things and must be reported separately.
`policy` removes judgement entirely and tests the rails — a failure there is a
bug. `local` and `anthropic` test whether the model chooses well among options
the rails already validated — a failure there is a prompt problem.
"""

import argparse
import sys

from latch.config import LOCAL_MODEL
from latch.scenarios import PolicyModel, print_progress, run_suite


def main() -> int:
    parser = argparse.ArgumentParser(prog="latch-scenarios", description=__doc__)
    parser.add_argument(
        "--model", choices=("policy", "local", "anthropic"), default="policy"
    )
    parser.add_argument("--family", help="run one family only")
    args = parser.parse_args()

    if args.model == "policy":
        client, label = PolicyModel(), "PolicyModel (rails only, no judgement)"
    elif args.model == "local":
        from latch.llm import OllamaModel

        client, label = OllamaModel(), f"{LOCAL_MODEL} (judgement)"
    else:
        from latch.llm import AnthropicModel

        client, label = AnthropicModel(), "claude (judgement, billed)"

    suite = None
    if args.family:
        from latch.scenario_suite import SUITE

        suite = tuple(s for s in SUITE if s.family == args.family)
        if not suite:
            print(f"no scenarios in family {args.family!r}", file=sys.stderr)
            return 2

    # Progress only where silence is expensive: the rails run is instant.
    progress = print_progress if args.model != "policy" else None
    report = run_suite(client, label, suite=suite, on_progress=progress)
    print(report.render())
    return 0 if not report.misses() else 1


if __name__ == "__main__":
    raise SystemExit(main())
