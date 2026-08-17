"""The risk lifecycle, as a validated transition table.

The v3 design document drew this as an ASCII diagram whose columns implied
`EXECUTING -> ESCALATED` and `SUPERSEDED -> STALE`, neither of which matches
the prose. Escalation comes out of an approval gate, not out of execution;
STALE is an upstream-data condition unrelated to supersession. The table
below is the corrected version and is the single source of truth — the deck
diagram is generated from it by `mermaid()` so the two cannot drift.
"""

from enum import StrEnum


class RiskState(StrEnum):
    DETECTED = "detected"
    TRIAGED = "triaged"
    DELIBERATING = "deliberating"
    AWAITING_APPROVAL = "awaiting_approval"
    ESCALATED = "escalated"
    AWAITING_CUSTOMER = "awaiting_customer"
    EXECUTING = "executing"

    # Off-ramps
    DISMISSED = "dismissed"  # triage killed it
    SUPERSEDED = "superseded"  # ETA improved mid-flight; abandon cleanly
    STALE = "stale"  # upstream data missing; gates tighten
    LOST_LOCK = "lost_lock"  # another risk won the contested resource
    LAPSED = "lapsed"  # internal approval never came

    # Terminal
    RESOLVED = "resolved"
    FAILED = "failed"


TERMINAL_STATES: frozenset[RiskState] = frozenset(
    {
        RiskState.RESOLVED,
        RiskState.FAILED,
        RiskState.DISMISSED,
        RiskState.SUPERSEDED,
    }
)


# Every legal move. Anything absent raises.
TRANSITIONS: dict[RiskState, frozenset[RiskState]] = {
    RiskState.DETECTED: frozenset(
        {RiskState.TRIAGED, RiskState.DISMISSED, RiskState.STALE}
    ),
    RiskState.TRIAGED: frozenset(
        {RiskState.DELIBERATING, RiskState.DISMISSED, RiskState.SUPERSEDED}
    ),
    RiskState.DELIBERATING: frozenset(
        {
            RiskState.AWAITING_APPROVAL,
            RiskState.AWAITING_CUSTOMER,
            RiskState.EXECUTING,  # auto-approved at Rung 1/3 under policy
            RiskState.SUPERSEDED,
            RiskState.LOST_LOCK,
            RiskState.STALE,
        }
    ),
    RiskState.AWAITING_APPROVAL: frozenset(
        {
            RiskState.EXECUTING,  # approved
            RiskState.ESCALATED,  # policy tightened under low confidence
            RiskState.LAPSED,  # nobody signed in time
            RiskState.SUPERSEDED,
        }
    ),
    RiskState.ESCALATED: frozenset(
        {RiskState.EXECUTING, RiskState.LAPSED, RiskState.SUPERSEDED}
    ),
    # All three Rung 4 exits lead here and then onward: the box physically
    # rolls in every case, so the customer gate is never itself terminal.
    # Which of the three occurred is recorded as the Resolution, not the state.
    RiskState.AWAITING_CUSTOMER: frozenset(
        {RiskState.EXECUTING, RiskState.SUPERSEDED}
    ),
    # The loser re-deliberates with the contested option removed. If no
    # alternative exists it falls to Rung 4 rather than dying quietly.
    RiskState.LOST_LOCK: frozenset(
        {RiskState.DELIBERATING, RiskState.AWAITING_CUSTOMER, RiskState.SUPERSEDED}
    ),
    RiskState.STALE: frozenset({RiskState.DELIBERATING, RiskState.DISMISSED}),
    # A lapsed internal approval still fires the default action — doing
    # nothing is also a decision, and it should be traced as one.
    RiskState.LAPSED: frozenset({RiskState.EXECUTING}),
    RiskState.EXECUTING: frozenset({RiskState.RESOLVED, RiskState.FAILED}),
    RiskState.RESOLVED: frozenset(),
    RiskState.FAILED: frozenset(),
    RiskState.DISMISSED: frozenset(),
    RiskState.SUPERSEDED: frozenset(),
}


class IllegalTransition(Exception):
    """Raised when something tries to move a risk somewhere it cannot go."""

    def __init__(self, current: RiskState, target: RiskState) -> None:
        allowed = ", ".join(sorted(s.value for s in TRANSITIONS[current])) or "(none)"
        super().__init__(
            f"cannot move {current.value} -> {target.value}; allowed: {allowed}"
        )
        self.current = current
        self.target = target


def can_transition(current: RiskState, target: RiskState) -> bool:
    return target in TRANSITIONS[current]


def transition(current: RiskState, target: RiskState) -> RiskState:
    """Move a risk, or raise.

    Deliberately strict. A silent illegal transition in an agent that writes
    its own audit trail would make the trail worthless.
    """
    if not can_transition(current, target):
        raise IllegalTransition(current, target)
    return target


def is_terminal(state: RiskState) -> bool:
    return state in TERMINAL_STATES


def mermaid() -> str:
    """Render the transition table as a mermaid state diagram.

    Generated rather than hand-drawn so the diagram on slide 5 is the machine
    that actually ran. If someone edits TRANSITIONS, the slide follows.
    """
    lines = ["stateDiagram-v2", "    [*] --> detected"]
    for source in RiskState:
        for target in sorted(TRANSITIONS[source], key=lambda s: s.value):
            lines.append(f"    {source.value} --> {target.value}")
    for terminal in sorted(TERMINAL_STATES, key=lambda s: s.value):
        lines.append(f"    {terminal.value} --> [*]")
    return "\n".join(lines)
