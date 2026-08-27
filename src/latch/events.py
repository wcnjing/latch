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

_CAUSAL_TIMING_FIELDS = (
    "inbound_reference_arrival",
    "inbound_predicted_arrival",
    "outbound_reference_arrival",
    "outbound_predicted_arrival",
)


def _optional_datetime(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    raise TypeError("causal arrival timing must be an ISO-8601 string or datetime")


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


class TimingResolution(StrEnum):
    """How the vessel arrival values on a risk event were obtained.

    ``DERIVED_CAUSAL_ARRIVAL`` means all four arrivals came from causal
    predictions derived from real AIS observations.  It does not mean the
    values are official schedules or observed berth arrivals.

    ``LEGACY_SLACK_FALLBACK`` means the event carries no causal arrivals and
    the adapter reconstructs display-only vessel times from the event's slack.
    """

    DERIVED_CAUSAL_ARRIVAL = "derived_causal_arrival"
    LEGACY_SLACK_FALLBACK = "legacy_slack_fallback"


def _timing_resolution_from(payload: dict[str, Any]) -> TimingResolution:
    """Parse explicit provenance or infer the pre-provenance wire format.

    Main emitted causal events with all four arrival keys before
    ``timing_resolution`` was added.  A payload without either enrichment is
    the older slack-based format.  Anything between those two complete shapes
    is malformed rather than a third compatibility format.
    """
    if "timing_resolution" in payload:
        return TimingResolution(payload["timing_resolution"])

    present = tuple(name for name in _CAUSAL_TIMING_FIELDS if name in payload)
    if not present:
        return TimingResolution.LEGACY_SLACK_FALLBACK
    if len(present) == len(_CAUSAL_TIMING_FIELDS):
        return TimingResolution.DERIVED_CAUSAL_ARRIVAL

    missing = tuple(name for name in _CAUSAL_TIMING_FIELDS if name not in payload)
    raise ValueError(
        "missing timing_resolution with partial causal vessel timing; "
        f"supplied {', '.join(present)}; missing {', '.join(missing)}"
    )


class ConnectionType(StrEnum):
    """Whether the cargo has to cross terminals. The one structural fact the
    agent reasons about, and it is assumed rather than observed."""

    SAME_TERMINAL = "SAME_TERMINAL"
    INTER_TERMINAL = "INTER_TERMINAL"

    @classmethod
    def from_crossing(cls, crosses: bool) -> "ConnectionType":
        """Single definition of the mapping, shared with the watcher adapter.

        Derived in two places before this, by two different routes, and #7 was
        a case where one path was right and the other wrong.
        """
        return cls.INTER_TERMINAL if crosses else cls.SAME_TERMINAL


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
    INBOUND_PREDICTION_UNAVAILABLE = "INBOUND_PREDICTION_UNAVAILABLE"
    OUTBOUND_PREDICTION_UNAVAILABLE = "OUTBOUND_PREDICTION_UNAVAILABLE"


# How much A's own confidence discounts a plan built on its numbers. A LOW
# from the Watcher should not produce a plan we auto-approve.
WATCHER_CONFIDENCE_FACTOR: dict[WatcherConfidence, float] = {
    WatcherConfidence.HIGH: 1.00,
    WatcherConfidence.MEDIUM: 0.90,
    WatcherConfidence.LOW: 0.75,
}


def _assumptions_from(payload: dict[str, Any]) -> "Assumptions":
    """Derive the assumption block for an event parsed from the wire.

    `from_dict` used to leave this at its default, so every connection loaded
    through `--events` recorded SAME_TERMINAL regardless of its terminals, and
    still recorded every provenance flag as synthetic even when the payload
    said otherwise. Those values land in an append-only trace, so a console
    cannot correct them downstream — they are already in the record.

    Two rules govern the derivation:

    Unknown provenance is treated as synthetic. An event that does not say
    where a value came from gets the claim that cannot mislead.

    A disagreement resolves toward INTER_TERMINAL. If the terminals look
    identical but A reports a transfer on the critical path, believing the
    terminals would drop the prevention rung entirely; believing the flag
    costs at most one advisory nobody needed. The asymmetry is deliberate.
    """
    declared = payload.get("connection_type")
    if declared is not None:
        connection_type = ConnectionType(declared)
    else:
        inbound = Terminal(payload.get("inbound_terminal", "unknown"))
        outbound = Terminal(payload.get("outbound_terminal", "unknown"))
        both_known = Terminal.UNKNOWN not in (inbound, outbound)
        terminals_differ = both_known and inbound is not outbound
        flagged = bool(payload.get("avoidable_by_terminal_prevention"))
        connection_type = ConnectionType.from_crossing(terminals_differ or flagged)

    # Only SIMULATED terminals are ours. A berth, a named terminal or a stated
    # inference all came from somewhere real, however imprecisely.
    resolution = TerminalResolution(payload.get("terminal_resolution", "simulated"))
    scenario = payload.get("transfer_scenario")

    return Assumptions(
        connection_type=connection_type,
        ucid_synthetic=bool(payload.get("ucid_synthetic", payload.get("ucid") is None)),
        pairing_synthetic=bool(payload.get("pairing_synthetic", True)),
        terminals_synthetic=bool(
            payload.get(
                "terminals_synthetic", resolution is TerminalResolution.SIMULATED
            )
        ),
        boxes_synthetic=bool(payload.get("boxes_synthetic", True)),
        # `is not None` rather than truthiness: an explicitly empty scenario is
        # a producer error worth seeing, not a request for the default label.
        **({"transfer_scenario": scenario} if scenario is not None else {}),
    )


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
    timing_resolution: TimingResolution
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

    # PR #4 causal timing enrichment.  Older event producers omit all four and
    # retain the historical adapter fallback below.  New Watcher events carry
    # the actual selected PR #2 values so the adapter never fabricates vessel
    # times from assessment time and slack.
    inbound_reference_arrival: datetime | None = None
    inbound_predicted_arrival: datetime | None = None
    outbound_reference_arrival: datetime | None = None
    outbound_predicted_arrival: datetime | None = None

    def __post_init__(self) -> None:
        timing = {
            "inbound_reference_arrival": self.inbound_reference_arrival,
            "inbound_predicted_arrival": self.inbound_predicted_arrival,
            "outbound_reference_arrival": self.outbound_reference_arrival,
            "outbound_predicted_arrival": self.outbound_predicted_arrival,
        }
        supplied = tuple(name for name, value in timing.items() if value is not None)

        if self.timing_resolution is TimingResolution.DERIVED_CAUSAL_ARRIVAL:
            missing = tuple(name for name, value in timing.items() if value is None)
            if missing:
                raise ValueError(
                    "derived causal vessel timing requires all four arrivals; "
                    f"missing {', '.join(missing)}"
                )
            if self.detected_at is None:
                raise ValueError(
                    "derived causal vessel timing requires detected_at"
                )
            for name, value in (("detected_at", self.detected_at), *timing.items()):
                # Keep the explicit type guard so malformed direct construction
                # fails here rather than inside the agent adapter.
                if (
                    not isinstance(value, datetime)
                    or value.tzinfo is None
                    or value.utcoffset() is None
                ):
                    raise ValueError(f"{name} must be timezone-aware")
        elif self.timing_resolution is TimingResolution.LEGACY_SLACK_FALLBACK:
            if supplied:
                raise ValueError(
                    "legacy slack fallback must not include causal vessel timing; "
                    f"supplied {', '.join(supplied)}"
                )
        else:
            raise TypeError("timing_resolution must be a TimingResolution")

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
            and self.no_itt_slack_hours >= 0
            and self.current_plan_slack_hours < 0
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
            timing_resolution=_timing_resolution_from(payload),
            reason_codes=tuple(ReasonCode(c) for c in payload.get("reason_codes", ())),
            detected_at=datetime.fromisoformat(detected) if detected else None,
            ucid=payload.get("ucid"),
            inbound_terminal=Terminal(payload.get("inbound_terminal", "unknown")),
            outbound_terminal=Terminal(payload.get("outbound_terminal", "unknown")),
            terminal_resolution=TerminalResolution(
                payload.get("terminal_resolution", "simulated")
            ),
            assumptions=_assumptions_from(payload),
            inbound_vessel=payload.get("inbound_vessel", "UNKNOWN"),
            outbound_vessel=payload.get("outbound_vessel", "UNKNOWN"),
            source=payload.get("source", "watcher.mock"),
            inbound_reference_arrival=_optional_datetime(
                payload.get("inbound_reference_arrival")
            ),
            inbound_predicted_arrival=_optional_datetime(
                payload.get("inbound_predicted_arrival")
            ),
            outbound_reference_arrival=_optional_datetime(
                payload.get("outbound_reference_arrival")
            ),
            outbound_predicted_arrival=_optional_datetime(
                payload.get("outbound_predicted_arrival")
            ),
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
            "timing_resolution": self.timing_resolution.value,
            "reason_codes": [c.value for c in self.reason_codes],
        }
        if self.detected_at is not None:
            payload["detected_at"] = self.detected_at.isoformat()
        if self.ucid is not None:
            payload["ucid"] = self.ucid
        payload.update(
            {
                "inbound_terminal": self.inbound_terminal.value,
                "outbound_terminal": self.outbound_terminal.value,
                "terminal_resolution": self.terminal_resolution.value,
                "inbound_vessel": self.inbound_vessel,
                "outbound_vessel": self.outbound_vessel,
                "source": self.source,
                **self.assumptions.as_dict(),
            }
        )
        for key, value in (
            ("inbound_reference_arrival", self.inbound_reference_arrival),
            ("inbound_predicted_arrival", self.inbound_predicted_arrival),
            ("outbound_reference_arrival", self.outbound_reference_arrival),
            ("outbound_predicted_arrival", self.outbound_predicted_arrival),
        ):
            if value is not None:
                payload[key] = value.isoformat()
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

        if self.timing_resolution is TimingResolution.DERIVED_CAUSAL_ARRIVAL:
            inbound_scheduled = self.inbound_reference_arrival
            inbound_estimated = self.inbound_predicted_arrival
            outbound_scheduled = self.outbound_reference_arrival
            outbound_estimated = self.outbound_predicted_arrival
        else:
            # Backwards-compatible behavior for legacy/demo RiskEvents that did
            # not carry PR #2 causal timing metadata.
            inbound_scheduled = detected
            inbound_estimated = detected + timedelta(hours=self.slack_deficit_hours)
            outbound_scheduled = detected + timedelta(minutes=total_min)
            outbound_estimated = outbound_scheduled

        inbound = VesselCall(
            vessel_name=self.inbound_vessel,
            service_code="UNKNOWN",
            terminal=self.inbound_terminal,
            terminal_resolution=self.terminal_resolution,
            scheduled=inbound_scheduled,
            estimated=inbound_estimated,
        )
        outbound = VesselCall(
            vessel_name=self.outbound_vessel,
            service_code="UNKNOWN",
            terminal=self.outbound_terminal,
            terminal_resolution=self.terminal_resolution,
            scheduled=outbound_scheduled,
            estimated=outbound_estimated,
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
