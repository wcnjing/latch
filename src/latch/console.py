"""View models for the operations console (workstream C).

The console renders a `Trace`. It could parse the raw steps itself, but then
two workstreams would each own half the meaning of a step type and they would
drift. This module is the seam: B decides what a step means, C decides how it
looks.

The confidence panel is the piece worth care. A bare number invites exactly
the question the design exists to answer — *why should I trust that?* — so the
panel emits the whole derivation as a waterfall: what each factor was, what it
multiplied by, and how much it cost. Rendered as steps down from 1.0, the
screen shows a judge the reasoning rather than asserting it.
"""

from dataclasses import asdict, dataclass
from typing import Any

from latch.config import CONFIDENCE_ESCALATION_THRESHOLD
from latch.trace import Trace


@dataclass(frozen=True, slots=True)
class WaterfallStep:
    """One factor's contribution, as a step down from 1.0."""

    label: str
    detail: str
    kind: str  # "multiply" | "subtract"
    factor: float
    running: float

    @property
    def cost(self) -> float:
        """How much confidence this factor removed. Positive means it hurt."""
        return round(self.running / self.factor - self.running, 4) if (
            self.kind == "multiply" and self.factor
        ) else round(self.factor, 4)


@dataclass(frozen=True, slots=True)
class ConfidencePanel:
    value: float
    band: str  # "auto" | "escalate"
    threshold: float
    derivation: str
    waterfall: tuple[WaterfallStep, ...]

    @property
    def crosses_threshold(self) -> bool:
        return self.value < self.threshold

    @property
    def headline(self) -> str:
        """One line, for when there is no room for the waterfall."""
        if not self.crosses_threshold:
            return f"{self.value:.2f} — within policy, no signature required"
        return (
            f"{self.value:.2f} — below {self.threshold:.2f}, "
            "approval escalated one level"
        )


def confidence_panel(trace: Trace) -> ConfidencePanel | None:
    """Build the panel from the last confidence step in a trace."""
    steps = [s for s in trace.steps if s.type == "confidence"]
    if not steps:
        return None

    payload = steps[-1].payload
    factors = payload.get("factors", {})
    value = float(payload.get("computed", 0.0))

    running = 1.0
    waterfall: list[WaterfallStep] = []

    for label, detail, key in (
        ("Source", str(factors.get("source", "?")), "source_factor"),
        (
            "Data age",
            f"{factors.get('data_age_min', 0):.0f} min old",
            "age_factor",
        ),
        ("Tool outcome", str(factors.get("tool_outcome", "?")), "tool_factor"),
    ):
        factor = float(factors.get(key, 1.0))
        running *= factor
        waterfall.append(
            WaterfallStep(label, detail, "multiply", factor, round(running, 4))
        )

    penalty = float(factors.get("unverified_penalty", 0.0))
    if penalty:
        running -= penalty
        waterfall.append(
            WaterfallStep(
                "Unverified inputs",
                f"{factors.get('unverified_inputs', 0)} of them",
                "subtract",
                penalty,
                round(running, 4),
            )
        )

    return ConfidencePanel(
        value=round(value, 4),
        band="escalate" if value < CONFIDENCE_ESCALATION_THRESHOLD else "auto",
        threshold=CONFIDENCE_ESCALATION_THRESHOLD,
        derivation=str(payload.get("derivation", "")),
        waterfall=tuple(waterfall),
    )


@dataclass(frozen=True, slots=True)
class OptionRow:
    option_id: str
    rung: str
    detail: str
    status: str  # "chosen" | "considered" | "ruled_out" | "advisory"
    cost_sgd: float = 0.0
    emissions_kg_co2e: float = 0.0

    @property
    def has_cost(self) -> bool:
        """Rung 1 and Rung 4 move no cargo, so a zero here is real, not missing."""
        return self.cost_sgd > 0 or self.emissions_kg_co2e > 0


def ladder_view(trace: Trace) -> tuple[OptionRow, ...]:
    """What the agent considered, chose, and ruled out.

    Ruled-out options are included deliberately. A ladder showing only what
    survived reads as an agent that never considered the alternatives, rather
    than one that considered and rejected them — and the rejection is usually
    the more interesting half.
    """
    rows: list[OptionRow] = []

    for step in trace.steps:
        if step.type == "options":
            # The comparison the agent actually made. This is what a detail
            # panel renders — road against barge on time, cost and emissions —
            # and it is the substance of a Rung 3 decision rather than its
            # summary.
            for candidate in step.payload.get("candidates", []):
                rows.append(
                    OptionRow(
                        option_id=str(candidate.get("option_id", "")),
                        rung=str(candidate.get("rung", "")),
                        detail=str(candidate.get("detail", "")),
                        status="chosen" if candidate.get("chosen") else "considered",
                        cost_sgd=float(candidate.get("cost_sgd", 0.0)),
                        emissions_kg_co2e=float(
                            candidate.get("emissions_kg_co2e", 0.0)
                        ),
                    )
                )
        elif step.type == "decision" and not step.payload.get("chosen"):
            rows.append(
                OptionRow(
                    option_id=str(step.payload.get("rung", "")),
                    rung=str(step.payload.get("rung", "")),
                    detail=str(step.payload.get("rationale", "")),
                    status="advisory",
                    cost_sgd=float(step.payload.get("cost_sgd", 0.0)),
                    emissions_kg_co2e=float(
                        step.payload.get("emissions_kg_co2e", 0.0)
                    ),
                )
            )
        elif step.type == "observation" and step.payload.get("considered"):
            summary = str(step.payload.get("summary", ""))
            option_id, _, reason = summary.partition(": ")
            rows.append(
                OptionRow(
                    option_id=option_id.replace("ruled out ", ""),
                    rung=str(step.payload.get("rung", "")),
                    detail=reason,
                    status="ruled_out",
                )
            )
    return tuple(rows)


@dataclass(frozen=True, slots=True)
class PendingApproval:
    rung: str
    role: str
    escalated: bool
    reason: str
    status: str


def approvals_view(trace: Trace) -> tuple[PendingApproval, ...]:
    """Gates as things a person acts on, not log lines."""
    return tuple(
        PendingApproval(
            rung=str(s.payload.get("rung", "")),
            role=str(s.payload.get("required_role", "")),
            escalated=bool(s.payload.get("escalated")),
            reason=str(s.payload.get("escalation_reason", "")),
            status=str(s.payload.get("status", "")),
        )
        for s in trace.steps
        if s.type == "gate"
    )


def case_view(trace: Trace) -> dict[str, Any]:
    """Everything the console needs for one connection, in one payload."""
    panel = confidence_panel(trace)
    external = [s for s in trace.steps if s.type == "external_gate"]

    return {
        "trace_id": trace.trace_id,
        "risk_id": trace.risk_id,
        "ucid": trace.ucid,
        "trigger": trace.trigger,
        "resolution": trace.resolution.value if trace.resolution else None,
        # The distinction the whole product turns on. A rolled box is not the
        # same as an unserved customer, and the screen has to say which.
        "service_success": (
            trace.resolution.is_service_success if trace.resolution else None
        ),
        "boxes": trace.boxes,
        "decision_lead_time_h": trace.decision_lead_time_h,
        "options_alive_at_send": trace.options_alive_at_send,
        "confidence": asdict(panel) if panel else None,
        "confidence_headline": panel.headline if panel else None,
        "ladder": [asdict(r) for r in ladder_view(trace)],
        "approvals": [asdict(a) for a in approvals_view(trace)],
        "customer_gate": (
            {
                "options_sent": external[-1].payload.get("options_sent"),
                "window_min": external[-1].payload.get("window_min"),
                "outcome": external[-1].payload.get("outcome"),
            }
            if external
            else None
        ),
        "cost": trace.cost.as_dict(),
        "step_count": len(trace.steps),
    }
