"""The recorded demo. Runs the agent, then plays back what it actually did.

    uv run python scripts/demo.py                    # §7.1 baseline, guaranteed
    uv run python scripts/demo.py --scenario contention
    uv run python scripts/demo.py --from-ais         # a real at-risk connection
    uv run python scripts/demo.py --pace 0           # no pauses, for checking
    uv run python scripts/demo.py --save traces/take.json

Three properties this is built around, all of which matter on the day:

  Deterministic   scripted tool failures, a fixed clock, a scripted model
                  seam. Record it twice and the takes match.

  Honest          the playback renders the trace the run produced. If a line
                  is on screen it is in the audit trail, and the numbers were
                  computed rather than written into the script.

  Standalone      needs no console, no API key and no network. If everything
                  else slips, this still records.
"""

import argparse
import json
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from latch.demo import beats_from_trace, outcome_panel
from latch.events import (
    Assumptions,
    ConnectionType,
    ReasonCode,
    RiskEvent,
    RiskSeverity,
    TimingResolution,
    WatcherConfidence,
)
from latch.llm import FakeModel
from latch.locks import LockTable
from latch.models import Terminal, TerminalResolution
from latch.runner import AutoApprove, CustomerSilent, handle
from latch.tools import CacheEntry, ScriptedFailures, ToolStatus
from latch.tools.stubs import build_itt_inventory
from latch.trace import TraceStore

T0 = datetime(2026, 8, 30, 4, 17, tzinfo=UTC)


def script(rationale: str) -> FakeModel:
    return FakeModel(
        {
            "triage": {
                "worth_deliberating": True,
                "reason": "Margin already negative against a large volume.",
            },
            "deliberation": {
                "chosen_plan_id": "",
                "ranking": [],
                "rationale": rationale,
            },
        }
    )


ASSUMED_TRANSFER_H = 1.5


def risk(
    connection_id: str,
    boxes: int,
    no_itt_h: float,
    inbound: Terminal,
    outbound: Terminal,
    detected_offset_min: float = 0.0,
) -> RiskEvent:
    """Build a scenario risk.

    The current-plan margin is derived from the no-transfer figure rather than
    set alongside it. Setting both by hand let them drift, and the options
    panel caught it: a scripted rationale claiming the barge arrived too late
    while the barge sat in the considered list, cheaper and cleaner than the
    option actually taken.
    """
    transfer_h = ASSUMED_TRANSFER_H if inbound is not outbound else 0.0
    margin_h = round(no_itt_h - transfer_h, 2)
    return RiskEvent(
        connection_id=connection_id,
        state=RiskSeverity.AT_RISK if margin_h <= 0 else RiskSeverity.WATCH,
        current_plan_slack_hours=margin_h,
        no_itt_slack_hours=no_itt_h,
        avoidable_by_terminal_prevention=inbound is not outbound,
        affected_boxes=boxes,
        watcher_confidence=WatcherConfidence.HIGH,
        timing_resolution=TimingResolution.LEGACY_SLACK_FALLBACK,
        reason_codes=(
            ReasonCode.INBOUND_ETA_SLIP,
            ReasonCode.INTER_TERMINAL_TRANSFER_TIME,
        ),
        detected_at=T0 + timedelta(minutes=detected_offset_min),
        ucid=f"UCID-SYNTH-{connection_id}",
        inbound_terminal=inbound,
        outbound_terminal=outbound,
        terminal_resolution=TerminalResolution.SIMULATED,
        assumptions=Assumptions(
            connection_type=(
                ConnectionType.INTER_TERMINAL
                if inbound is not outbound
                else ConnectionType.SAME_TERMINAL
            ),
            transfer_scenario="configured reference transfer scenario (1.5h assumed transfer)",
        ),
        inbound_vessel="SYNTHETIC MAERSK",
        outbound_vessel="SYNTHETIC FEEDER",
        source="scripted_demo_scenario",
    )


def scene_baseline(store: TraceStore):
    """§7.1 — the guaranteed take. A tool dies and the gate tightens by itself."""
    # 1.4h without the transfer: road (55m) still reaches the modelled cutoff,
    # the barge sailing (190m) does not. The cheaper, cleaner option losing to
    # the clock is the beat worth recording.
    event = risk("DEMO-BASE", 34, 1.4, Terminal.TUAS, Terminal.PASIR_PANJANG)
    # The live inventory call fails twice; a cached read from eight minutes ago
    # carries the day, and the staleness is what moves confidence.
    cached = CacheEntry(
        value=build_itt_inventory(
            event.detected_at, Terminal.TUAS, Terminal.PASIR_PANJANG
        ),
        age_min=8.0,
    )
    outcome = handle(
        event,
        client=script(
            "The assumed road transfer is the only mode that reaches the "
            "modelled cutoff; the barge sailing would arrive after it. "
            "Capacity here is a cached read, so this is provisional."
        ),
        store=store,
        failures=ScriptedFailures(
            {"query_itt_slot": [ToolStatus.TIMEOUT, ToolStatus.TIMEOUT]}
        ),
        itt_cache=cached,
        approvals=AutoApprove(),
        customer=CustomerSilent(),
    )
    return [("Tool failure and an automatic gate tightening", outcome)]


def scene_contention(store: TraceStore):
    """§7.2 — two risks, one slot, and the loser is not abandoned."""
    locks = LockTable()
    minor = risk("DEMO-MINOR", 18, 1.4, Terminal.TUAS, Terminal.PASIR_PANJANG)
    urgent = risk(
        "DEMO-URGENT", 92, 1.3, Terminal.TUAS, Terminal.PASIR_PANJANG,
        detected_offset_min=2,
    )
    first = handle(
        minor,
        client=script("Road transfer reaches the modelled cutoff."),
        store=store,
        locks=locks,
        approvals=AutoApprove(),
        customer=CustomerSilent(),
    )
    second = handle(
        urgent,
        client=script(
            "Ninety-two boxes against a closing window outranks the smaller "
            "claim on the same slot."
        ),
        store=store,
        locks=locks,
        approvals=AutoApprove(),
        customer=CustomerSilent(),
    )
    return [
        ("Smaller risk claims the last slot", first),
        ("Larger risk arrives and outranks it", second),
    ]


def scene_from_ais(store: TraceStore):
    """A real at-risk connection out of the October 2023 AIS month."""
    from latch.cases import CaseRegistry
    from latch.connections import ConnectionParams
    from latch.replay import ArrivalBoundary, ReplayConfig
    from latch.watcher import events_from_signals

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from run_historical import DEFAULT_CSV, arrival_signals

    if not DEFAULT_CSV.is_file() or DEFAULT_CSV.stat().st_size < 1_000:
        raise SystemExit("AIS data not pulled — run: git lfs install && git lfs pull")

    config = ReplayConfig(boundary=ArrivalBoundary())
    registry = CaseRegistry()
    chosen = None
    for event in events_from_signals(
        arrival_signals(DEFAULT_CSV, config, 60_000), ConnectionParams()
    ):
        if event.state is not RiskSeverity.AT_RISK:
            continue
        if registry.admit(event).should_process and event.affected_boxes >= 40:
            chosen = event
            break
    if chosen is None:
        raise SystemExit("no at-risk connection found in this slice")

    outcome = handle(
        chosen,
        client=script(
            "Assessed against the configured reference scenario; the assumed "
            "transfer does not reach the modelled cutoff."
        ),
        store=store,
        approvals=AutoApprove(),
        customer=CustomerSilent(),
    )
    return [("Real October 2023 vessel timing, synthetic connection", outcome)]


SCENES = {
    "baseline": scene_baseline,
    "contention": scene_contention,
    "ais": scene_from_ais,
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=("baseline", "contention"), default="baseline")
    parser.add_argument("--from-ais", action="store_true")
    parser.add_argument("--pace", type=float, default=1.2, help="seconds between beats")
    parser.add_argument("--step", type=float, default=5.0, help="displayed T+ increment")
    parser.add_argument("--full", action="store_true", help="include state changes")
    parser.add_argument("--no-colour", action="store_true")
    parser.add_argument("--save", type=Path, help="write the traces as JSON")
    args = parser.parse_args()

    colour = not args.no_colour and sys.stdout.isatty()
    store = TraceStore()
    scene = SCENES["ais" if args.from_ais else args.scenario]
    runs = scene(store)

    for title, outcome in runs:
        print()
        print("═" * 76)
        print(f"  LATCH — {title}")
        print("═" * 76)
        for beat in beats_from_trace(outcome.trace, args.step, args.full):
            print(beat.render(colour))
            if args.pace:
                time.sleep(args.pace)
        print()
        print(outcome_panel(outcome.trace))

    metrics = store.metrics()
    if metrics["at_risk"]:
        # Deliberately not "reached the customer" — a connection held
        # internally never reaches them, and saying so on screen would be a
        # false claim in the one place a judge is definitely watching.
        print(
            f"\n  {metrics['served']}/{metrics['at_risk']} at-risk connections "
            f"served: held internally, or the line decided with real options"
        )
    print(
        "\n  Vessel timing is real where the AIS scene is used. Connections,\n"
        "  terminals, box counts and transfer times are generated from frozen\n"
        "  parameters and declared as such in every trace above.\n"
    )

    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_text(
            json.dumps([o.trace.as_dict() for _, o in runs], indent=2),
            encoding="utf-8",
        )
        print(f"  captured fixture written to {args.save}\n")


if __name__ == "__main__":
    main()
