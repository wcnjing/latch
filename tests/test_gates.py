"""Gate Controller tests.

The first test is the structural one. The rest check the policy table.
"""

import inspect

import pytest

from latch import gates
from latch.gates import LADDERS, evaluate
from latch.models import ApprovalRole, Plan, Rung


def plan(rung: Rung, confidence: float = 0.95, cost: float = 400.0) -> Plan:
    return Plan(
        plan_id="p",
        risk_id="r",
        rung=rung,
        actions=(),
        rationale="",
        cost_sgd=cost,
        confidence=confidence,
    )


def test_the_gate_has_no_channel_through_which_to_be_persuaded():
    """The structural argument, asserted rather than claimed.

    An agent that can talk its way into a higher approval level has no
    meaningful approval level. This module takes no model client and imports
    none, so there is nothing for a rationale to act on.
    """
    source = inspect.getsource(gates)
    assert "ModelClient" not in source
    assert "llm" not in source
    assert "rationale" not in inspect.signature(evaluate).parameters


def test_confident_small_move_is_auto_approved():
    decision = evaluate(plan(Rung.MOVE), boxes_at_risk=20)
    assert decision.required_role is ApprovalRole.AUTO
    assert not decision.escalated
    assert not decision.blocks


def test_volume_escalates():
    decision = evaluate(plan(Rung.MOVE), boxes_at_risk=84)
    assert decision.required_role is ApprovalRole.VESSEL_OPS
    assert "84 boxes" in decision.escalation_reason
    assert decision.blocks


def test_low_confidence_escalates_on_its_own():
    decision = evaluate(plan(Rung.MOVE, confidence=0.62), boxes_at_risk=20)
    assert decision.required_role is ApprovalRole.VESSEL_OPS
    assert "confidence 0.62" in decision.escalation_reason


def test_escalations_compound_up_the_ladder():
    decision = evaluate(plan(Rung.MOVE, confidence=0.62, cost=12_000), boxes_at_risk=84)
    assert decision.required_role is ApprovalRole.DUTY_MANAGER
    assert decision.escalation_reason.count(";") == 2


def test_cost_gate_is_independent_of_the_volume_gate():
    """At SGD 2,000 the cost gate fired at roughly 42 road boxes, which the
    40-box volume gate already caught — two criteria carrying one signal, so
    every large move escalated twice. They have to be able to fire alone."""
    volume_only = evaluate(plan(Rung.MOVE, cost=4_032), boxes_at_risk=84)
    assert volume_only.required_role is ApprovalRole.VESSEL_OPS
    assert "cost" not in volume_only.escalation_reason

    cost_only = evaluate(plan(Rung.MOVE, cost=12_000), boxes_at_risk=20)
    assert cost_only.required_role is ApprovalRole.VESSEL_OPS
    assert "boxes" not in cost_only.escalation_reason


def test_escalation_stops_at_the_top_rather_than_wrapping():
    decision = evaluate(plan(Rung.MOVE, confidence=0.05, cost=1e9), boxes_at_risk=99_999)
    assert decision.required_role is ApprovalRole.DUTY_MANAGER


def test_rung_one_never_blocks_whatever_the_numbers_say():
    """It surfaces a number to a planner who was already going to decide.
    Escalating an advisory would just train people to ignore the gate."""
    decision = evaluate(plan(Rung.INFORM, confidence=0.05, cost=1e6), boxes_at_risk=9_999)
    assert decision.required_role is ApprovalRole.BERTH_PLANNER
    assert not decision.blocks
    assert not decision.escalated


def test_rung_four_always_needs_the_customer():
    """A gate PSA cannot escalate its way past, at any level of seniority."""
    decision = evaluate(plan(Rung.OFFER), boxes_at_risk=10)
    assert decision.needs_customer
    assert decision.required_role is ApprovalRole.VESSEL_OPS

    big = evaluate(plan(Rung.OFFER), boxes_at_risk=84)
    assert big.required_role is ApprovalRole.DUTY_MANAGER
    assert big.needs_customer


def test_customer_is_not_on_any_internal_ladder():
    """The line's decision belongs to the line. It cannot be delegated inward."""
    for ladder in LADDERS.values():
        assert ApprovalRole.CUSTOMER not in ladder


@pytest.mark.parametrize("rung", list(Rung))
def test_every_rung_has_a_ladder(rung):
    assert LADDERS[rung]
