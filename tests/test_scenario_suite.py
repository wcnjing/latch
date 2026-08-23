"""The rails suite, as a test.

The suite existed as a script only, so a regression in it broke nothing that
anyone would notice. That is exactly what happened: splitting APPROVAL_LAPSED
out of WINDOW_LAPSED_NO_RESPONSE left G-03 asserting the old value, the suite
quietly dropped to 29/30, and a full green pytest run reported no problem at
all. The number is a headline claim on the deck; it needs a build that fails.

Only the PolicyModel run belongs here. It is deterministic, instant and costs
nothing, and a failure in it is a rails bug. The model-backed runs take ~13
minutes and bill real money, so they stay in `scripts/run_scenarios.py` — and
a failure there is a prompt problem, which is not the same claim.
"""

import pytest

from latch.scenarios import PolicyModel, run_suite
from latch.scenario_suite import SUITE


@pytest.fixture(scope="module")
def report():
    return run_suite(PolicyModel(), "PolicyModel (rails only, no judgement)")


def test_rails_suite_passes_completely(report):
    """30/30 on the rails, or the build goes red.

    Asserted as a whole rather than per-scenario so the failure message names
    every miss at once — debugging one scenario at a time through a test
    runner is slower than reading the report.
    """
    assert not report.misses(), "\n" + report.render()


def test_suite_covers_every_family(report):
    """A family silently emptied by a refactor still reports 100%."""
    families = {s.family for s in SUITE}
    assert families == {
        "customer_gate",
        "degradation",
        "gate_policy",
        "internal_fix",
        "no_internal_option",
        "prevention",
        "triage",
    }


def test_suite_size_is_the_number_on_the_deck():
    """The deck says thirty. If that changes, change the deck deliberately."""
    assert len(SUITE) == 30
    assert len({s.scenario_id for s in SUITE}) == 30, "duplicate scenario id"
