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
    args = parser.parse_args()

    events = [RiskEvent.from_dict(p) for p in json.loads(args.events.read_text())]
    store = TraceStore(sink=args.out)
    locks = LockTable()

    live = bool(os.environ.get("ANTHROPIC_API_KEY"))
    print(
        f"model: {'anthropic (live)' if live else 'FakeModel (no API key set)'}",
        file=sys.stderr,
    )

    for event in events:
        if live:
            client, _ = get_client()
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
    rate = metrics["service_rate"]
    print(
        f"\nserved {metrics['served']}/{metrics['at_risk']} at-risk "
        f"({rate:.0%} service rate) "
        f"| {metrics['excluded_dismissed']} dismissed, "
        f"{metrics['excluded_superseded']} superseded excluded "
        f"| ${store.cost_per_risk():.4f} per risk"
    )
    if not live:
        print(
            "\nThese numbers came from scripted model responses. They measure "
            "the pipeline, not the agent.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
