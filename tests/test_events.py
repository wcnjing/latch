"""A-to-B contract tests. These pin the format A and B agreed on."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from latch.events import (
    Assumptions,
    ConnectionType,
    ReasonCode,
    RiskEvent,
    RiskSeverity,
    TimingResolution,
    WatcherConfidence,
)
from latch.models import SourceKind, Terminal, TerminalResolution

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

CAUSAL_DETECTED_AT = "2026-08-25T12:00:00+00:00"
CAUSAL_TIMING = {
    "inbound_reference_arrival": "2026-08-25T17:00:00+00:00",
    "inbound_predicted_arrival": "2026-08-25T19:00:00+00:00",
    "outbound_reference_arrival": "2026-08-26T02:00:00+00:00",
    "outbound_predicted_arrival": "2026-08-26T03:00:00+00:00",
}


def causal_payload(**overrides):
    return (
        AGREED
        | {
            "timing_resolution": "derived_causal_arrival",
            "detected_at": CAUSAL_DETECTED_AT,
        }
        | CAUSAL_TIMING
        | overrides
    )


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


def test_old_payload_without_timing_resolution_decodes_explicitly_as_legacy():
    event = RiskEvent.from_dict(AGREED)

    assert event.timing_resolution is TimingResolution.LEGACY_SLACK_FALLBACK


def test_old_causal_payload_without_timing_resolution_infers_causal_arrival():
    payload = causal_payload()
    del payload["timing_resolution"]

    event = RiskEvent.from_dict(payload)

    assert event.timing_resolution is TimingResolution.DERIVED_CAUSAL_ARRIVAL


def test_old_payload_without_timing_resolution_rejects_partial_causal_timing():
    with pytest.raises(ValueError, match="partial causal vessel timing"):
        RiskEvent.from_dict(
            AGREED
            | {
                "detected_at": CAUSAL_DETECTED_AT,
                "inbound_reference_arrival": CAUSAL_TIMING[
                    "inbound_reference_arrival"
                ],
            }
        )


def test_to_dict_always_emits_timing_resolution():
    legacy = RiskEvent.from_dict(AGREED)
    causal = RiskEvent.from_dict(causal_payload())

    assert legacy.to_dict()["timing_resolution"] == "legacy_slack_fallback"
    assert causal.to_dict()["timing_resolution"] == "derived_causal_arrival"


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


def test_itt_counterfactual_uses_strict_current_and_inclusive_no_itt_boundaries():
    rescued_at_zero = RiskEvent.from_dict(
        AGREED
        | {
            "current_plan_slack_hours": -1.0,
            "no_itt_slack_hours": 0.0,
        }
    )
    exactly_at_current_cutoff = RiskEvent.from_dict(
        AGREED
        | {
            "current_plan_slack_hours": 0.0,
            "no_itt_slack_hours": 2.0,
        }
    )
    assert rescued_at_zero.itt_is_the_problem
    assert not exactly_at_current_cutoff.itt_is_the_problem


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


def test_pr4_enrichment_round_trip_maps_supplied_derived_causal_times():
    assessed_at = datetime(2026, 8, 25, 12, tzinfo=UTC)
    inbound_reference = assessed_at + timedelta(hours=5)
    inbound_prediction = inbound_reference + timedelta(hours=2)
    outbound_reference = assessed_at + timedelta(hours=14)
    outbound_prediction = outbound_reference + timedelta(hours=1)
    event = RiskEvent(
        connection_id="UCID-SGSIN-0001-ABCDEF",
        state=RiskSeverity.AT_RISK,
        current_plan_slack_hours=-1.0,
        no_itt_slack_hours=0.0,
        avoidable_by_terminal_prevention=True,
        affected_boxes=24,
        watcher_confidence=WatcherConfidence.MEDIUM,
        timing_resolution=TimingResolution.DERIVED_CAUSAL_ARRIVAL,
        reason_codes=(
            ReasonCode.INBOUND_ETA_SLIP,
            ReasonCode.INTER_TERMINAL_TRANSFER_TIME,
        ),
        detected_at=assessed_at,
        ucid="UCID-SGSIN-0001-ABCDEF",
        inbound_terminal=Terminal.TUAS,
        outbound_terminal=Terminal.PASIR_PANJANG,
        terminal_resolution=TerminalResolution.SIMULATED,
        assumptions=Assumptions(
            connection_type=ConnectionType.INTER_TERMINAL,
            transfer_scenario=(
                "synthetic PR #3 reference process scenario; not a PSA operating rule"
            ),
        ),
        inbound_vessel="inbound-vessel",
        outbound_vessel="outbound-vessel",
        source="real_ais_causal_predictions+synthetic_pr3_connection",
        inbound_reference_arrival=inbound_reference,
        inbound_predicted_arrival=inbound_prediction,
        outbound_reference_arrival=outbound_reference,
        outbound_predicted_arrival=outbound_prediction,
    )

    restored = RiskEvent.from_dict(json.loads(json.dumps(event.to_dict())))
    risk = restored.to_connection_risk()

    assert restored == event
    assert risk.ucid == event.ucid
    assert risk.inbound.scheduled == inbound_reference
    assert risk.inbound.estimated == inbound_prediction
    assert risk.outbound.scheduled == outbound_reference
    assert risk.outbound.estimated == outbound_prediction
    assert restored.assumptions.any_synthetic
    assert "not a PSA operating rule" in restored.assumptions.transfer_scenario


@pytest.mark.parametrize("supplied_count", range(4))
def test_causal_provenance_rejects_zero_to_three_timing_fields(supplied_count):
    partial = dict(list(CAUSAL_TIMING.items())[:supplied_count])

    with pytest.raises(ValueError, match="requires all four arrivals"):
        RiskEvent.from_dict(
            AGREED
            | {
                "timing_resolution": "derived_causal_arrival",
                "detected_at": CAUSAL_DETECTED_AT,
            }
            | partial
        )


@pytest.mark.parametrize("field_name", ["detected_at", *CAUSAL_TIMING])
def test_causal_provenance_rejects_naive_datetimes(field_name):
    payload = causal_payload()
    payload[field_name] = payload[field_name].replace("+00:00", "")

    with pytest.raises(ValueError, match=rf"{field_name} must be timezone-aware"):
        RiskEvent.from_dict(payload)


def test_causal_provenance_rejects_missing_detected_at():
    payload = causal_payload()
    del payload["detected_at"]

    with pytest.raises(ValueError, match="requires detected_at"):
        RiskEvent.from_dict(payload)


@pytest.mark.parametrize("field_name", CAUSAL_TIMING)
def test_legacy_provenance_rejects_supplied_causal_timing(field_name):
    with pytest.raises(ValueError, match="must not include causal vessel timing"):
        RiskEvent.from_dict(
            AGREED
            | {
                "timing_resolution": "legacy_slack_fallback",
                field_name: CAUSAL_TIMING[field_name],
            }
        )


def test_legacy_event_without_causal_times_keeps_adapter_fallback():
    event = RiskEvent.from_dict(AGREED | {"detected_at": "2026-08-25T12:00:00+00:00"})
    risk = event.to_connection_risk()
    expected_detected = datetime(2026, 8, 25, 12, tzinfo=UTC)

    assert event.timing_resolution is TimingResolution.LEGACY_SLACK_FALLBACK
    assert event.inbound_reference_arrival is None
    assert risk.inbound.scheduled == expected_detected
    assert risk.inbound.estimated == expected_detected + timedelta(hours=1.8)
    assert risk.outbound.scheduled == expected_detected + timedelta(hours=2.4)
    assert risk.outbound.estimated == expected_detected + timedelta(hours=2.4)


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
