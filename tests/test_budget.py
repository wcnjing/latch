"""Spend-guard tests. With a small budget these are the ones that matter."""

import pytest

from latch.budget import BudgetExceeded, BudgetGuard, estimate_tokens, worst_case_usd
from latch.llm import FakeModel

SCRIPT = {"triage": {"worth_deliberating": True, "reason": "scripted"}}


def guard(limit: float) -> BudgetGuard:
    return BudgetGuard(FakeModel(SCRIPT), limit_usd=limit)


def call(g: BudgetGuard, max_tokens: int = 512):
    return g.complete_json(
        model="claude-haiku-4-5",
        system="system prompt",
        prompt="user prompt",
        schema={},
        max_tokens=max_tokens,
        purpose="triage",
    )


def test_worst_case_prices_output_at_the_full_ceiling():
    """A short reply is not a guarantee of a small bill — on a thinking model
    the budget covers reasoning too."""
    small = worst_case_usd("claude-opus-5", "x" * 700, 2_000)
    large = worst_case_usd("claude-opus-5", "x" * 700, 16_000)
    assert large > small * 5


def test_guard_refuses_before_spending_not_after():
    g = guard(0.0001)
    with pytest.raises(BudgetExceeded):
        call(g)
    assert g.spent_usd == 0.0
    assert g.calls == []


def test_guard_allows_calls_within_the_ceiling():
    g = guard(1.0)
    call(g)
    assert g.spent_usd > 0
    assert len(g.calls) == 1


def test_guard_stops_once_prior_spend_leaves_no_headroom():
    """The failure mode this exists for: a loop that quietly drains a budget.

    Spend is seeded directly rather than accumulated through FakeModel, whose
    actual cost is far below the worst case the guard projects — the ceiling
    behaviour is what is under test, not the fake's token arithmetic.
    """
    g = guard(1.0)
    call(g)
    assert len(g.calls) == 1

    g.spent_usd = 0.999
    with pytest.raises(BudgetExceeded) as excinfo:
        call(g)
    assert excinfo.value.limit == 1.0
    assert len(g.calls) == 1, "a refused call must not be recorded as spend"


def test_remaining_never_goes_negative():
    g = guard(1.0)
    call(g)
    assert 0.0 <= g.remaining_usd <= 1.0


def test_report_names_the_spend_and_the_ceiling():
    g = guard(3.0)
    call(g)
    assert "of $3.00" in g.report()


def test_token_estimate_errs_high():
    """Over-estimating is the point. An under-estimate defeats the guard."""
    text = "the quick brown fox jumps over the lazy dog " * 10
    assert estimate_tokens(text) > len(text.split())
