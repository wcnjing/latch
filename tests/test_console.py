"""Console view-model tests. This is the B-to-C seam."""

import json

import pytest

from latch.console import approvals_view, case_view, confidence_panel, ladder_view
from latch.events import RiskEvent
from latch.llm import FakeModel
from latch.runner import CustomerSilent, handle
from latch.tools import CacheEntry, ScriptedFailures, ToolStatus
from latch.trace import TraceStore

CLEAN = {
    "connection_id": "V-1",
    "state": "AT_RISK",
    "current_plan_slack_hours": -0.5,
    "no_itt_slack_hours": 6.0,
    "avoidable_by_terminal_prevention": True,
    "affected_boxes": 20,
    "confidence": "HIGH",
    "reason_codes": ["INBOUND_ETA_SLIP"],
}


def run(payload=None, **kwargs):
    event = RiskEvent.from_dict(payload or CLEAN)
    client = FakeModel(
        {
            "triage": {"worth_deliberating": True, "reason": "scripted"},
            "deliberation": {
                "chosen_plan_id": "",
                "ranking": [],
                "rationale": "Road arrives in time.",
            },
        }
    )
    kwargs.setdefault("customer", CustomerSilent())
    return handle(event, client=client, store=TraceStore(), **kwargs).trace


def degraded():
    return run(
        failures=ScriptedFailures(
            {"query_itt_slot": [ToolStatus.TIMEOUT, ToolStatus.TIMEOUT]}
        ),
        itt_cache=CacheEntry(value=[], age_min=8.0),
    )


def test_waterfall_multiplies_down_to_the_reported_value():
    """If the steps do not reconstruct the number, the panel is decoration."""
    panel = confidence_panel(degraded())

    running = 1.0
    for step in panel.waterfall:
        running = running * step.factor if step.kind == "multiply" else running - step.factor
    assert running == pytest.approx(panel.value, abs=1e-3)


def test_waterfall_names_every_factor_that_moved_the_number():
    panel = confidence_panel(degraded())
    labels = [w.label for w in panel.waterfall]
    assert labels == ["Source", "Data age", "Tool outcome", "Unverified inputs"]
    assert all(w.detail for w in panel.waterfall)


def test_panel_says_whether_it_crossed_the_threshold():
    """The screen has to answer 'so what' without the reader doing arithmetic."""
    panel = confidence_panel(degraded())
    assert panel.crosses_threshold
    assert panel.band == "escalate"
    assert "escalated" in panel.headline

    clean = confidence_panel(run())
    assert not clean.crosses_threshold
    assert clean.band == "auto"


def test_panel_is_none_when_nothing_was_scored():
    """A dismissed risk never gets a confidence score, and the console must not
    render a zero as though it had."""
    dismissed = run(CLEAN | {"state": "SAFE", "current_plan_slack_hours": 9.0})
    assert confidence_panel(dismissed) is None
    assert case_view(dismissed)["confidence"] is None


def test_ladder_shows_what_was_ruled_out_not_only_what_survived():
    """A ladder showing only survivors reads as an agent that never considered
    the alternatives."""
    tight = run(CLEAN | {"no_itt_slack_hours": 2.4, "current_plan_slack_hours": -1.8})
    statuses = {row.status for row in ladder_view(tight)}
    assert "ruled_out" in statuses
    assert any("barge" in row.detail for row in ladder_view(tight))


def test_advisories_are_marked_as_not_chosen():
    """Rung 1 changes nothing on its own. If the console shows it as the action,
    an operator reads a stranded connection as handled."""
    rows = ladder_view(run())
    advisories = [r for r in rows if r.status == "advisory"]
    chosen = [r for r in rows if r.status == "chosen"]
    assert advisories
    assert all(r.rung != "rung_1_inform" for r in chosen)


def test_approvals_expose_the_role_and_the_reason():
    panel = approvals_view(degraded())
    assert panel
    assert panel[-1].role
    assert panel[-1].escalated
    assert "confidence" in panel[-1].reason


def test_case_view_carries_the_service_distinction():
    """A rolled box is not the same as an unserved customer, and the payload
    has to say which."""
    view = case_view(run())
    assert "service_success" in view
    assert view["resolution"] is not None


def test_case_view_is_json_serialisable():
    """C parses this over the wire; a dataclass that will not serialise is not
    a contract."""
    view = case_view(degraded())
    assert json.loads(json.dumps(view))["trace_id"] == view["trace_id"]
    assert view["confidence"]["waterfall"]


def test_case_view_reports_the_customer_gate_when_one_opened():
    hopeless = run(
        CLEAN
        | {
            "current_plan_slack_hours": -3.0,
            "no_itt_slack_hours": -1.0,
            "avoidable_by_terminal_prevention": False,
        }
    )
    gate = case_view(hopeless)["customer_gate"]
    assert gate is not None
    assert gate["outcome"] == "LAPSED_NO_RESPONSE"
