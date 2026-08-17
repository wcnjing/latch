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
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

from latch.config import PRICING
from latch.models import ConnectionRisk, Resolution

TOKENS_PER_MILLION = 1_000_000


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

    def decision(
        self, rung: str, chosen: bool, confidence: float, rationale: str = ""
    ) -> TraceStep:
        return self._append(
            "decision",
            rung=rung,
            chosen=chosen,
            confidence=round(confidence, 4),
            rationale=rationale,
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
    ) -> TraceStep:
        return self._append(
            "gate",
            rung=rung,
            required_role=role,
            escalated=escalated,
            escalation_reason=escalation_reason,
            status=status,
            latency_s=round(latency_s, 1),
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

    def service_rate(self) -> float | None:
        """Share of closed risks where the customer held a live decision.

        The north star. Deliberately not connection success rate: PSA cannot
        control vessel arrival, and claiming credit for it invites a judge who
        knows the domain to reject the causality.
        """
        closed = [t for t in self._traces.values() if t.resolution is not None]
        if not closed:
            return None
        served = sum(1 for t in closed if t.resolution.is_service_success)
        return served / len(closed)

    def cost_per_risk(self) -> float | None:
        traces = self.all()
        if not traces:
            return None
        return sum(t.cost.usd for t in traces) / len(traces)
