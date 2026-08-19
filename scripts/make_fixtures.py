"""Generate console fixtures for workstream C.

These are *scripted*, not agent output — the agent core does not exist yet.
They are built by driving the real domain objects (state machine, lock table,
confidence engine, trace recorder) rather than by hand-writing JSON, so a
fixture that violates a contract cannot be produced: every state move goes
through `transition()` and raises if illegal, and the contention priorities
come out of a real `LockTable` rather than being typed in.

Run:  uv run python scripts/make_fixtures.py
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from latch.config import (
    CONFIDENCE_ESCALATION_THRESHOLD,
    CUSTOMER_WINDOW_MIN,
    DELIBERATION_MODEL,
    TRIAGE_MODEL,
)
from latch.confidence import score
from latch.locks import LockTable
from latch.models import (
    ApprovalRole,
    ConnectionRisk,
    Provenance,
    Resolution,
    Rung,
    SourceKind,
    Terminal,
    TerminalResolution,
    ToolOutcome,
    VesselCall,
)
from latch.console import case_view
from latch.serde import risk_to_dict
from latch.state import RiskState, mermaid, transition
from latch.trace import Trace, TraceStore

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
T0 = datetime(2026, 8, 30, 4, 17, tzinfo=UTC)

TRIAGE_TOKENS = (1_840, 90)
DELIBERATION_TOKENS = (9_200, 1_140)


def make_risk(
    risk_id: str,
    *,
    boxes: int,
    slack_total_min: float,
    slack_remaining_min: float,
    eta_slip_min: float,
    inbound_terminal: Terminal = Terminal.TUAS,
    outbound_terminal: Terminal = Terminal.PASIR_PANJANG,
    resolution: TerminalResolution = TerminalResolution.TERMINAL,
    inbound_vessel: str = "SYNTHETIC MAERSK",
    outbound_vessel: str = "SYNTHETIC FEEDER",
    detected_offset_min: float = 0.0,
) -> ConnectionRisk:
    detected = T0 + timedelta(minutes=detected_offset_min)
    return ConnectionRisk(
        risk_id=risk_id,
        ucid=f"UCID-SGSIN-{risk_id[-4:]}",
        detected_at=detected,
        inbound=VesselCall(
            vessel_name=inbound_vessel,
            service_code="AE7",
            terminal=inbound_terminal,
            terminal_resolution=resolution,
            scheduled=detected,
            estimated=detected + timedelta(minutes=eta_slip_min),
        ),
        outbound=VesselCall(
            vessel_name=outbound_vessel,
            service_code="SEA3",
            terminal=outbound_terminal,
            terminal_resolution=resolution,
            scheduled=detected + timedelta(minutes=slack_total_min),
            estimated=detected + timedelta(minutes=slack_total_min),
        ),
        boxes_at_risk=boxes,
        slack_total_min=slack_total_min,
        slack_remaining_min=slack_remaining_min,
        source="oceans_x.vessel_movements",
        data_age_min=2.0,
    )


class Scenario:
    """A trace plus a state cursor that refuses illegal moves."""

    def __init__(self, risk: ConnectionRisk) -> None:
        self.risk = risk
        self.trace = Trace.for_risk(risk)
        self.state = RiskState.DETECTED
        self.trace.observation(
            f"{risk.boxes_at_risk} boxes, slack {risk.slack_remaining_min:.0f}m of "
            f"{risk.slack_total_min:.0f}m ({risk.slack_consumed_pct:.0%} consumed), "
            f"{risk.inbound.terminal.value} -> {risk.outbound.terminal.value}",
            priority=round(risk.priority, 2),
        )

    def move(self, target: RiskState, reason: str = "") -> None:
        previous = self.state
        self.state = transition(self.state, target)
        self.trace.state_change(previous.value, self.state.value, reason)

    def triage(self, keep: bool, summary: str) -> None:
        self.trace.model_call(TRIAGE_MODEL, *TRIAGE_TOKENS, purpose="triage")
        self.trace.observation(summary)
        self.move(RiskState.TRIAGED if keep else RiskState.DISMISSED, summary)

    def deliberate(self) -> None:
        self.move(RiskState.DELIBERATING, "walking the ladder")
        self.trace.model_call(
            DELIBERATION_MODEL, *DELIBERATION_TOKENS, purpose="deliberation"
        )


def write(name: str, payload: object) -> None:
    path = FIXTURES / name
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"  {path.relative_to(FIXTURES.parent)}")


# --- scenarios --------------------------------------------------------------


def scenario_baseline_timeout() -> Scenario:
    """§7.1 — the guaranteed demo. Tool fails, cache saves it, gate tightens."""
    risk = make_risk(
        "cr_0001",
        boxes=34,
        slack_total_min=720,
        slack_remaining_min=110,
        eta_slip_min=361,
    )
    s = Scenario(risk)
    s.triage(True, "slack 85% consumed against a 12h window; escalate to deliberation")
    s.deliberate()

    s.trace.tool_call("query_itt_slot", status="timeout", latency_ms=5_000)
    s.trace.error(
        "query_itt_slot", error_class="timeout", retries=1, recovery="retry with backoff"
    )
    s.trace.tool_call("query_itt_slot", status="timeout", latency_ms=5_000)
    s.trace.error(
        "query_itt_slot",
        error_class="timeout",
        retries=1,
        recovery="cached inventory @ T-8m",
    )

    breakdown = score(
        (
            Provenance(
                "itt_capacity",
                SourceKind.CACHE,
                age_min=8.0,
                tool_outcome=ToolOutcome.RETRIED,
                verified=False,
            ),
            Provenance("outbound_capacity", SourceKind.LIVE_API, age_min=1.0, verified=False),
            Provenance("berth_window", SourceKind.LIVE_API),
        )
    )
    s.trace.confidence(breakdown.as_dict())
    s.trace.decision(
        rung=Rung.MOVE.value,
        chosen=True,
        confidence=breakdown.confidence,
        rationale="Barge slot covers all 34 boxes within the window at lower emissions "
        "than road; capacity read is from cache, so the number is provisional.",
    )

    s.move(RiskState.AWAITING_APPROVAL, "policy requires vessel ops at this volume")
    s.trace.gate(
        rung=Rung.MOVE.value,
        role=ApprovalRole.VESSEL_OPS.value,
        escalated=False,
        status="pending",
    )
    s.move(
        RiskState.ESCALATED,
        f"confidence {breakdown.confidence:.2f} < {CONFIDENCE_ESCALATION_THRESHOLD}",
    )
    s.trace.gate(
        rung=Rung.MOVE.value,
        role=ApprovalRole.DUTY_MANAGER.value,
        escalated=True,
        escalation_reason=f"confidence < {CONFIDENCE_ESCALATION_THRESHOLD}",
        status="approved",
        latency_s=41,
    )

    s.move(RiskState.EXECUTING, "approved with the cache caveat visible")
    s.trace.tool_call(
        "book_itt_slot", status="ok", latency_ms=850, booking_ref="BK-tuapas_1140-SG0001"
    )
    s.move(RiskState.RESOLVED, "all 34 boxes on the barge leg")
    s.trace.close(Resolution.CONNECTION_HELD)
    return s


def scenario_contention() -> tuple[Scenario, Scenario]:
    """§7.2 — two risks, one slot. Priorities come from a real LockTable."""
    slot = "itt_slot:tuapas_1140"
    table = LockTable(clock=lambda: T0)

    minor = make_risk(
        "cr_0002",
        boxes=18,
        slack_total_min=600,
        slack_remaining_min=58,
        eta_slip_min=290,
        detected_offset_min=0,
    )
    urgent = make_risk(
        "cr_0003",
        boxes=52,
        slack_total_min=480,
        slack_remaining_min=76,
        eta_slip_min=330,
        inbound_terminal=Terminal.BRANI,
        outbound_terminal=Terminal.PASIR_PANJANG,
        inbound_vessel="SYNTHETIC ONE",
        outbound_vessel="SYNTHETIC FEEDER II",
        detected_offset_min=2,
    )

    loser = Scenario(minor)
    loser.triage(True, "94% of window consumed; 18 boxes crossing terminals")
    loser.deliberate()
    first = table.claim(slot, minor.risk_id, minor.priority)
    loser.trace.lock(
        slot, status=first.status, our_priority=first.our_priority, action="claimed"
    )

    winner = Scenario(urgent)
    winner.triage(True, "84% of window consumed; 52 boxes crossing terminals")
    winner.deliberate()
    second = table.claim(slot, urgent.risk_id, urgent.priority)
    winner.trace.lock(
        slot,
        status=second.status,
        our_priority=second.our_priority,
        winner_priority=second.winner_priority,
        action=f"preempted {second.preempted_risk_id}",
    )

    # Winner: books and resolves.
    winner.trace.confidence(
        score((Provenance("itt_capacity", SourceKind.LIVE_API),)).as_dict()
    )
    winner.trace.decision(
        rung=Rung.MOVE.value,
        chosen=True,
        confidence=1.0,
        rationale="Higher boxes-at-risk over remaining slack; takes the contested slot.",
    )
    winner.move(RiskState.EXECUTING, "auto-approved: live data, within policy limits")
    table.commit(slot, urgent.risk_id)
    winner.trace.tool_call("book_itt_slot", status="ok", latency_ms=850)
    winner.move(RiskState.RESOLVED, "all 52 boxes on the contested slot")
    winner.trace.close(Resolution.CONNECTION_HELD)

    # Loser: re-deliberates, finds nothing, falls to Rung 4, and is never answered.
    loser.trace.lock(
        slot,
        status="lost",
        our_priority=minor.priority,
        winner_priority=urgent.priority,
        action="re-deliberate with this option removed",
    )
    loser.move(RiskState.LOST_LOCK, f"outranked by {urgent.risk_id}")
    loser.move(RiskState.DELIBERATING, "re-deliberating without the contested slot")
    loser.trace.model_call(
        DELIBERATION_MODEL, 6_400, 720, purpose="deliberation (re-run)"
    )
    loser.trace.tool_call(
        "query_itt_slot", status="ok", latency_ms=420, alternatives_found=0
    )
    loser.trace.observation("no alternative inter-terminal slot inside the window")
    loser.trace.decision(
        rung=Rung.OFFER.value,
        chosen=True,
        confidence=0.91,
        rationale="Nothing left to resolve internally. Three outbound services still "
        "callable — put them to the line while they exist.",
    )

    offer_sent = T0 + timedelta(hours=6, minutes=12)
    loser.move(RiskState.AWAITING_CUSTOMER, "PSA cannot re-route cargo; the line can")
    loser.trace.tool_call("send_options_to_line", status="ok", latency_ms=640)
    loser.trace.external_gate(
        party="line",
        options_sent=3,
        window_min=CUSTOMER_WINDOW_MIN,
        outcome="LAPSED_NO_RESPONSE",
    )
    loser.move(RiskState.EXECUTING, "window closed; default action fires")
    loser.trace.tool_call("roll_to_next_service", status="ok", latency_ms=310)
    loser.move(RiskState.RESOLVED, "rolled by default, not by decision")
    loser.trace.close(
        Resolution.WINDOW_LAPSED_NO_RESPONSE, offer_sent_at=offer_sent, options_alive=3
    )

    return winner, loser


def scenario_dismissed() -> Scenario:
    """Most events are not risks. Triage kills ~85-90% and that is the point."""
    risk = make_risk(
        "cr_0004",
        boxes=6,
        slack_total_min=1800,
        slack_remaining_min=1430,
        eta_slip_min=370,
    )
    s = Scenario(risk)
    s.triage(
        False,
        "6h slip against 30h of slack; 21% consumed, well inside the window. "
        "Delay magnitude is large and irrelevant.",
    )
    s.trace.close(Resolution.DISMISSED_NO_ACTION)
    return s


def scenario_superseded() -> Scenario:
    """Fires often in practice, and demonstrates real state management."""
    risk = make_risk(
        "cr_0005",
        boxes=22,
        slack_total_min=540,
        slack_remaining_min=95,
        eta_slip_min=300,
    )
    s = Scenario(risk)
    s.triage(True, "82% of window consumed; deliberating")
    s.deliberate()
    s.trace.tool_call("query_itt_slot", status="ok", latency_ms=420)
    s.trace.observation("inbound ETA improved 148m mid-deliberation; slack restored")
    s.move(RiskState.SUPERSEDED, "ETA improved; connection no longer at risk")
    s.trace.close(Resolution.SUPERSEDED)
    return s


def scenario_customer_declined() -> Scenario:
    """The exit that looks like failure and is not.

    The box rolls. The line was asked, had real options, and said no to all of
    them. That is a served customer, and the distinction from the lapsed case
    is the whole product.
    """
    risk = make_risk(
        "cr_0006",
        boxes=29,
        slack_total_min=420,
        slack_remaining_min=64,
        eta_slip_min=280,
        resolution=TerminalResolution.INFERRED,
    )
    s = Scenario(risk)
    s.triage(True, "85% of window consumed; 29 boxes")
    s.deliberate()
    s.trace.tool_call("query_itt_slot", status="ok", latency_ms=420, alternatives_found=0)
    s.trace.observation("no internal resolution available inside the window")
    s.trace.decision(
        rung=Rung.OFFER.value,
        chosen=True,
        confidence=0.83,
        rationale="Two outbound services still callable. Escalating before internal "
        "evaluation completes: option count decays faster than certainty improves.",
    )

    offer_sent = T0 + timedelta(hours=4, minutes=48)
    s.move(RiskState.AWAITING_CUSTOMER, "options ranked and sent")
    s.trace.tool_call("send_options_to_line", status="ok", latency_ms=640)
    s.trace.external_gate(
        party="line",
        options_sent=2,
        window_min=CUSTOMER_WINDOW_MIN,
        outcome="DECLINED_ALL",
    )
    s.move(RiskState.EXECUTING, "line declined both; the roll is their call")
    s.trace.tool_call("roll_to_next_service", status="ok", latency_ms=310)
    s.move(RiskState.RESOLVED, "rolled by the line's decision")
    s.trace.close(
        Resolution.CUSTOMER_DECLINED_ALL, offer_sent_at=offer_sent, options_alive=2
    )
    return s


def main() -> None:
    FIXTURES.mkdir(exist_ok=True)

    baseline = scenario_baseline_timeout()
    winner, loser = scenario_contention()
    scenarios = [
        baseline,
        winner,
        loser,
        scenario_dismissed(),
        scenario_superseded(),
        scenario_customer_declined(),
    ]

    print("writing fixtures:")
    write("risks.json", [risk_to_dict(s.risk) for s in scenarios])
    write("traces.json", [s.trace.as_dict() for s in scenarios])
    # What the console actually renders. Emitted alongside the raw traces so C
    # builds against the view model rather than re-deriving it from steps.
    write("console_views.json", [case_view(s.trace) for s in scenarios])

    (FIXTURES / "state_diagram.mmd").write_text(mermaid() + "\n", encoding="utf-8")
    print("  fixtures/state_diagram.mmd")

    # Reuse the store's metric rather than recomputing it here — the fixture
    # summary and the console must not be able to disagree about the number.
    store = TraceStore()
    for scenario in scenarios:
        store.adopt(scenario.trace)

    summary = {
        "scenarios": len(scenarios),
        **store.metrics(),
        "total_usd": round(sum(s.trace.cost.usd for s in scenarios), 6),
        "usd_per_risk": round(
            sum(s.trace.cost.usd for s in scenarios) / len(scenarios), 6
        ),
        "resolutions": {s.risk.risk_id: s.trace.resolution.value for s in scenarios},
        "final_states": {s.risk.risk_id: s.state.value for s in scenarios},
    }
    write("summary.json", summary)

    print(
        f"\n{len(scenarios)} scenarios; service rate "
        f"{summary['service_rate']:.0%} ({summary['served']}/{summary['at_risk']} "
        f"at-risk, {summary['excluded_dismissed'] + summary['excluded_superseded']} "
        f"excluded), ${summary['usd_per_risk']:.4f} per risk"
    )


if __name__ == "__main__":
    main()
