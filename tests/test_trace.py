"""Trace store tests, with cost priced at real Anthropic rates."""

import json

import pytest

from latch.models import Resolution
from latch.trace import ModelCall, Trace, TraceStore
from tests.conftest import T0, make_risk

from datetime import timedelta


def test_cost_uses_real_pricing():
    """haiku-4-5 is $1/$5 per MTok; opus-5 is $5/$25."""
    triage = ModelCall("claude-haiku-4-5", input_tokens=8_000, output_tokens=400)
    assert triage.usd == pytest.approx(0.010)

    deliberation = ModelCall("claude-opus-5", input_tokens=2_240, output_tokens=980)
    assert deliberation.usd == pytest.approx(0.0357)


def test_unpriced_model_raises_rather_than_reporting_zero():
    """A decision carrying a silently-free model call would make the whole cost
    narrative worthless."""
    with pytest.raises(KeyError, match="no pricing"):
        ModelCall("claude-imaginary-9", 100, 100).usd


def test_trace_accumulates_cost_across_the_funnel(risk):
    trace = Trace.for_risk(risk)
    trace.model_call("claude-haiku-4-5", 8_000, 400, purpose="triage")
    trace.model_call("claude-opus-5", 2_240, 980, purpose="deliberation")

    assert trace.cost.usd == pytest.approx(0.0457)
    assert trace.cost.input_tokens == 10_240
    assert trace.cost.output_tokens == 1_380
    assert trace.cost.as_dict()["by_model"]["claude-opus-5"] == pytest.approx(0.0357)


def test_steps_are_sequential_and_append_only(risk):
    trace = Trace.for_risk(risk)
    trace.observation("slack 1h50m, consumed 85%")
    trace.decision(rung="rung_3_move", chosen=True, confidence=0.88)
    trace.lock("itt_slot:1140", status="lost", our_priority=18.6, winner_priority=41.2)

    assert [s.seq for s in trace.steps] == [1, 2, 3]
    assert [s.type for s in trace.steps] == ["observation", "decision", "lock"]


def test_trigger_records_how_the_terminal_was_resolved(risk):
    """Provenance of the inter-terminal split, on every trace, by construction."""
    trace = Trace.for_risk(risk)
    assert trace.trigger["terminal_resolution"] == "terminal"
    assert trace.trigger["source"] == "oceans_x.vessel_movements"


def test_lapsed_window_is_recorded_as_a_failure(risk):
    trace = Trace.for_risk(risk)
    trace.external_gate(
        party="line", options_sent=3, window_min=180, outcome="LAPSED_NO_RESPONSE"
    )
    trace.close(Resolution.WINDOW_LAPSED_NO_RESPONSE, options_alive=3)

    payload = trace.as_dict()
    assert payload["outcome"]["resolution"] == "window_lapsed_no_response"
    assert payload["outcome"]["service_success"] is False


def test_declining_everything_is_recorded_as_service(risk):
    trace = Trace.for_risk(risk)
    trace.close(Resolution.CUSTOMER_DECLINED_ALL, options_alive=2)
    assert trace.as_dict()["outcome"]["service_success"] is True


def test_decision_lead_time_measured_from_detection_to_offer(risk):
    trace = Trace.for_risk(risk)
    trace.close(
        Resolution.CUSTOMER_DECIDED,
        offer_sent_at=T0 + timedelta(hours=6, minutes=12),
        options_alive=3,
    )
    assert trace.decision_lead_time_h == pytest.approx(6.2)


def test_decision_lead_time_is_none_when_no_offer_was_sent(risk):
    """Worth knowing rather than papering over with a zero."""
    trace = Trace.for_risk(risk)
    trace.close(Resolution.CONNECTION_HELD)
    assert trace.decision_lead_time_h is None
    assert trace.as_dict()["outcome"]["decision_lead_time_h"] is None


def test_trace_matches_the_published_schema_shape(risk):
    trace = Trace.for_risk(risk)
    trace.observation("detected")
    trace.close(Resolution.CONNECTION_HELD)

    payload = trace.as_dict()
    assert set(payload) == {
        "trace_id",
        "risk_id",
        "ucid",
        "trigger",
        "steps",
        "outcome",
        "cost",
    }
    assert set(payload["cost"]) == {
        "model_calls",
        "input_tokens",
        "output_tokens",
        "usd",
        "by_model",
    }
    # C's console parses this; it has to survive a round trip.
    assert json.loads(json.dumps(payload))["trace_id"] == trace.trace_id


def test_store_refuses_to_reopen_a_trace(risk):
    store = TraceStore()
    store.open(risk)
    with pytest.raises(ValueError, match="already open"):
        store.open(risk)


def test_service_rate_counts_declines_as_served():
    store = TraceStore()
    outcomes = [
        Resolution.CUSTOMER_DECIDED,
        Resolution.CUSTOMER_DECLINED_ALL,
        Resolution.WINDOW_LAPSED_NO_RESPONSE,
        Resolution.CONNECTION_HELD,
    ]
    for i, outcome in enumerate(outcomes):
        trace = store.open(make_risk(risk_id=f"cr_{i:04d}"))
        trace.close(outcome)

    assert store.service_rate() == pytest.approx(0.75)


def test_service_rate_is_none_before_anything_closes(risk):
    store = TraceStore()
    store.open(risk)
    assert store.service_rate() is None


def test_flush_appends_one_line_per_trace(tmp_path, risk):
    sink = tmp_path / "traces" / "run.jsonl"
    store = TraceStore(sink=sink)

    trace = store.open(risk)
    trace.close(Resolution.CONNECTION_HELD)
    store.flush(trace)
    store.flush(trace)

    lines = sink.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["risk_id"] == risk.risk_id
