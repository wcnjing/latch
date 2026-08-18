"""The Gate Controller: policy decides permissions, never the model.

This module takes no model client and has no way to obtain one. That is the
structural argument, not a stylistic preference: an agent that can talk its
way into a higher approval level has no meaningful approval level, and the
cleanest way to prove it cannot is for the code that decides permissions to
have no channel through which to be persuaded.

Confidence enters as a number computed from provenance elsewhere. Low
confidence tightens the gate automatically — the agent cannot self-authorise
and it cannot self-certify, and neither claim rests on the prompt.

Escalation ladders are per rung, because "which role" and "how senior" are
different questions. A berth planner is not a junior vessel ops manager; they
are the right person for a different rung entirely.
"""

from dataclasses import dataclass

from latch.config import (
    AUTO_APPROVE_MAX_BOXES,
    AUTO_APPROVE_MAX_COST_SGD,
    CONFIDENCE_ESCALATION_THRESHOLD,
)
from latch.models import ApprovalRole, Plan, Rung

# Per-rung escalation path, least to most senior.
#
# Rung 1 has a single entry: it surfaces a number to the planner who was
# already going to decide, and changes nothing on its own. There is nothing
# to escalate, and escalating an advisory would just train people to ignore
# the gate.
#
# Rung 4 starts at vessel ops because releasing ranked options to a customer
# is an outward-facing act. The decision that follows belongs to the line and
# appears in no ladder here — PSA cannot make it, at any level of seniority.
LADDERS: dict[Rung, tuple[ApprovalRole, ...]] = {
    Rung.INFORM: (ApprovalRole.BERTH_PLANNER,),
    Rung.MOVE: (ApprovalRole.AUTO, ApprovalRole.VESSEL_OPS, ApprovalRole.DUTY_MANAGER),
    Rung.OFFER: (ApprovalRole.VESSEL_OPS, ApprovalRole.DUTY_MANAGER),
}


@dataclass(frozen=True, slots=True)
class GateDecision:
    rung: Rung
    required_role: ApprovalRole
    escalated: bool
    escalation_reason: str = ""

    @property
    def auto_approved(self) -> bool:
        return self.required_role is ApprovalRole.AUTO

    @property
    def blocks(self) -> bool:
        """Rung 1 never blocks. It is a notification, not a request."""
        return self.rung is not Rung.INFORM and not self.auto_approved

    @property
    def needs_customer(self) -> bool:
        """The external gate. Not a role we can escalate our way past."""
        return self.rung is Rung.OFFER


def evaluate(plan: Plan, boxes_at_risk: int) -> GateDecision:
    """Map a plan to the approval it requires.

    Inputs are the rung, the volume, the cost and the computed confidence.
    Nothing the model wrote is consulted — the rationale is for humans to
    read, not for the gate to weigh.
    """
    ladder = LADDERS[plan.rung]
    steps = 0
    reasons: list[str] = []

    # An advisory changes nothing on its own, so neither volume nor confidence
    # can make it require a signature.
    if plan.rung is not Rung.INFORM:
        if boxes_at_risk > AUTO_APPROVE_MAX_BOXES:
            steps += 1
            reasons.append(
                f"{boxes_at_risk} boxes over the {AUTO_APPROVE_MAX_BOXES}-box limit"
            )
        if plan.cost_sgd > AUTO_APPROVE_MAX_COST_SGD:
            steps += 1
            reasons.append(
                f"cost SGD {plan.cost_sgd:,.0f} over the "
                f"SGD {AUTO_APPROVE_MAX_COST_SGD:,.0f} limit"
            )
        if plan.confidence < CONFIDENCE_ESCALATION_THRESHOLD:
            steps += 1
            reasons.append(
                f"confidence {plan.confidence:.2f} below "
                f"{CONFIDENCE_ESCALATION_THRESHOLD}"
            )

    index = min(steps, len(ladder) - 1)
    return GateDecision(
        rung=plan.rung,
        required_role=ladder[index],
        escalated=index > 0,
        escalation_reason="; ".join(reasons),
    )
