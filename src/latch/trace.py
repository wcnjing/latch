"""Append-only execution trace, with cost as a first-class field.

Every decision, tool call, approval, action, result, error and token cost the
agent incurs lands here. Two consumers: workstream C's console renders it
live, and the metrics in the submission are computed from it rather than
asserted.

Putting cost inside the trace rather than in a separate meter makes token
efficiency an auditable property of every individual decision, which is a
much stronger claim than a headline average.
"""

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

from latch.config import PRICING
from latch.models import OUTCOMES, ConnectionRisk, Resolution

TOKENS_PER_MILLION = 1_000_000

# Resolutions excluded from the north-star denominator. Neither represents a
# connection that was ever genuinely at risk of failing, so counting them as
# service failures would punish the system for correctly deciding there was
# nothing to do.
EXCLUDED_FROM_DENOMINATOR: frozenset[Resolution] = frozenset(
    {Resolution.DISMISSED_NO_ACTION, Resolution.SUPERSEDED}
)


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class ModelCall:
    """One request to a model, priced at first-party rates."""

    model: str
    input_tokens: int
    output_tokens: int
    purpose: str = ""

    @property
    def usd(self) -> float:
        try:
            in_rate, out_rate = PRICING[self.model]
        except KeyError:
            raise KeyError(
                f"no pricing for {self.model!r}; add it to config.PRICING "
                "rather than letting a decision carry an unpriced call"
            ) from None
        return (
            self.input_tokens * in_rate + self.output_tokens * out_rate
        ) / TOKENS_PER_MILLION


@dataclass(slots=True)
class CostMeter:
    """Running token and dollar cost for one risk."""

    calls: list[ModelCall] = field(default_factory=list)

    def record(
        self, model: str, input_tokens: int, output_tokens: int, purpose: str = ""
    ) -> ModelCall:
        call = ModelCall(model, input_tokens, output_tokens, purpose)
        self.calls.append(call)
        return call

    @property
    def input_tokens(self) -> int:
        return sum(c.input_tokens for c in self.calls)

    @property
    def output_tokens(self) -> int:
        return sum(c.output_tokens for c in self.calls)

    @property
    def usd(self) -> float:
        return sum(c.usd for c in self.calls)

    def as_dict(self) -> dict[str, Any]:
        return {
            "model_calls": len(self.calls),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "usd": round(self.usd, 6),
            "by_model": {
                model: round(
                    sum(c.usd for c in self.calls if c.model == model), 6
                )
                for model in sorted({c.model for c in self.calls})
            },
        }


@dataclass(frozen=True, slots=True)
class TraceStep:
    seq: int
    type: str
    at: datetime
    payload: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "type": self.type,
            "at": self.at.isoformat(),
            **self.payload,
        }


@dataclass(slots=True)
class Trace:
    """The record of one ConnectionRisk's journey through the ladder."""

    trace_id: str
    risk_id: str
    ucid: str
    trigger: dict[str, Any]
    detected_at: datetime
    steps: list[TraceStep] = field(default_factory=list)
    cost: CostMeter = field(default_factory=CostMeter)
    resolution: Resolution | None = None
    boxes: int = 0
    # Operational cost of the action actually taken. Deliberately separate
    # from `cost`, which is model tokens in USD — adding Singapore dollars to
    # inference dollars would be a category error on a slide.
    committed_cost_sgd: float = 0.0
    committed_emissions_kg: float = 0.0
    options_alive_at_send: int = 0
    offer_sent_at: datetime | None = None

    @classmethod
    def for_risk(cls, risk: ConnectionRisk) -> Self:
        stamp = risk.detected_at.strftime("%Y_%m_%d_%H%M")
        return cls(
            trace_id=f"cr_{stamp}_{risk.risk_id[-4:]}",
            risk_id=risk.risk_id,
            ucid=risk.ucid,
            trigger={
                "source": risk.source,
                "eta_deviation_min": round(risk.eta_deviation_min),
                "slack_consumed_pct": round(risk.slack_consumed_pct, 3),
                "inbound_terminal": risk.inbound.terminal.value,
                "outbound_terminal": risk.outbound.terminal.value,
                "terminal_resolution": risk.inbound.terminal_resolution.value,
            },
            detected_at=risk.detected_at,
            boxes=risk.boxes_at_risk,
        )

    # --- step recorders -----------------------------------------------------
    # One per step type in the schema. Each returns the step so callers can
    # reference its seq without reaching into the list.

    def _append(self, type_: str, **payload: Any) -> TraceStep:
        step = TraceStep(len(self.steps) + 1, type_, _now(), payload)
        self.steps.append(step)
        return step

    def observation(self, summary: str, **extra: Any) -> TraceStep:
        return self._append("observation", summary=summary, **extra)

    def state_change(self, from_state: str, to_state: str, reason: str = "") -> TraceStep:
        return self._append(
            "state_change", from_state=from_state, to_state=to_state, reason=reason
        )

    def options(self, candidates: list[dict[str, Any]]) -> TraceStep:
        """Every option considered, with what each would cost.

        Cost and emissions were computed per option and shown to the model,
        then discarded — so the console had nothing to put in a detail panel
        and the cost narrative had nothing to aggregate. The comparison
        between options is the substance of a Rung 3 decision; recording only
        the winner throws away the reasoning.
        """
        return self._append("options", candidates=candidates)

    def decision(
        self,
        rung: str,
        chosen: bool,
        confidence: float,
        rationale: str = "",
        cost_sgd: float = 0.0,
        emissions_kg_co2e: float = 0.0,
    ) -> TraceStep:
        return self._append(
            "decision",
            rung=rung,
            chosen=chosen,
            confidence=round(confidence, 4),
            rationale=rationale,
            cost_sgd=round(cost_sgd, 2),
            emissions_kg_co2e=round(emissions_kg_co2e, 2),
        )

    def tool_call(
        self, tool: str, status: str, latency_ms: int, **extra: Any
    ) -> TraceStep:
        return self._append(
            "tool_call", tool=tool, status=status, latency_ms=latency_ms, **extra
        )

    def lock(
        self,
        resource: str,
        status: str,
        our_priority: float,
        winner_priority: float | None = None,
        action: str = "",
    ) -> TraceStep:
        return self._append(
            "lock",
            resource=resource,
            status=status,
            our_priority=round(our_priority, 2),
            winner_priority=(
                round(winner_priority, 2) if winner_priority is not None else None
            ),
            action=action,
        )

    def error(
        self, tool: str, error_class: str, retries: int, recovery: str
    ) -> TraceStep:
        return self._append(
            "error",
            tool=tool,
            error_class=error_class,
            retries=retries,
            recovery=recovery,
        )

    def confidence(self, breakdown_dict: dict[str, Any]) -> TraceStep:
        return self._append("confidence", **breakdown_dict)

    def gate(
        self,
        rung: str,
        role: str,
        escalated: bool,
        status: str,
        latency_s: float = 0.0,
        escalation_reason: str = "",
        window_min: int | None = None,
        expires_at: datetime | None = None,
    ) -> TraceStep:
        """One gate evaluation.

        `latency_s` is elapsed time after the fact. `window_min` and
        `expires_at` are the deadline the approver is working against, and are
        only meaningful while one still is — a resolved gate reports how long
        it took, not when it would have expired.
        """
        extra: dict[str, Any] = {}
        if window_min is not None:
            extra["window_min"] = window_min
        if expires_at is not None:
            extra["expires_at"] = expires_at.isoformat()
        return self._append(
            "gate",
            rung=rung,
            required_role=role,
            escalated=escalated,
            escalation_reason=escalation_reason,
            status=status,
            latency_s=round(latency_s, 1),
            **extra,
        )

    def external_gate(
        self, party: str, options_sent: int, window_min: int, outcome: str
    ) -> TraceStep:
        return self._append(
            "external_gate",
            party=party,
            options_sent=options_sent,
            window_min=window_min,
            outcome=outcome,
        )

    def model_call(
        self, model: str, input_tokens: int, output_tokens: int, purpose: str
    ) -> TraceStep:
        call = self.cost.record(model, input_tokens, output_tokens, purpose)
        return self._append(
            "model_call",
            model=model,
            purpose=purpose,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            usd=round(call.usd, 6),
        )

    # --- outcome ------------------------------------------------------------

    def commit_action_cost(self, cost_sgd: float, emissions_kg_co2e: float) -> None:
        """Record what the executed action actually costs, once it fires."""
        self.committed_cost_sgd = round(cost_sgd, 2)
        self.committed_emissions_kg = round(emissions_kg_co2e, 2)

    def close(
        self,
        resolution: Resolution,
        offer_sent_at: datetime | None = None,
        options_alive: int = 0,
    ) -> None:
        self.resolution = resolution
        self.offer_sent_at = offer_sent_at
        self.options_alive_at_send = options_alive

    @property
    def decision_lead_time_h(self) -> float | None:
        """Hours between the risk becoming knowable and options reaching the line.

        The supporting metric where the agent obviously beats a phone call.
        None when no offer was ever sent, which is itself worth knowing.
        """
        if self.offer_sent_at is None:
            return None
        return (self.offer_sent_at - self.detected_at).total_seconds() / 3600.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "risk_id": self.risk_id,
            "ucid": self.ucid,
            "trigger": self.trigger,
            "steps": [s.as_dict() for s in self.steps],
            "outcome": {
                "resolution": self.resolution.value if self.resolution else None,
                "service_success": (
                    self.resolution.is_service_success if self.resolution else None
                ),
                "boxes": self.boxes,
                "decision_lead_time_h": (
                    round(self.decision_lead_time_h, 2)
                    if self.decision_lead_time_h is not None
                    else None
                ),
                "options_alive_at_send": self.options_alive_at_send,
                "action_cost_sgd": self.committed_cost_sgd,
                "action_emissions_kg_co2e": self.committed_emissions_kg,
            },
            "cost": self.cost.as_dict(),
        }


class TraceStore:
    """Append-only store. In memory, with an optional JSONL sink.

    Append-only is not decoration: a trace that can be edited after the fact
    is not an audit trail, and the calibration loop in the roadmap depends on
    these records being trustworthy.
    """

    def __init__(self, sink: Path | None = None) -> None:
        self._traces: dict[str, Trace] = {}
        self._sink = sink
        if sink is not None:
            sink.parent.mkdir(parents=True, exist_ok=True)

    def open(self, risk: ConnectionRisk) -> Trace:
        trace = Trace.for_risk(risk)
        if trace.trace_id in self._traces:
            raise ValueError(f"trace {trace.trace_id} already open")
        self._traces[trace.trace_id] = trace
        return trace

    def adopt(self, trace: Trace) -> Trace:
        """Take ownership of a trace built elsewhere.

        For replaying a captured fixture, and for the backup path if the live
        feed dies during recording.
        """
        if trace.trace_id in self._traces:
            raise ValueError(f"trace {trace.trace_id} already present")
        self._traces[trace.trace_id] = trace
        return trace

    def get(self, trace_id: str) -> Trace:
        return self._traces[trace_id]

    def all(self) -> list[Trace]:
        return list(self._traces.values())

    def flush(self, trace: Trace) -> None:
        """Write a completed trace to the sink. Never rewrites an earlier line."""
        if self._sink is None:
            return
        with self._sink.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(trace.as_dict(), separators=(",", ":")) + "\n")

    # --- metrics ------------------------------------------------------------

    def metrics(self) -> dict[str, Any]:
        """North-star metric with its denominator shown.

        The metric is the share of *at-risk* connections where the customer
        held a live decision before the window closed. Two resolutions are
        excluded from the denominator rather than counted as failures:

          DISMISSED_NO_ACTION  triage determined the connection was never
                               actually at risk, which is triage working
          SUPERSEDED           the ETA improved and the risk evaporated

        Counting either as a service failure would punish the system for
        correctly deciding there was nothing to do. Excluding them also moves
        the number up, so the count of exclusions is reported alongside it —
        a rate quoted without its denominator is not a measurement.
        """
        closed = [t for t in self._traces.values() if t.resolution is not None]

        # One pass. Five separate generator expressions over the same list read
        # as five independent facts when they are really one classification.
        tally = Counter(t.resolution for t in closed)
        excluded = sum(tally[r] for r in EXCLUDED_FROM_DENOMINATOR)
        at_risk = len(closed) - excluded

        served = failed_internally = failed_at_the_line = 0
        reached = agent_faults = 0
        for resolution, count in tally.items():
            if resolution in EXCLUDED_FROM_DENOMINATOR:
                continue
            facts = OUTCOMES[resolution]
            if facts.reached_line:
                reached += count
            if facts.served:
                served += count
            elif facts.agent_fault:
                # A crash is not a decision. Counting it as an internal failure
                # reports an infrastructure fault as a business one, and hides
                # the only number here that means "go and fix the code".
                agent_faults += count
            elif facts.reached_line:
                failed_at_the_line += count
            else:
                failed_internally += count

        return {
            "closed": len(closed),
            "at_risk": at_risk,
            "action_cost_sgd": round(
                sum(t.committed_cost_sgd for t in closed), 2
            ),
            "action_emissions_kg_co2e": round(
                sum(t.committed_emissions_kg for t in closed), 2
            ),
            "served": served,
            "service_rate": (served / at_risk) if at_risk else None,
            # Split the failures by who they belong to. A run failing because
            # nobody internally signed is a different problem from one failing
            # because the line never replied, and one number hides which.
            "failed_internally": failed_internally,
            "failed_at_the_line": failed_at_the_line,
            "agent_faults": agent_faults,
            "reached_the_line": reached,
            "excluded_dismissed": tally[Resolution.DISMISSED_NO_ACTION],
            "excluded_superseded": tally[Resolution.SUPERSEDED],
        }

    def service_rate(self) -> float | None:
        """Share of at-risk connections where the customer held a live decision.

        The north star. Deliberately not connection success rate: PSA cannot
        control vessel arrival, and claiming credit for it invites a judge who
        knows the domain to reject the causality. See `metrics()` for the
        denominator.
        """
        return self.metrics()["service_rate"]

    def cost_per_risk(self) -> float | None:
        traces = self.all()
        if not traces:
            return None
        return sum(t.cost.usd for t in traces) / len(traces)
