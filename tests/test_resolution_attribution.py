"""Who actually made the decision, and did the line ever get asked.

Two mirrored defects: an internal decline closed as `customer_declined_all`
and counted as the customer being served, and an unsigned internal approval
closed as `window_lapsed_no_response` and blamed the line. In both cases the
shipping line was never contacted.
"""

import pytest

from latch.events import RiskEvent
from latch.llm import FakeModel
from latch.models import Resolution
from latch.runner import (
    AutoApprove,
    CustomerAccepts,
    CustomerDeclinesAll,
    CustomerSilent,
    NeverApproves,
    handle,
)
from latch.trace import TraceStore

NEEDS_APPROVAL = {
    "connection_id": "R-1",
    "state": "AT_RISK",
    "current_plan_slack_hours": -0.1,
    "no_itt_slack_hours": 1.4,
    "avoidable_by_terminal_prevention": True,
    "affected_boxes": 84,  # over the auto-approve limit, so a human is required
    "confidence": "HIGH",
    "reason_codes": [],
}
NOTHING_VIABLE = NEEDS_APPROVAL | {
    "connection_id": "R-2",
    "current_plan_slack_hours": -3.5,
    "no_itt_slack_hours": -2.0,
    "avoidable_by_terminal_prevention": False,
}


class RejectsEverything:
    def decide(self, role, plan):
        return False


def run(payload, **kwargs):
    kwargs.setdefault("approvals", AutoApprove())
    kwargs.setdefault("customer", CustomerSilent())
    return handle(
        RiskEvent.from_dict(payload),
        client=FakeModel(
            {
                "triage": {"worth_deliberating": True, "reason": "s"},
                "deliberation": {"chosen_plan_id": "", "ranking": [], "rationale": "s"},
            }
        ),
        store=kwargs.pop("store", TraceStore()),
        **kwargs,
    )


def test_an_internal_decline_is_not_a_customer_decline():
    """Vessel ops saying no is not the line saying no, and counting it as the
    customer being served inflates the north-star metric with our own choice."""
    outcome = run(NEEDS_APPROVAL, approvals=RejectsEverything())

    assert outcome.resolution is Resolution.INTERNALLY_DECLINED
    assert not outcome.resolution.is_service_success
    assert not outcome.resolution.reached_the_line


def test_an_unsigned_approval_does_not_blame_the_line():
    """Nobody internally signed. Recording that as the line failing to answer
    blames them for a question they were never asked."""
    outcome = run(NEEDS_APPROVAL, approvals=NeverApproves())

    assert outcome.resolution is Resolution.APPROVAL_LAPSED
    assert not outcome.resolution.reached_the_line


def test_neither_internal_outcome_emits_an_external_gate():
    """The strongest check: if the line was never contacted, no external gate
    step should exist in the trace at all."""
    for approvals in (RejectsEverything(), NeverApproves()):
        outcome = run(NEEDS_APPROVAL, approvals=approvals)
        assert not any(s.type == "external_gate" for s in outcome.trace.steps)


@pytest.mark.parametrize(
    "customer,expected",
    [
        (CustomerAccepts(), Resolution.CUSTOMER_DECIDED),
        (CustomerDeclinesAll(), Resolution.CUSTOMER_DECLINED_ALL),
        (CustomerSilent(), Resolution.WINDOW_LAPSED_NO_RESPONSE),
    ],
)
def test_the_three_real_customer_exits_all_reached_the_line(customer, expected):
    outcome = run(NOTHING_VIABLE, customer=customer)
    assert outcome.resolution is expected
    assert outcome.resolution.reached_the_line
    assert any(s.type == "external_gate" for s in outcome.trace.steps)


def test_a_line_that_declines_everything_is_still_served():
    """Unchanged, and the distinction the whole product rests on: the box rolls
    either way, but one of them had a choice."""
    assert Resolution.CUSTOMER_DECLINED_ALL.is_service_success
    assert not Resolution.WINDOW_LAPSED_NO_RESPONSE.is_service_success


def test_metrics_separate_our_failures_from_the_lines():
    store = TraceStore()
    run(NEEDS_APPROVAL | {"connection_id": "A"}, approvals=NeverApproves(), store=store)
    run(NEEDS_APPROVAL | {"connection_id": "B"}, approvals=RejectsEverything(), store=store)
    run(NOTHING_VIABLE | {"connection_id": "C"}, customer=CustomerSilent(), store=store)
    run(NOTHING_VIABLE | {"connection_id": "D"}, customer=CustomerAccepts(), store=store)

    metrics = store.metrics()
    assert metrics["failed_internally"] == 2
    assert metrics["failed_at_the_line"] == 1
    assert metrics["reached_the_line"] == 2
    assert metrics["served"] == 1
