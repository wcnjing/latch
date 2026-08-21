"""Case registry tests. One connection, one live case."""

import pytest

from latch.cases import Admission, CaseRegistry
from latch.events import RiskEvent


def event(slack: float, state: str = "AT_RISK", cid: str = "conn_1") -> RiskEvent:
    return RiskEvent.from_dict(
        {
            "connection_id": cid,
            "state": state,
            "current_plan_slack_hours": slack,
            "no_itt_slack_hours": slack + 1.5,
            "avoidable_by_terminal_prevention": True,
            "affected_boxes": 60,
            "confidence": "HIGH",
            "reason_codes": [],
        }
    )


def test_first_sighting_is_new_work():
    registry = CaseRegistry()
    decision = registry.admit(event(-1.0))
    assert decision.admission is Admission.NEW
    assert decision.should_process
    assert not decision.closes_previous


def test_jitter_does_not_re_run_the_ladder():
    """The expensive model must not be spent on an ETA estimate wobbling."""
    registry = CaseRegistry(slack_delta_h=0.5)
    registry.admit(event(-1.0))

    decision = registry.admit(event(-1.2))
    assert decision.admission is Admission.DUPLICATE
    assert not decision.should_process


def test_material_slip_supersedes_and_reprocesses():
    registry = CaseRegistry(slack_delta_h=0.5)
    registry.admit(event(-1.0))
    registry.opened("conn_1", "trace_a")

    decision = registry.admit(event(-4.0))
    assert decision.admission is Admission.SUPERSEDES
    assert decision.should_process
    assert decision.superseded_trace_id == "trace_a"


def test_severity_change_is_always_material():
    """WATCH to AT_RISK matters even if the slack move is small."""
    registry = CaseRegistry(slack_delta_h=5.0)
    registry.admit(event(0.2, state="WATCH"))

    decision = registry.admit(event(-0.1, state="AT_RISK"))
    assert decision.admission is Admission.SUPERSEDES


def test_recovery_closes_the_case_without_reprocessing():
    """ETA improved mid-flight. Abandon cleanly — this is what SUPERSEDED is for."""
    registry = CaseRegistry()
    registry.admit(event(-1.0))
    registry.opened("conn_1", "trace_a")

    decision = registry.admit(event(9.0, state="SAFE"))
    assert decision.admission is Admission.RECOVERED
    assert not decision.should_process
    assert decision.superseded_trace_id == "trace_a"
    assert registry.in_flight() == 0


def test_safe_events_never_open_a_case():
    """65% of traffic is fine. Admitting it would fill the registry with it."""
    registry = CaseRegistry()
    decision = registry.admit(event(9.0, state="SAFE"))
    assert not decision.should_process
    assert registry.in_flight() == 0


def test_resolved_case_ignores_events_that_are_not_worse():
    registry = CaseRegistry()
    registry.admit(event(-1.0))
    registry.resolved("conn_1")

    decision = registry.admit(event(-1.1))
    assert decision.admission is Admission.ALREADY_RESOLVED
    assert not decision.should_process


def test_resolved_case_reopens_when_the_vessel_slips_further():
    """We booked a transfer and the vessel slipped three more hours. The
    earlier decision may no longer hold, so this is genuinely new work."""
    registry = CaseRegistry()
    registry.admit(event(-1.0))
    registry.resolved("conn_1")

    decision = registry.admit(event(-4.0))
    assert decision.admission is Admission.NEW
    assert decision.should_process
    assert "after we acted" in decision.reason


def test_connections_are_tracked_independently():
    registry = CaseRegistry()
    assert registry.admit(event(-1.0, cid="conn_1")).admission is Admission.NEW
    assert registry.admit(event(-1.0, cid="conn_2")).admission is Admission.NEW
    assert registry.in_flight() == 2


def test_jittering_estimate_collapses_to_one_case():
    """The bug this exists for: a connection under pressure emits an event
    every Watcher cycle, and without this each one walks the whole ladder.

    Here the estimate wobbles either side of the same value with no net drift,
    which is noise and must produce exactly one case."""
    registry = CaseRegistry(slack_delta_h=0.5)
    wobble = [-1.0, -1.2, -0.9, -1.1, -1.0, -1.3, -0.8, -1.1, -1.0]
    decisions = [registry.admit(event(s)) for s in wobble]

    assert len([d for d in decisions if d.should_process]) == 1
    assert registry.counts["duplicate"] == len(wobble) - 1


def test_steady_drift_re_triggers_but_far_less_often_than_it_polls():
    """A connection sliding 0.1h per poll is genuinely degrading, so it must
    re-trigger — comparison is against the last *admitted* slack, so cumulative
    drift crosses the threshold. If it never re-triggered, a slow steady slide
    would be invisible."""
    registry = CaseRegistry(slack_delta_h=0.5)
    decisions = [registry.admit(event(-1.0 - 0.1 * i)) for i in range(30)]

    processed = [d for d in decisions if d.should_process]
    assert 1 < len(processed) <= 6, "should re-trigger, but nothing like per-poll"
    assert all(
        d.admission is Admission.SUPERSEDES for d in processed[1:]
    )


def test_counts_account_for_every_event():
    registry = CaseRegistry()
    for slack in (-1.0, -1.1, -6.0, 9.0):
        registry.admit(event(slack, state="SAFE" if slack > 0 else "AT_RISK"))
    assert sum(registry.counts.values()) == 4
