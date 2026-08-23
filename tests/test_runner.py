"""End-to-end pipeline tests, driven by the four agreed mock cases."""

import json
from pathlib import Path

import pytest

from latch.events import RiskEvent
from latch.llm import FakeModel
from latch.locks import LockTable
from latch.models import Resolution
from latch.runner import (
    AutoApprove,
    CustomerAccepts,
    CustomerDeclinesAll,
    CustomerSilent,
    NeverApproves,
    handle,
)
from latch.state import RiskState
from latch.trace import TraceStore

MOCKS = Path(__file__).resolve().parent.parent / "fixtures" / "mock_events.json"


def mock_events() -> dict[str, RiskEvent]:
    return {
        p["connection_id"]: RiskEvent.from_dict(p)
        for p in json.loads(MOCKS.read_text())
    }


def client_for(event: RiskEvent, chosen: str | None = None) -> FakeModel:
    return FakeModel(
        {
            "triage": {"worth_deliberating": True, "reason": "scripted"},
            "deliberation": {
                "chosen_plan_id": chosen or f"{event.connection_id}-r3-unkunk_1100",
                "ranking": [],
                "rationale": "Road arrives before the cutoff; barge does not.",
            },
        }
    )


def run(event: RiskEvent, **kwargs):
    kwargs.setdefault("client", client_for(event))
    kwargs.setdefault("store", TraceStore())
    kwargs.setdefault("approvals", AutoApprove())
    kwargs.setdefault("customer", CustomerSilent())
    return handle(event, **kwargs)


def test_safe_event_costs_nothing_and_reaches_no_model():
    outcome = run(mock_events()["DEMO-000"])
    assert outcome.resolution is Resolution.DISMISSED_NO_ACTION
    assert outcome.state is RiskState.DISMISSED
    assert outcome.trace.cost.usd == 0.0


def test_the_four_cases_take_four_different_paths():
    """If they all resolved the same way the mock set would be testing nothing."""
    events = mock_events()
    resolutions = {
        cid: run(events[cid]).resolution.value
        for cid in ("DEMO-000", "DEMO-002", "DEMO-001", "DEMO-003")
    }
    assert resolutions["DEMO-000"] == "dismissed_no_action"
    assert resolutions["DEMO-002"] == "connection_held"
    assert resolutions["DEMO-001"] == "connection_held"
    # not avoidable under the available options, and the line never answered
    assert resolutions["DEMO-003"] == "window_lapsed_no_response"


def test_hopeless_case_reaches_the_customer_gate():
    outcome = run(mock_events()["DEMO-003"])
    gates = [s for s in outcome.trace.steps if s.type == "external_gate"]
    assert len(gates) == 1
    assert gates[0].payload["party"] == "line"


def test_line_deciding_is_service():
    outcome = run(mock_events()["DEMO-003"], customer=CustomerAccepts())
    assert outcome.resolution is Resolution.CUSTOMER_DECIDED
    assert outcome.resolution.is_service_success


def test_line_declining_everything_is_still_service():
    """The box rolls either way. Only one of the two is a failure."""
    outcome = run(mock_events()["DEMO-003"], customer=CustomerDeclinesAll())
    assert outcome.resolution is Resolution.CUSTOMER_DECLINED_ALL
    assert outcome.resolution.is_service_success


def test_silence_is_the_failure():
    outcome = run(mock_events()["DEMO-003"], customer=CustomerSilent())
    assert outcome.resolution is Resolution.WINDOW_LAPSED_NO_RESPONSE
    assert not outcome.resolution.is_service_success


def test_decision_lead_time_is_recorded_when_options_are_sent():
    outcome = run(mock_events()["DEMO-003"], customer=CustomerAccepts())
    assert outcome.trace.decision_lead_time_h is not None
    assert outcome.trace.options_alive_at_send > 0


def test_unsigned_approval_lapses_and_still_fires_the_default_action():
    """Doing nothing is also a decision, and it should be traced as one.

    Crucially it is an *internal* lapse. It used to close as
    WINDOW_LAPSED_NO_RESPONSE, which blamed the shipping line for failing to
    answer a question nobody asked it.
    """
    outcome = run(mock_events()["DEMO-001"], approvals=NeverApproves())
    assert outcome.resolution is Resolution.APPROVAL_LAPSED
    assert not outcome.resolution.reached_the_line
    assert not any(s.type == "external_gate" for s in outcome.trace.steps)
    assert outcome.state is RiskState.RESOLVED
    lapsed = [
        s
        for s in outcome.trace.steps
        if s.type == "gate" and s.payload.get("status") == "lapsed"
    ]
    assert lapsed


def test_large_volume_requires_a_signature():
    outcome = run(mock_events()["DEMO-001"])
    gate = next(s for s in outcome.trace.steps if s.type == "gate")
    assert gate.payload["escalated"] is True
    assert "84 boxes" in gate.payload["escalation_reason"]


def test_contention_sends_the_loser_to_the_customer_gate():
    """Two risks, one slot. The loser does not die quietly — losing a slot is
    not the same as having nothing to offer."""
    events = mock_events()
    minor, urgent = events["DEMO-002"], events["DEMO-001"]
    locks = LockTable()
    store = TraceStore()

    first = handle(
        minor,
        client=client_for(minor),
        store=store,
        locks=locks,
        approvals=AutoApprove(),
        customer=CustomerSilent(),
    )
    second = handle(
        urgent,
        client=client_for(urgent),
        store=store,
        locks=locks,
        approvals=AutoApprove(),
        customer=CustomerAccepts(),
    )

    assert first.resolution is Resolution.CONNECTION_HELD

    # The first risk booked the slot, so its capacity is consumed. Priority
    # arbitration governs provisional reservations; it cannot un-book a move
    # already underway, however urgent the newcomer.
    lock_steps = [s for s in second.trace.steps if s.type == "lock"]
    assert lock_steps
    assert any(s.payload["status"] == "lost" for s in lock_steps)

    # Losing the slot must not end the case quietly — it falls to the line.
    assert any(s.type == "external_gate" for s in second.trace.steps)


def test_a_booked_slot_stays_held_after_the_risk_closes():
    """Consumed capacity does not come back. Releasing a committed slot on
    resolution would hand it to the next risk and book it twice."""
    locks = LockTable()
    event = mock_events()["DEMO-001"]
    outcome = run(event, locks=locks)

    booked = any(s.type == "tool_call" and s.payload.get("tool") == "book_itt_leg"
                 for s in outcome.trace.steps)
    if booked:
        assert locks.held_by(event.connection_id), "a booked slot must stay held"
    else:
        assert locks.held_by(event.connection_id) == []


def test_a_risk_that_books_nothing_leaks_nothing():
    """The other half: a provisional claim on a plan that died is released."""
    locks = LockTable()
    locks.claim("itt_slot:orphan", "DEMO-999", priority=5.0)
    assert locks.release_all("DEMO-999") == ["itt_slot:orphan"]
    assert locks.held_by("DEMO-999") == []


def test_trace_records_the_watcher_signal_it_acted_on():
    """C renders this, and it is what makes the decision auditable back to A."""
    outcome = run(mock_events()["DEMO-001"])
    first = outcome.trace.steps[0]
    assert first.payload["watcher_confidence"] == "MEDIUM"
    assert "INTER_TERMINAL_TRANSFER_TIME" in first.payload["reason_codes"]


def test_every_trace_closes_with_a_resolution():
    """An open trace would sit in the console forever."""
    store = TraceStore()
    for event in mock_events().values():
        handle(
            event,
            client=client_for(event),
            store=store,
            approvals=AutoApprove(),
            customer=CustomerSilent(),
        )
    assert all(t.resolution is not None for t in store.all())
    assert store.metrics()["closed"] == 4


def test_state_never_moves_illegally():
    """Every transition in the pipeline goes through the validated table, so an
    illegal move raises rather than producing a plausible-looking trace."""
    for event in mock_events().values():
        outcome = run(event)
        assert outcome.state in (RiskState.RESOLVED, RiskState.DISMISSED)


@pytest.mark.parametrize("cid", ["DEMO-001", "DEMO-002", "DEMO-003"])
def test_cost_is_attributed_per_risk(cid):
    outcome = run(mock_events()[cid])
    assert outcome.trace.cost.usd > 0
    assert outcome.trace.cost.as_dict()["model_calls"] >= 1
