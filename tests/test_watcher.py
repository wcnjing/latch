"""A-to-B bridge tests. The seam that had never existed in one tree."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from latch.connections import ConnectionParams, connection_for
from latch.events import ReasonCode, RiskSeverity, WatcherConfidence
from latch.models import TerminalResolution
from latch.watcher import (
    ArrivalSignal,
    compute_slack,
    events_from_signals,
    to_risk_event,
)

T0 = datetime(2023, 10, 1, tzinfo=UTC)


@dataclass
class FakeSignal:
    """Stands in for A's CausalArrivalUpdate. Only the protocol fields matter."""

    call_id: str = "call_abc123def456"
    vessel_id: str = "v1"
    observed_at: datetime = T0
    predicted_arrival: datetime | None = T0 + timedelta(hours=2)
    reference_arrival: datetime | None = T0 + timedelta(hours=2)
    data_quality: str = "good"
    quality_reason_codes: tuple[str, ...] = ()


def conn(call_id: str = "call_abc123def456", **kw):
    return connection_for(call_id, "v1", T0 + timedelta(hours=2), ConnectionParams(**kw))


def test_a_signal_satisfies_the_structural_protocol():
    """A can rename or extend its class; only these fields are load-bearing."""
    assert isinstance(FakeSignal(), ArrivalSignal)


def test_no_prediction_yields_no_event():
    """An ineligible observation is not an arrival at an unknown time — it is
    no estimate at all. Substituting one would invent what A refused to guess."""
    signal = FakeSignal(predicted_arrival=None)
    assert compute_slack(signal, conn()) is None
    assert to_risk_event(signal, conn()) is None


def test_slack_shrinks_as_the_vessel_slips():
    """The core behaviour. The cutoff is anchored to the *original* expected
    arrival, so a later prediction eats into slack rather than moving the window."""
    connection = conn()
    early = to_risk_event(FakeSignal(), connection)
    late = to_risk_event(
        FakeSignal(predicted_arrival=T0 + timedelta(hours=9)), connection
    )

    assert late.current_plan_slack_hours < early.current_plan_slack_hours
    assert late.no_itt_slack_hours < early.no_itt_slack_hours


def test_a_slipping_vessel_eventually_becomes_at_risk():
    # Window pinned wide so the run starts SAFE regardless of which window the
    # hash would have drawn — the progression is what is under test, not the
    # synthetic draw.
    connection = conn(min_connection_window_h=32.0, max_connection_window_h=34.0)

    # Slip fractions of the connection's own window rather than fixed hours,
    # so the progression still spans SAFE to AT_RISK if the params change.
    window_h = (connection.outbound_cutoff - T0).total_seconds() / 3600.0
    slips = [window_h * f for f in (0.05, 0.35, 0.65, 0.85, 1.05)]
    states = [
        to_risk_event(
            FakeSignal(predicted_arrival=T0 + timedelta(hours=h)), connection
        ).state
        for h in slips
    ]
    assert states[0] is RiskSeverity.SAFE
    assert RiskSeverity.AT_RISK in states
    # severity is monotone: it never recovers while the vessel keeps slipping
    order = [RiskSeverity.SAFE, RiskSeverity.WATCH, RiskSeverity.AT_RISK]
    assert [order.index(s) for s in states] == sorted(order.index(s) for s in states)


def first_matching(requires_transfer: bool):
    """Find a call id whose synthetic connection has the shape we need.

    Deterministic search rather than a hardcoded id, so the test keeps working
    if the generator changes — and skips nothing.
    """
    for i in range(200):
        candidate = connection_for(f"call_probe_{i}", "v1", T0 + timedelta(hours=2))
        if candidate.requires_transfer is requires_transfer:
            return candidate
    raise AssertionError(f"no connection found with requires_transfer={requires_transfer}")


def test_transfer_time_is_the_gap_between_the_two_slack_figures():
    """This is the signal the whole ladder turns on, so it has to be exact."""
    transferring = first_matching(requires_transfer=True)

    event = to_risk_event(FakeSignal(call_id=transferring.call_id), transferring)
    gap = event.no_itt_slack_hours - event.current_plan_slack_hours
    assert gap == pytest.approx(transferring.params.planned_transfer_h)
    assert event.itt_cost_hours == pytest.approx(gap)


def test_same_terminal_connection_has_no_transfer_cost():
    same = first_matching(requires_transfer=False)
    event = to_risk_event(FakeSignal(call_id=same.call_id), same)
    assert event.no_itt_slack_hours == pytest.approx(event.current_plan_slack_hours)
    assert not event.avoidable_by_terminal_prevention


def test_terminals_are_declared_simulated():
    """They came from the synthetic layer, and that lowers confidence
    downstream. Enforced by the pipeline rather than asserted on a slide."""
    event = to_risk_event(FakeSignal(), conn())
    assert event.terminal_resolution is TerminalResolution.SIMULATED
    assert event.to_connection_risk().inbound.terminal_resolution is (
        TerminalResolution.SIMULATED
    )


def test_watcher_confidence_follows_a_data_quality():
    for quality, expected in (
        ("good", WatcherConfidence.HIGH),
        ("degraded", WatcherConfidence.MEDIUM),
        ("excluded", WatcherConfidence.LOW),
    ):
        event = to_risk_event(FakeSignal(data_quality=quality), conn())
        assert event.watcher_confidence is expected


def test_unknown_quality_gets_no_benefit_of_the_doubt():
    """Absent or unrecognised provenance is weaker than stated-poor provenance."""
    assert (
        to_risk_event(FakeSignal(data_quality="something_new"), conn()).watcher_confidence
        is WatcherConfidence.LOW
    )


def test_eta_slip_is_reported_only_when_it_exceeds_noise():
    connection = conn()
    steady = to_risk_event(FakeSignal(), connection)
    assert ReasonCode.INBOUND_ETA_SLIP not in steady.reason_codes

    slipped = to_risk_event(
        FakeSignal(predicted_arrival=T0 + timedelta(hours=5)), connection
    )
    assert ReasonCode.INBOUND_ETA_SLIP in slipped.reason_codes


def test_data_quality_codes_are_not_smuggled_in_as_causes():
    """They describe how good the observation was, not why cargo is at risk,
    and they already reach the agent through confidence. Folding them in would
    double-count uncertainty as causation."""
    event = to_risk_event(
        FakeSignal(quality_reason_codes=("stale_observation", "long_observation_gap")),
        conn(),
    )
    assert all(isinstance(c, ReasonCode) for c in event.reason_codes)
    assert "stale_observation" not in [c.value for c in event.reason_codes]


def test_one_connection_per_call_across_its_updates():
    """Regenerating per update would move the cutoff with the vessel and no
    connection would ever come under threat."""
    signals = [
        FakeSignal(
            observed_at=T0 + timedelta(hours=h),
            predicted_arrival=T0 + timedelta(hours=2 + h),
        )
        for h in range(6)
    ]
    events = list(events_from_signals(signals))
    assert len({e.ucid for e in events}) == 1
    slacks = [e.current_plan_slack_hours for e in events]
    assert slacks == sorted(slacks, reverse=True)


def test_signals_without_any_anchor_are_skipped():
    signals = [FakeSignal(predicted_arrival=None, reference_arrival=None)]
    assert list(events_from_signals(signals)) == []


def test_adapted_events_reach_the_agent_end_to_end():
    """The whole point: real-shaped arrival timing to an agent decision."""
    from latch.llm import FakeModel
    from latch.runner import AutoApprove, CustomerAccepts, handle
    from latch.trace import TraceStore

    connection = conn()
    event = to_risk_event(
        FakeSignal(predicted_arrival=T0 + timedelta(hours=20)), connection
    )
    assert event.state is RiskSeverity.AT_RISK

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
    outcome = handle(
        event,
        client=client,
        store=TraceStore(),
        approvals=AutoApprove(),
        customer=CustomerAccepts(),
    )
    assert outcome.resolution is not None
    assert outcome.trace.trigger["terminal_resolution"] == "simulated"
