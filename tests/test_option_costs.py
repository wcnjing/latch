"""Cost and emissions have to survive into the trace.

They were computed per option, formatted into the model prompt, and then
dropped — so the console detail panel had nothing to bind to and the cost
narrative had nothing to aggregate. The comparison between options *is* the
substance of a Rung 3 decision; recording only the winner throws away the
reasoning that produced it.
"""

import json

import pytest

from latch.console import ladder_view
from latch.events import RiskEvent
from latch.llm import FakeModel
from latch.models import Resolution
from latch.runner import AutoApprove, CustomerSilent, handle
from latch.trace import TraceStore

AT_RISK = {
    "connection_id": "C-1",
    "state": "AT_RISK",
    "current_plan_slack_hours": -0.1,
    "no_itt_slack_hours": 1.4,
    "avoidable_by_terminal_prevention": True,
    "affected_boxes": 34,
    "confidence": "HIGH",
    "reason_codes": ["INTER_TERMINAL_TRANSFER_TIME"],
}


def run(payload: dict | None = None):
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
        RiskEvent.from_dict(payload or AT_RISK),
        client=client,
        store=TraceStore(),
        approvals=AutoApprove(),
        customer=CustomerSilent(),
    )


def options_step(trace):
    return next((s for s in trace.steps if s.type == "options"), None)


def test_every_option_considered_is_serialised_with_its_cost():
    step = options_step(run().trace)
    assert step is not None
    candidates = step.payload["candidates"]
    assert candidates
    for candidate in candidates:
        assert "cost_sgd" in candidate
        assert "emissions_kg_co2e" in candidate
        assert "rung" in candidate


def test_exactly_one_option_is_marked_chosen():
    candidates = options_step(run().trace).payload["candidates"]
    assert sum(1 for c in candidates if c["chosen"]) == 1


def test_the_decision_step_carries_what_the_chosen_option_costs():
    trace = run().trace
    decision = next(
        s for s in trace.steps if s.type == "decision" and s.payload["chosen"]
    )
    assert decision.payload["cost_sgd"] > 0
    assert decision.payload["emissions_kg_co2e"] > 0


def test_moving_cargo_costs_more_than_not_moving_it():
    """A Rung 3 option that costs the same as doing nothing would mean the
    tradeoff the agent claims to weigh does not exist."""
    rows = ladder_view(run().trace)
    moves = [r for r in rows if r.rung == "rung_3_move" and r.status != "ruled_out"]
    advisories = [r for r in rows if r.rung in ("rung_1_inform", "rung_4_offer")]

    assert moves and all(r.has_cost for r in moves)
    assert advisories and not any(r.has_cost for r in advisories)


def test_zero_cost_on_an_advisory_is_real_rather_than_missing():
    """Rung 1 surfaces a number and Rung 4 hands over a decision. Neither moves
    a box, so a zero there is the correct value, not an unpopulated field."""
    rows = ladder_view(run().trace)
    advisory = next(r for r in rows if r.rung == "rung_1_inform")
    assert advisory.cost_sgd == 0.0
    assert not advisory.has_cost


def test_action_cost_is_committed_only_when_the_action_fires():
    """A plan that was chosen but never executed has not spent anything."""
    executed = run()
    assert executed.resolution is Resolution.CONNECTION_HELD
    assert executed.trace.committed_cost_sgd > 0

    nothing_viable = run(
        AT_RISK | {"no_itt_slack_hours": -2.0, "current_plan_slack_hours": -3.5}
    )
    assert nothing_viable.trace.committed_cost_sgd == 0.0


def test_operational_cost_is_never_mixed_with_model_cost():
    """Singapore dollars and inference dollars are different units. Summing
    them on a slide would be a category error, so they stay in separate
    fields with separate names."""
    payload = run().trace.as_dict()
    assert "action_cost_sgd" in payload["outcome"]
    assert "usd" in payload["cost"]
    assert "usd" not in payload["outcome"]
    assert "sgd" not in json.dumps(payload["cost"]).lower()


def test_the_store_aggregates_operational_cost_for_the_cost_narrative():
    store = TraceStore()
    for index in range(3):
        client = FakeModel(
            {
                "triage": {"worth_deliberating": True, "reason": "s"},
                "deliberation": {
                    "chosen_plan_id": "",
                    "ranking": [],
                    "rationale": "s",
                },
            }
        )
        handle(
            RiskEvent.from_dict(AT_RISK | {"connection_id": f"C-{index}"}),
            client=client,
            store=store,
            approvals=AutoApprove(),
            customer=CustomerSilent(),
        )

    metrics = store.metrics()
    assert metrics["action_cost_sgd"] > 0
    assert metrics["action_emissions_kg_co2e"] > 0


def test_ruled_out_options_still_reach_the_panel():
    """The rejection is usually the more interesting half of the comparison."""
    rows = ladder_view(run().trace)
    assert any(r.status == "ruled_out" for r in rows)
