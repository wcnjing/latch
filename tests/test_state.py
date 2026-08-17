"""State machine tests, including the transitions the v3 diagram got wrong."""

import pytest

from latch.state import (
    TERMINAL_STATES,
    TRANSITIONS,
    IllegalTransition,
    RiskState,
    can_transition,
    is_terminal,
    mermaid,
    transition,
)


def test_every_state_has_a_transition_entry():
    """A state missing from the table would raise KeyError at runtime."""
    assert set(TRANSITIONS) == set(RiskState)


def test_terminal_states_go_nowhere():
    for state in TERMINAL_STATES:
        assert TRANSITIONS[state] == frozenset()
        assert is_terminal(state)


def test_happy_path_reaches_resolved():
    state = RiskState.DETECTED
    for target in (
        RiskState.TRIAGED,
        RiskState.DELIBERATING,
        RiskState.AWAITING_APPROVAL,
        RiskState.EXECUTING,
        RiskState.RESOLVED,
    ):
        state = transition(state, target)
    assert state is RiskState.RESOLVED


def test_illegal_transition_raises_and_names_the_alternatives():
    with pytest.raises(IllegalTransition) as excinfo:
        transition(RiskState.DETECTED, RiskState.EXECUTING)
    assert "detected -> executing" in str(excinfo.value)
    assert "triaged" in str(excinfo.value)


# --- the corrections ---------------------------------------------------------


def test_escalation_does_not_come_out_of_execution():
    """The v3 diagram's columns implied EXECUTING -> ESCALATED. Escalation is a
    gate decision, and by the time we are executing the gate has been passed."""
    assert not can_transition(RiskState.EXECUTING, RiskState.ESCALATED)
    assert can_transition(RiskState.AWAITING_APPROVAL, RiskState.ESCALATED)


def test_supersession_is_terminal_not_a_route_to_stale():
    """The diagram hung STALE off SUPERSEDED. STALE is an upstream-data
    condition and has nothing to do with an ETA improving."""
    assert not can_transition(RiskState.SUPERSEDED, RiskState.STALE)
    assert is_terminal(RiskState.SUPERSEDED)


def test_customer_gate_is_not_terminal():
    """The box physically rolls in all three Rung 4 exits, so the gate always
    flows onward to an action. Which exit occurred is a Resolution, not a state."""
    assert can_transition(RiskState.AWAITING_CUSTOMER, RiskState.EXECUTING)
    assert not is_terminal(RiskState.AWAITING_CUSTOMER)


def test_lapsed_approval_still_fires_the_default_action():
    """Doing nothing is also a decision and should be traced as one."""
    assert can_transition(RiskState.LAPSED, RiskState.EXECUTING)


def test_lost_lock_re_deliberates_or_falls_to_rung_4():
    """The loser of a contested slot must not die quietly."""
    assert can_transition(RiskState.LOST_LOCK, RiskState.DELIBERATING)
    assert can_transition(RiskState.LOST_LOCK, RiskState.AWAITING_CUSTOMER)


def test_stale_recovers_or_is_dismissed():
    assert can_transition(RiskState.STALE, RiskState.DELIBERATING)
    assert can_transition(RiskState.STALE, RiskState.DISMISSED)


def test_every_non_terminal_state_can_reach_a_terminal_state():
    """No dead ends: a risk that can never close would sit in the console forever."""
    reachable_to_terminal = set(TERMINAL_STATES)
    changed = True
    while changed:
        changed = False
        for source, targets in TRANSITIONS.items():
            if source not in reachable_to_terminal and targets & reachable_to_terminal:
                reachable_to_terminal.add(source)
                changed = True
    assert set(RiskState) == reachable_to_terminal


def test_mermaid_renders_every_edge():
    diagram = mermaid()
    assert diagram.startswith("stateDiagram-v2")
    edges = sum(len(targets) for targets in TRANSITIONS.values())
    # every edge, plus the initial arrow, plus one exit arrow per terminal state
    assert diagram.count("-->") == edges + 1 + len(TERMINAL_STATES)
