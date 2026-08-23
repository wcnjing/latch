"""Command line: run risk events through the agent core.

    uv run latch                          # the four mock cases
    uv run latch --events path/to.json    # A's output, once it exists
    uv run latch --customer accepts --approvals never

The point of the flags is that the interesting outcomes are the ones we do
not control. A duty manager who never signs and a line that never replies are
both selectable, because both are real.
"""

import argparse
import json
import os
import sys
from pathlib import Path

from latch.events import RiskEvent
from latch.llm import FakeModel, get_client
from latch.locks import LockTable
from latch.runner import (
    AutoApprove,
    CustomerAccepts,
    CustomerDeclinesAll,
    CustomerSilent,
    NeverApproves,
    handle,
)
from latch.trace import TraceStore

DEFAULT_EVENTS = Path(__file__).resolve().parent.parent.parent / "fixtures" / "mock_events.json"

APPROVALS = {"auto": AutoApprove, "never": NeverApproves}
CUSTOMERS = {
    "silent": CustomerSilent,
    "accepts": CustomerAccepts,
    "declines": CustomerDeclinesAll,
}

SCRIPT = {
    "triage": {
        "worth_deliberating": True,
        "reason": "Volume and remaining slack justify deliberation.",
    },
}


def main() -> int:
    parser = argparse.ArgumentParser(prog="latch", description=__doc__)
    parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    parser.add_argument("--approvals", choices=sorted(APPROVALS), default="auto")
    parser.add_argument("--customer", choices=sorted(CUSTOMERS), default="silent")
    parser.add_argument("--out", type=Path, help="write traces as JSONL")
    parser.add_argument(
        "--model",
        choices=("auto", "fake", "local", "anthropic"),
        default="auto",
        help="auto picks anthropic when a key is set, otherwise fake",
    )
    args = parser.parse_args()

    events = [RiskEvent.from_dict(p) for p in json.loads(args.events.read_text())]
    store = TraceStore(sink=args.out)
    locks = LockTable()

    from latch.config import LOCAL_MODEL, LOCAL_MODEL_LICENCE
    from latch.llm import OllamaModel

    choice = args.model
    if choice == "auto":
        choice = "anthropic" if os.environ.get("ANTHROPIC_API_KEY") else "fake"

    label = {
        "anthropic": "anthropic (billed)",
        "local": f"{LOCAL_MODEL} via ollama ({LOCAL_MODEL_LICENCE}, zero marginal cost)",
        "fake": "FakeModel (scripted; measures the pipeline, not the agent)",
    }[choice]
    print(f"model: {label}", file=sys.stderr)
    live = choice == "anthropic"

    for event in events:
        if live:
            client, _ = get_client()
        elif choice == "local":
            client = OllamaModel()
        else:
            client = FakeModel(
                SCRIPT
                | {
                    "deliberation": {
                        "chosen_plan_id": "",
                        "ranking": [],
                        "rationale": "Scripted choice; no model was consulted.",
                    }
                }
            )
        outcome = handle(
            event,
            client=client,
            store=store,
            locks=locks,
            approvals=APPROVALS[args.approvals](),
            customer=CUSTOMERS[args.customer](),
        )
        print(
            f"{event.connection_id:10} {outcome.state.value:10} "
            f"{outcome.resolution.value:26} "
            f"steps={len(outcome.trace.steps):3} "
            f"usd={outcome.trace.cost.usd:.4f}"
        )
        store.flush(outcome.trace)

    metrics = store.metrics()
    # Both of these are None when nothing was at risk, which is an ordinary
    # outcome — every connection triaged clean — and used to end the run in a
    # TypeError from the format string after all the work had already been done.
    rate = metrics["service_rate"]
    per_risk = store.cost_per_risk()
    rate_text = f"{rate:.0%} service rate" if rate is not None else "no service rate"
    per_risk_text = f"${per_risk:.4f} per risk" if per_risk is not None else "n/a"
    print(
        f"\nserved {metrics['served']}/{metrics['at_risk']} at-risk "
        f"({rate_text}) "
        f"| {metrics['excluded_dismissed']} dismissed, "
        f"{metrics['excluded_superseded']} superseded excluded "
        f"| {per_risk_text}"
    )
    # Whose failure it was. An unsigned internal approval and a line that never
    # replied are different problems, and one number hides which you have.
    if metrics["failed_internally"] or metrics["failed_at_the_line"]:
        print(
            f"  failures: {metrics['failed_internally']} internal "
            f"(never reached the line), "
            f"{metrics['failed_at_the_line']} at the line "
            f"(of {metrics['reached_the_line']} asked)"
        )
    if choice == "fake":
        print(
            "\nThese numbers came from scripted model responses. They measure "
            "the pipeline, not the agent.",
            file=sys.stderr,
        )
    elif choice == "local":
        print(
            f"\nRan on {LOCAL_MODEL} locally. Dollar cost is zero at the margin, "
            "not zero outright — it cost this machine's time and power.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
