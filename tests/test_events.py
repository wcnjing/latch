"""A-to-B contract tests. These pin the format A and B agreed on."""

import json
from pathlib import Path

import pytest

from latch.events import (
    ReasonCode,
    RiskEvent,
    RiskSeverity,
    WatcherConfidence,
)
from latch.models import SourceKind

AGREED = {
    "connection_id": "DEMO-001",
    "state": "AT_RISK",
    "current_plan_slack_hours": -1.8,
    "no_itt_slack_hours": 2.4,
    "avoidable_by_terminal_prevention": True,
    "affected_boxes": 84,
    "confidence": "MEDIUM",
    "reason_codes": ["INBOUND_ETA_SLIP", "INTER_TERMINAL_TRANSFER_TIME"],
}


def test_parses_the_agreed_format_exactly_as_written():
    event = RiskEvent.from_dict(AGREED)
    assert event.connection_id == "DEMO-001"
    assert event.state is RiskSeverity.AT_RISK
    assert event.watcher_confidence is WatcherConfidence.MEDIUM
    assert event.reason_codes == (
        ReasonCode.INBOUND_ETA_SLIP,
        ReasonCode.INTER_TERMINAL_TRANSFER_TIME,
    )


def test_round_trips_through_json():
    event = RiskEvent.from_dict(AGREED)
    assert RiskEvent.from_dict(json.loads(json.dumps(event.to_dict()))) == event


def test_unknown_reason_code_fails_loudly():
    """A silently-dropped code would change which rungs are considered without
    anyone noticing."""
    payload = AGREED | {"reason_codes": ["INBOUND_ETA_SLIP", "SOMETHING_NEW"]}
    with pytest.raises(ValueError):
        RiskEvent.from_dict(payload)


def test_itt_cost_is_the_gap_between_the_two_slack_figures():
    event = RiskEvent.from_dict(AGREED)
    assert event.itt_cost_hours == pytest.approx(4.2)
    assert event.slack_deficit_hours == pytest.approx(1.8)


def test_itt_is_the_problem_when_removing_it_would_save_the_connection():
    """The single most useful signal A sends: it decides whether Rung 1 is a
    live option or merely advisory noise."""
    avoidable = RiskEvent.from_dict(AGREED)
    assert avoidable.itt_is_the_problem

    not_avoidable = RiskEvent.from_dict(
        AGREED
        | {
            "no_itt_slack_hours": -0.9,
            "avoidable_by_terminal_prevention": False,
        }
    )
    assert not not_avoidable.itt_is_the_problem


def test_already_fitting_connection_is_not_an_itt_problem():
    """Positive slack means nothing needs preventing, whatever the flag says."""
    fits = RiskEvent.from_dict(
        AGREED | {"current_plan_slack_hours": 3.0, "state": "WATCH"}
    )
    assert not fits.itt_is_the_problem


def test_safe_events_are_not_actionable():
    assert not RiskEvent.from_dict(AGREED | {"state": "SAFE"}).is_actionable
    assert RiskEvent.from_dict(AGREED | {"state": "WATCH"}).is_actionable


def test_negative_slack_floors_rather_than_inverting_priority():
    """An already-blown connection should be maximally urgent, not negatively
    urgent — a sign flip here would sort it below everything else."""
    blown = RiskEvent.from_dict(AGREED | {"current_plan_slack_hours": -8.0})
    assert blown.priority > 0
    assert blown.priority == pytest.approx(84 / 0.25)


def test_watcher_confidence_is_an_input_not_an_override():
    """A's confidence and a Plan's confidence are different things. A HIGH from
    the Watcher must not be able to make a plan built on stale data trustworthy."""
    high = RiskEvent.from_dict(AGREED | {"confidence": "HIGH"})
    low = RiskEvent.from_dict(AGREED | {"confidence": "LOW"})

    assert high.provenance().source is SourceKind.LIVE_API
    assert low.provenance().source is SourceKind.ASSUMED_DEFAULT
    assert high.provenance().verified
    assert not low.provenance().verified


def test_adapter_marks_what_a_has_not_sent_yet_as_simulated():
    """The gap has to be visible in the trace rather than papered over with a
    plausible-looking default."""
    risk = RiskEvent.from_dict(AGREED).to_connection_risk()
    assert risk.inbound.terminal.value == "unknown"
    assert risk.inbound.terminal_resolution.value == "simulated"
    assert risk.boxes_at_risk == 84
    assert risk.risk_id == "DEMO-001"


def test_optional_enrichment_flows_through_when_a_starts_sending_it():
    """A can add fields without B changing. This is the swap-in test."""
    enriched = RiskEvent.from_dict(
        AGREED
        | {
            "inbound_terminal": "tuas",
            "outbound_terminal": "pasir_panjang",
            "terminal_resolution": "berth",
            "ucid": "UCID-SGSIN-0001",
            "source": "oceans_x.vessel_movements",
        }
    )
    risk = enriched.to_connection_risk()
    assert risk.inbound.terminal.value == "tuas"
    assert risk.inbound.terminal_resolution.value == "berth"
    assert risk.ucid == "UCID-SGSIN-0001"
    assert risk.crosses_terminals


def test_the_four_mock_cases_are_genuinely_different():
    """If they all took the same path they would not be testing anything."""
    path = Path(__file__).resolve().parent.parent / "fixtures" / "mock_events.json"
    events = [RiskEvent.from_dict(p) for p in json.loads(path.read_text())]
    assert len(events) == 4

    by_id = {e.connection_id: e for e in events}
    assert not by_id["DEMO-000"].is_actionable
    assert by_id["DEMO-002"].state is RiskSeverity.WATCH
    assert by_id["DEMO-001"].itt_is_the_problem
    assert not by_id["DEMO-003"].itt_is_the_problem
    assert by_id["DEMO-003"].no_itt_slack_hours < 0
