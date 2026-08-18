"""Triage tests. The funnel has to be free at both ends to be worth having."""

from latch.events import RiskEvent
from latch.llm import FakeModel
from latch.triage import TriageRoute, prefilter, triage

BASE = {
    "connection_id": "T-1",
    "state": "AT_RISK",
    "current_plan_slack_hours": -1.0,
    "no_itt_slack_hours": 2.0,
    "avoidable_by_terminal_prevention": True,
    "affected_boxes": 60,
    "confidence": "MEDIUM",
    "reason_codes": [],
}


def event(**overrides) -> RiskEvent:
    return RiskEvent.from_dict(BASE | overrides)


def model(keep: bool = True) -> FakeModel:
    return FakeModel(
        {"triage": {"worth_deliberating": keep, "reason": "scripted"}}
    )


def test_safe_never_reaches_a_model():
    client = model()
    verdict = triage(event(state="SAFE", current_plan_slack_hours=9.0), client)

    assert not verdict.keep
    assert verdict.route is TriageRoute.DISMISSED_SAFE
    assert verdict.was_free
    assert client.calls == []


def test_tiny_volume_never_reaches_a_model():
    """Below the floor, any move costs more than the miss."""
    client = model()
    verdict = triage(event(affected_boxes=2), client)

    assert not verdict.keep
    assert verdict.route is TriageRoute.DISMISSED_TOO_SMALL
    assert client.calls == []


def test_obviously_critical_skips_the_ask():
    """Eighty boxes already past the window does not need a small model's
    opinion on whether it is serious."""
    client = model()
    verdict = triage(event(affected_boxes=84, current_plan_slack_hours=-1.8), client)

    assert verdict.keep
    assert verdict.route is TriageRoute.FAST_TRACKED
    assert verdict.was_free
    assert client.calls == []


def test_the_ambiguous_middle_is_where_the_model_is_spent():
    client = model(keep=True)
    verdict = triage(event(state="WATCH", current_plan_slack_hours=3.1, affected_boxes=47), client)

    assert verdict.keep
    assert verdict.route is TriageRoute.MODEL_KEPT
    assert verdict.model_used
    assert [c[0] for c in client.calls] == ["triage"]


def test_model_can_dismiss():
    verdict = triage(event(state="WATCH", current_plan_slack_hours=4.0), model(keep=False))
    assert not verdict.keep
    assert verdict.route is TriageRoute.MODEL_DISMISSED


def test_prefilter_returns_none_when_a_judgement_is_needed():
    assert prefilter(event(state="WATCH", current_plan_slack_hours=3.0)) is None


def test_watch_with_large_volume_is_not_fast_tracked():
    """Fast-tracking requires the window to be blown, not merely thinning —
    otherwise the funnel stops filtering anything."""
    verdict = prefilter(event(state="WATCH", affected_boxes=90, current_plan_slack_hours=2.0))
    assert verdict is None


def test_unscripted_purpose_raises_rather_than_improvising():
    """A fake that invents answers would let a test pass against a response the
    real model would never produce."""
    import pytest

    with pytest.raises(KeyError, match="no scripted response"):
        triage(event(state="WATCH", current_plan_slack_hours=3.0), FakeModel({}))
