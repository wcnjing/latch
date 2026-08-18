"""Triage: decide what deserves the expensive model.

A already classifies severity, so re-deriving it here would be redundant and
a judge would say so. Triage answers a different question: *is this worth
spending Deliberation on?* Severity is an input to that, not the answer.

The funnel is free at both ends. A SAFE event never reaches a model, and an
already-blown connection carrying eighty boxes does not need a small model's
opinion on whether it is serious. The small model is spent only on the
ambiguous middle — which is the only place a judgement is being made.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from latch.config import (
    TRIAGE_FAST_TRACK_BOXES,
    TRIAGE_MIN_BOXES,
    TRIAGE_MAX_TOKENS,
    TRIAGE_MODEL,
)
from latch.events import RiskEvent, RiskSeverity
from latch.llm import ModelClient

TRIAGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "worth_deliberating": {
            "type": "boolean",
            "description": "True if this connection warrants full deliberation.",
        },
        "reason": {
            "type": "string",
            "description": "One sentence. What decided it.",
        },
    },
    "required": ["worth_deliberating", "reason"],
    "additionalProperties": False,
}

TRIAGE_SYSTEM = """You triage container connection risks at the Port of Singapore.

You are deciding one thing only: whether this connection warrants full \
deliberation by a more capable model. You are not deciding what to do about it, \
and you are not re-assessing how severe it is — the Watcher has already done that.

Deliberation is worth spending when there is a real decision to make: options \
exist, they differ, and choosing between them affects whether cargo connects. \
It is wasted when the connection comfortably fits its window, when the volume is \
too small for any action to be worth its own cost, or when nothing about the \
situation is actually in question.

Answer with the schema. Keep the reason to one sentence."""


class TriageRoute(StrEnum):
    """How a verdict was reached. Recorded so the funnel is auditable."""

    DISMISSED_SAFE = "dismissed_safe"
    DISMISSED_TOO_SMALL = "dismissed_too_small"
    FAST_TRACKED = "fast_tracked"
    MODEL_KEPT = "model_kept"
    MODEL_DISMISSED = "model_dismissed"


@dataclass(frozen=True, slots=True)
class TriageVerdict:
    keep: bool
    route: TriageRoute
    reason: str
    model_used: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""

    @property
    def was_free(self) -> bool:
        return not self.model_used


def prefilter(event: RiskEvent) -> TriageVerdict | None:
    """Deterministic decisions. Returns None when a judgement is genuinely needed."""
    if event.state is RiskSeverity.SAFE:
        return TriageVerdict(
            keep=False,
            route=TriageRoute.DISMISSED_SAFE,
            reason=(
                f"Watcher reports SAFE with {event.current_plan_slack_hours:.1f}h "
                "of slack; nothing to decide."
            ),
        )

    if event.affected_boxes < TRIAGE_MIN_BOXES:
        return TriageVerdict(
            keep=False,
            route=TriageRoute.DISMISSED_TOO_SMALL,
            reason=(
                f"{event.affected_boxes} boxes is below the {TRIAGE_MIN_BOXES}-box "
                "floor; any move would cost more than the miss."
            ),
        )

    if (
        event.state is RiskSeverity.AT_RISK
        and event.affected_boxes >= TRIAGE_FAST_TRACK_BOXES
        and event.current_plan_slack_hours <= 0
    ):
        return TriageVerdict(
            keep=True,
            route=TriageRoute.FAST_TRACKED,
            reason=(
                f"{event.affected_boxes} boxes already past the window by "
                f"{event.slack_deficit_hours:.1f}h; deliberating without asking."
            ),
        )

    return None


def _prompt(event: RiskEvent) -> str:
    codes = ", ".join(c.value for c in event.reason_codes) or "none given"
    return (
        f"Connection {event.connection_id}\n"
        f"Watcher severity: {event.state.value} "
        f"(watcher confidence {event.watcher_confidence.value})\n"
        f"Boxes affected: {event.affected_boxes}\n"
        f"Slack under the current plan: {event.current_plan_slack_hours:.1f}h\n"
        f"Slack if the inter-terminal transfer were removed: "
        f"{event.no_itt_slack_hours:.1f}h\n"
        f"Removing the transfer would save the connection: "
        f"{event.itt_is_the_problem}\n"
        f"Reason codes: {codes}"
    )


def triage(event: RiskEvent, client: ModelClient) -> TriageVerdict:
    """Route an event. Spends a model call only when the answer is not obvious."""
    decided = prefilter(event)
    if decided is not None:
        return decided

    response = client.complete_json(
        model=TRIAGE_MODEL,
        system=TRIAGE_SYSTEM,
        prompt=_prompt(event),
        schema=TRIAGE_SCHEMA,
        max_tokens=TRIAGE_MAX_TOKENS,
        purpose="triage",
    )
    keep = bool(response.data["worth_deliberating"])
    return TriageVerdict(
        keep=keep,
        route=TriageRoute.MODEL_KEPT if keep else TriageRoute.MODEL_DISMISSED,
        reason=str(response.data["reason"]),
        model_used=True,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        model=response.model,
    )
