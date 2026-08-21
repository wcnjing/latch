"""The A to B contract: structured risk events from the Watcher.

This is the shape A and B agreed on. B's agent logic never touches it
directly — `RiskEvent.to_connection_risk()` adapts it into the internal
domain model, so when A swaps mock output for live Watcher output, and later
enriches it with vessel and terminal detail, only the adapter changes.

    A ──RiskEvent──▶ adapter ──ConnectionRisk──▶ agent core

One naming hazard, called out because getting it wrong would be a real bug:
this event carries a `confidence` field and so does a Plan, and they mean
different things.

    RiskEvent.watcher_confidence   how sure A is that this is a risk at all
    Plan.confidence                how much to trust this specific plan

A's confidence is an *input* to B's. It never overwrites it, and a HIGH from
the Watcher cannot make a plan built on stale cache data trustworthy.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from latch.models import (
    MIN_SLACK_HOURS,
    ConnectionRisk,
    Provenance,
    SourceKind,
    Terminal,
    TerminalResolution,
    VesselCall,
)

WIRE_VERSION = 1


class RiskSeverity(StrEnum):
    """A's own classification of the connection."""

    SAFE = "SAFE"
    WATCH = "WATCH"
    AT_RISK = "AT_RISK"


class WatcherConfidence(StrEnum):
    """How sure A is about the assessment. Not the same as plan confidence."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ConnectionType(StrEnum):
    """Whether the cargo has to cross terminals. The one structural fact the
    agent reasons about, and it is assumed rather than observed."""

    SAME_TERMINAL = "SAME_TERMINAL"
    INTER_TERMINAL = "INTER_TERMINAL"


@dataclass(frozen=True, slots=True)
class Assumptions:
    """The narrow slice of provenance that changes how the agent reasons.

    Deliberately not the full assumption register — B does not need to carry
    A's methodology. It needs exactly the facts that determine whether a
    statement in a trace is an observation or a scenario output, because an
    agent that writes "PSA confirmed this container needs 5.2 hours to
    transfer" has fabricated a claim about the real world.

    Everything here defaults to synthetic. An event that arrives without
    provenance is treated as invented, because assuming the safer thing about
    unlabelled data is the only default that cannot mislead.
    """

    connection_type: ConnectionType = ConnectionType.SAME_TERMINAL
    ucid_synthetic: bool = True
    pairing_synthetic: bool = True
    terminals_synthetic: bool = True
    boxes_synthetic: bool = True
    transfer_scenario: str = "configured reference transfer scenario"

    @property
    def any_synthetic(self) -> bool:
        return (
            self.ucid_synthetic
            or self.pairing_synthetic
            or self.terminals_synthetic
            or self.boxes_synthetic
        )

    @property
    def qualifier(self) -> str:
        """The phrase every derived figure is stated under.

        Used verbatim so the hedge is consistent, and so a reader who sees it
        once learns what it covers rather than parsing a new caveat each time.
        """
        return f"Under the {self.transfer_scenario}"

    def as_dict(self) -> dict[str, object]:
        return {
            "connection_type": self.connection_type.value,
            "ucid_synthetic": self.ucid_synthetic,
            "pairing_synthetic": self.pairing_synthetic,
            "terminals_synthetic": self.terminals_synthetic,
            "boxes_synthetic": self.boxes_synthetic,
            "transfer_scenario": self.transfer_scenario,
            "slack_is_scenario_output": True,
            "no_itt_slack_means": "margin if the transfer requirement were removed",
        }


class ReasonCode(StrEnum):
    """Why the connection is at risk. Drives which rungs are even relevant."""

    INBOUND_ETA_SLIP = "INBOUND_ETA_SLIP"
    OUTBOUND_CUTOFF_ADVANCED = "OUTBOUND_CUTOFF_ADVANCED"
    INTER_TERMINAL_TRANSFER_TIME = "INTER_TERMINAL_TRANSFER_TIME"
    BERTH_CONGESTION = "BERTH_CONGESTION"
    YARD_CONGESTION = "YARD_CONGESTION"
    DISCHARGE_SEQUENCE = "DISCHARGE_SEQUENCE"


# How much A's own confidence discounts a plan built on its numbers. A LOW
# from the Watcher should not produce a plan we auto-approve.
WATCHER_CONFIDENCE_FACTOR: dict[WatcherConfidence, float] = {
    WatcherConfidence.HIGH: 1.00,
    WatcherConfidence.MEDIUM: 0.90,
    WatcherConfidence.LOW: 0.75,
}


@dataclass(frozen=True, slots=True)
class RiskEvent:
    """One structured risk event from the Watcher.

    Required fields are the agreed temporary format. Everything below
    `detected_at` is optional enrichment A can add later without breaking B.
    """

    connection_id: str
    state: RiskSeverity
    current_plan_slack_hours: float
    no_itt_slack_hours: float
    avoidable_by_terminal_prevention: bool
    affected_boxes: int
    watcher_confidence: WatcherConfidence
    reason_codes: tuple[ReasonCode, ...] = ()

    # Optional enrichment. Absent in the mock feed; expected once A has the
    # real Watcher running and the day-1 data gate has resolved.
    detected_at: datetime | None = None
    ucid: str | None = None
    inbound_terminal: Terminal = Terminal.UNKNOWN
    outbound_terminal: Terminal = Terminal.UNKNOWN
    terminal_resolution: TerminalResolution = TerminalResolution.SIMULATED
    assumptions: "Assumptions" = field(default_factory=lambda: Assumptions())
    inbound_vessel: str = "UNKNOWN"
    outbound_vessel: str = "UNKNOWN"
    source: str = "watcher.mock"

    # --- derived signals ----------------------------------------------------

    @property
    def is_actionable(self) -> bool:
        """SAFE never reaches the agent. WATCH does, cheaply."""
        return self.state is not RiskSeverity.SAFE

    @property
    def slack_deficit_hours(self) -> float:
        """How short the current plan is. Zero when it already fits."""
        return max(-self.current_plan_slack_hours, 0.0)

    @property
    def itt_cost_hours(self) -> float:
        """What the inter-terminal leg is costing this connection.

        The gap between the two slack figures A sends. When it is larger than
        the deficit, the transfer *is* the problem and prevention is on the table.
        """
        return self.no_itt_slack_hours - self.current_plan_slack_hours

    @property
    def itt_is_the_problem(self) -> bool:
        """True when removing the transfer would save the connection outright.

        This is the single most useful thing A sends: it decides whether Rung 1
        is a live option or merely advisory noise.
        """
        return (
            self.avoidable_by_terminal_prevention
            and self.no_itt_slack_hours > 0
            and self.current_plan_slack_hours <= 0
        )

    @property
    def priority(self) -> float:
        """affected_boxes over remaining hours, floored.

        What the Lock Table arbitrates on. Negative slack floors rather than
        inverting sign, so an already-blown connection is maximally urgent
        without being infinitely so.
        """
        return self.affected_boxes / max(self.current_plan_slack_hours, MIN_SLACK_HOURS)

    @property
    def confidence_factor(self) -> float:
        return WATCHER_CONFIDENCE_FACTOR[self.watcher_confidence]

    def provenance(self) -> Provenance:
        """A's assessment, as an input to B's confidence calculation.

        A MEDIUM is treated as a cache-grade input and a LOW as an assumed
        default, so the Watcher's own uncertainty propagates into the gate
        rather than being discarded at the boundary.
        """
        source = {
            WatcherConfidence.HIGH: SourceKind.LIVE_API,
            WatcherConfidence.MEDIUM: SourceKind.CACHE,
            WatcherConfidence.LOW: SourceKind.ASSUMED_DEFAULT,
        }[self.watcher_confidence]
        return Provenance(
            field_name="watcher_assessment",
            source=source,
            verified=self.watcher_confidence is WatcherConfidence.HIGH,
        )

    # --- wire format --------------------------------------------------------

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RiskEvent":
        """Parse the agreed format. Unknown reason codes fail loudly.

        A silently-dropped reason code would change which rungs the agent
        considers without anyone noticing, so this raises rather than skipping.
        """
        detected = payload.get("detected_at")
        return cls(
            connection_id=payload["connection_id"],
            state=RiskSeverity(payload["state"]),
            current_plan_slack_hours=float(payload["current_plan_slack_hours"]),
            no_itt_slack_hours=float(payload["no_itt_slack_hours"]),
            avoidable_by_terminal_prevention=bool(
                payload["avoidable_by_terminal_prevention"]
            ),
            affected_boxes=int(payload["affected_boxes"]),
            watcher_confidence=WatcherConfidence(payload["confidence"]),
            reason_codes=tuple(ReasonCode(c) for c in payload.get("reason_codes", ())),
            detected_at=datetime.fromisoformat(detected) if detected else None,
            ucid=payload.get("ucid"),
            inbound_terminal=Terminal(payload.get("inbound_terminal", "unknown")),
            outbound_terminal=Terminal(payload.get("outbound_terminal", "unknown")),
            terminal_resolution=TerminalResolution(
                payload.get("terminal_resolution", "simulated")
            ),
            inbound_vessel=payload.get("inbound_vessel", "UNKNOWN"),
            outbound_vessel=payload.get("outbound_vessel", "UNKNOWN"),
            source=payload.get("source", "watcher.mock"),
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "connection_id": self.connection_id,
            "state": self.state.value,
            "current_plan_slack_hours": self.current_plan_slack_hours,
            "no_itt_slack_hours": self.no_itt_slack_hours,
            "avoidable_by_terminal_prevention": self.avoidable_by_terminal_prevention,
            "affected_boxes": self.affected_boxes,
            "confidence": self.watcher_confidence.value,
            "reason_codes": [c.value for c in self.reason_codes],
        }
        if self.detected_at is not None:
            payload["detected_at"] = self.detected_at.isoformat()
        if self.ucid is not None:
            payload["ucid"] = self.ucid
        return payload

    # --- adapter ------------------------------------------------------------

    def to_connection_risk(self) -> ConnectionRisk:
        """Adapt into B's internal model.

        Everything A does not send yet is filled in as UNKNOWN and marked
        `SIMULATED`, so the gap is visible in the trace rather than papered
        over with a plausible-looking default. When A starts sending terminals
        and vessel names, only this method changes.
        """
        detected = self.detected_at or datetime.now(UTC)
        total_min = max(self.no_itt_slack_hours, 0.0) * 60.0
        remaining_min = self.current_plan_slack_hours * 60.0

        inbound = VesselCall(
            vessel_name=self.inbound_vessel,
            service_code="UNKNOWN",
            terminal=self.inbound_terminal,
            terminal_resolution=self.terminal_resolution,
            scheduled=detected,
            estimated=detected + timedelta(hours=self.slack_deficit_hours),
        )
        outbound = VesselCall(
            vessel_name=self.outbound_vessel,
            service_code="UNKNOWN",
            terminal=self.outbound_terminal,
            terminal_resolution=self.terminal_resolution,
            scheduled=detected + timedelta(minutes=total_min),
            estimated=detected + timedelta(minutes=total_min),
        )
        return ConnectionRisk(
            risk_id=self.connection_id,
            ucid=self.ucid or f"UCID-PENDING-{self.connection_id}",
            detected_at=detected,
            inbound=inbound,
            outbound=outbound,
            boxes_at_risk=self.affected_boxes,
            slack_total_min=total_min,
            slack_remaining_min=remaining_min,
            source=self.source,
        )
