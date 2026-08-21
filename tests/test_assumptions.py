"""Assumption disclosure tests.

The agent writes an audit trail. A trace that says "PSA confirmed this
container needs 5.2 hours to transfer" has fabricated a claim about the real
world, and no amount of caveating elsewhere repairs it.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from latch.connections import connection_for
from latch.events import Assumptions, ConnectionType, RiskEvent
from latch.llm import FakeModel
from latch.runner import AutoApprove, CustomerSilent, handle
from latch.trace import TraceStore
from latch.watcher import to_risk_event

T0 = datetime(2023, 10, 1, tzinfo=UTC)

# Words that assert a synthetic figure as an observed fact.
ASSERTIVE = ("psa confirmed", "confirmed that", "actual transfer", "measured transfer")


@dataclass
class Signal:
    call_id: str
    vessel_id: str
    observed_at: datetime
    predicted_arrival: datetime | None
    reference_arrival: datetime | None
    data_quality: str = "good"


def run_trace(call_id: str = "call_probe_1", slip_h: float = 20.0):
    connection = connection_for(call_id, "v1", T0 + timedelta(hours=2))
    event = to_risk_event(
        Signal(
            call_id,
            "v1",
            T0,
            T0 + timedelta(hours=slip_h),
            T0 + timedelta(hours=2),
        ),
        connection,
    )
    client = FakeModel(
        {
            "triage": {"worth_deliberating": True, "reason": "scripted"},
            "deliberation": {
                "chosen_plan_id": "",
                "ranking": [],
                "rationale": "scripted",
            },
        }
    )
    return handle(
        event,
        client=client,
        store=TraceStore(),
        approvals=AutoApprove(),
        customer=CustomerSilent(),
    )


def test_unlabelled_events_default_to_synthetic():
    """Assuming the safer thing about unlabelled data is the only default that
    cannot mislead."""
    plain = RiskEvent.from_dict(
        {
            "connection_id": "X",
            "state": "AT_RISK",
            "current_plan_slack_hours": -1.0,
            "no_itt_slack_hours": 1.0,
            "avoidable_by_terminal_prevention": True,
            "affected_boxes": 20,
            "confidence": "HIGH",
            "reason_codes": [],
        }
    )
    assert plain.assumptions.any_synthetic
    assert plain.assumptions.ucid_synthetic
    assert plain.assumptions.boxes_synthetic


def test_connection_type_follows_the_transfer_requirement():
    transferring = next(
        connection_for(f"call_probe_{i}", "v1", T0 + timedelta(hours=2))
        for i in range(200)
        if connection_for(
            f"call_probe_{i}", "v1", T0 + timedelta(hours=2)
        ).requires_transfer
    )
    event = to_risk_event(
        Signal(transferring.call_id, "v1", T0, T0 + timedelta(hours=6), T0),
        transferring,
    )
    assert event.assumptions.connection_type is ConnectionType.INTER_TERMINAL


def test_every_derived_figure_is_stated_under_the_scenario():
    """The headline observation must not read as an observation."""
    trace = run_trace().trace
    headline = trace.steps[0].payload["summary"]
    assert headline.startswith("Under the configured reference transfer scenario")
    assert "remaining margin" in headline
    assert "slack" not in headline.lower(), "'slack' reads as a measured quantity"


def test_no_itt_slack_is_explained_not_just_reported():
    """A bare second number invites the reader to invent its meaning."""
    headline = run_trace().trace.steps[0].payload["summary"]
    assert "if the transfer requirement were removed" in headline


def test_the_assumption_basis_is_recorded_once_per_trace():
    steps = run_trace().trace.steps
    basis = [s for s in steps if s.payload.get("slack_is_scenario_output")]
    assert len(basis) == 1
    payload = basis[0].payload
    assert payload["ucid_synthetic"] is True
    assert payload["pairing_synthetic"] is True
    assert payload["terminals_synthetic"] is True
    assert payload["boxes_synthetic"] is True
    assert payload["connection_type"] in ("SAME_TERMINAL", "INTER_TERMINAL")


def test_excluded_options_name_the_assumption_rather_than_asserting_it():
    trace = run_trace().trace
    ruled_out = [
        s.payload["summary"]
        for s in trace.steps
        if "ruled out" in str(s.payload.get("summary", ""))
    ]
    assert ruled_out
    for line in ruled_out:
        assert line.startswith("under the configured reference transfer scenario")
        assert "assumed" in line
        assert "modelled cutoff" in line


def test_no_generated_trace_text_asserts_a_synthetic_figure_as_confirmed():
    """Regression guard. Model-written rationale is constrained by prompt; every
    other line in the trace is ours and must survive this."""
    trace = run_trace().trace
    for step in trace.steps:
        text = str(step.payload.get("summary", "")).lower()
        for phrase in ASSERTIVE:
            assert phrase not in text, f"step {step.seq} asserts: {text[:80]}"


def test_the_deliberation_prompt_carries_the_constraint():
    """The model's rationale is the one line we cannot lint, so the instruction
    has to be in the prompt and has to stay there."""
    from latch.deliberation import DELIBERATION_SYSTEM

    lowered = DELIBERATION_SYSTEM.lower()
    assert "configured scenario" in lowered
    assert "psa confirmed" in lowered, "the counter-example is what makes it land"
    assert "audit trail" in lowered
