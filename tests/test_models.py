"""Contract tests. These pin the shape A and C build against."""

import pytest

from latch.models import Resolution, Terminal, TerminalResolution
from tests.conftest import make_risk


def test_slack_consumed_not_delay_magnitude():
    """A six-hour slip against thirty hours of slack is nothing; a ninety-minute
    slip against two hours is critical. The Watcher triggers on the ratio."""
    roomy = make_risk(slack_total_min=1800, slack_remaining_min=1440, eta_slip_min=360)
    tight = make_risk(slack_total_min=120, slack_remaining_min=30, eta_slip_min=90)

    assert roomy.eta_deviation_min > tight.eta_deviation_min
    assert roomy.slack_consumed_pct < tight.slack_consumed_pct
    assert tight.slack_consumed_pct == pytest.approx(0.75)


def test_slack_consumed_is_clamped():
    blown = make_risk(slack_total_min=120, slack_remaining_min=-60)
    assert blown.slack_consumed_pct == 1.0

    no_window = make_risk(slack_total_min=0, slack_remaining_min=0)
    assert no_window.slack_consumed_pct == 1.0


def test_priority_rewards_volume_and_punishes_slack():
    urgent = make_risk(boxes=60, slack_remaining_min=60)
    relaxed = make_risk(boxes=60, slack_remaining_min=600)
    small = make_risk(boxes=6, slack_remaining_min=60)

    assert urgent.priority > relaxed.priority
    assert urgent.priority > small.priority
    assert urgent.priority == pytest.approx(60.0)


def test_priority_is_bounded_when_slack_is_gone():
    """Without a floor, an already-blown connection outranks everything forever."""
    blown = make_risk(boxes=10, slack_remaining_min=0)
    assert blown.priority == pytest.approx(40.0)  # 10 / 0.25h


def test_crosses_terminals_detects_the_inter_terminal_case():
    across = make_risk(
        inbound_terminal=Terminal.TUAS, outbound_terminal=Terminal.PASIR_PANJANG
    )
    within = make_risk(
        inbound_terminal=Terminal.TUAS, outbound_terminal=Terminal.TUAS
    )
    assert across.crosses_terminals
    assert not within.crosses_terminals


def test_terminal_resolution_travels_with_the_call():
    """If the day-1 gate lands on port-level-only data, this is the field that
    keeps the claim honest instead of implied."""
    simulated = make_risk(resolution=TerminalResolution.SIMULATED)
    assert simulated.inbound.terminal_resolution is TerminalResolution.SIMULATED


def test_declining_every_option_is_still_service():
    """The distinction that is the entire product: the box rolls in all three
    Rung 4 exits, but only one of them is a failure."""
    assert Resolution.CUSTOMER_DECIDED.is_service_success
    assert Resolution.CUSTOMER_DECLINED_ALL.is_service_success
    assert not Resolution.WINDOW_LAPSED_NO_RESPONSE.is_service_success


def test_vessel_call_deviation():
    risk = make_risk(eta_slip_min=361)
    assert risk.inbound.deviation_min == pytest.approx(361.0)
    assert risk.outbound.deviation_min == pytest.approx(0.0)
