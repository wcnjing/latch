"""The A to B bridge: arrival predictions become connection risks.

Workstream A predicts *when a vessel will arrive* from real AIS observations.
Workstream B decides *what to do about a connection at risk*. Those are
different questions with different label spaces, and this module is the only
place they meet.

    CausalArrivalUpdate  ──┐
    (real AIS timing)      ├──▶  RiskEvent  ──▶  agent core
    SyntheticConnection  ──┘
    (invented graph)

The split is the honesty story in one diagram. Arrival timing is real and
measured against observed crossings; the connection, its terminals, its box
count and its cutoff are ours. Every event this module emits therefore carries
`TerminalResolution.SIMULATED`, which travels into the trace and lowers the
agent's confidence — so the synthetic origin is enforced by the pipeline
rather than asserted in a slide.

`ArrivalSignal` is a structural protocol rather than an import of A's concrete
class, so A can rename or extend `CausalArrivalUpdate` without breaking this
bridge. Only the fields named below are load-bearing.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Iterable, Protocol, runtime_checkable

from latch.connections import ConnectionParams, SyntheticConnection, connection_for
from latch.events import (
    Assumptions,
    ConnectionType,
    ReasonCode,
    RiskEvent,
    RiskSeverity,
    WatcherConfidence,
)
from latch.models import TerminalResolution
from latch.replay import (
    CausalArrivalUpdate,
    DataQuality,
    PredictionStatus,
    calculate_data_age_minutes,
)
from latch.synthetic import (
    BenchmarkEvidence,
    BenchmarkTerminal,
    ImpactBand,
    ProcessProjection,
    ProcessScenario,
    SyntheticConnection as BenchmarkSyntheticConnection,
    TransferMode,
    UCIDAssignment,
    UCIDConnectionIdentity,
)

# A's DataQuality values, mapped to how much B should trust the assessment.
# Deliberately not an import: a rename upstream should surface here as an
# unmapped value we notice, not as a silent AttributeError at run time.
_QUALITY_TO_CONFIDENCE: dict[str, WatcherConfidence] = {
    "good": WatcherConfidence.HIGH,
    "degraded": WatcherConfidence.MEDIUM,
    "excluded": WatcherConfidence.LOW,
}

# Drift below this is measurement noise, not a slipping vessel.
ETA_SLIP_TOLERANCE_MIN = 15.0


@runtime_checkable
class ArrivalSignal(Protocol):
    """The minimum A must provide. Everything else on their type is ignored."""

    call_id: str
    vessel_id: str
    observed_at: datetime
    predicted_arrival: datetime | None
    reference_arrival: datetime | None


@dataclass(frozen=True, slots=True)
class SlackBreakdown:
    """The arithmetic, kept so the console can show its working."""

    cargo_ready: datetime
    outbound_cutoff: datetime
    no_itt_slack_h: float
    transfer_h: float
    current_plan_slack_h: float
    eta_slip_min: float


def _confidence(signal: object) -> WatcherConfidence:
    quality = getattr(signal, "data_quality", None)
    key = getattr(quality, "value", quality)
    if key is None:
        # A signal that does not say how good it is gets no benefit of the
        # doubt. Absent provenance is weaker than stated-poor provenance.
        return WatcherConfidence.LOW
    return _QUALITY_TO_CONFIDENCE.get(str(key), WatcherConfidence.LOW)


def compute_slack(
    signal: ArrivalSignal, connection: SyntheticConnection
) -> SlackBreakdown | None:
    """Turn a predicted arrival into slack against the connection's cutoff.

    Returns None when there is no prediction. An ineligible observation is not
    an arrival at an unknown time — it is no arrival estimate at all, and
    substituting one would be inventing the very thing A refused to guess.
    """
    if signal.predicted_arrival is None:
        return None

    params = connection.params
    cargo_ready = signal.predicted_arrival + _hours(params.berth_and_discharge_h)
    no_itt_slack_h = (
        connection.outbound_cutoff - cargo_ready
    ).total_seconds() / 3600.0
    transfer_h = connection.transfer_hours

    reference = signal.reference_arrival
    slip_min = (
        (signal.predicted_arrival - reference).total_seconds() / 60.0
        if reference is not None
        else 0.0
    )

    return SlackBreakdown(
        cargo_ready=cargo_ready,
        outbound_cutoff=connection.outbound_cutoff,
        no_itt_slack_h=no_itt_slack_h,
        transfer_h=transfer_h,
        current_plan_slack_h=no_itt_slack_h - transfer_h,
        eta_slip_min=slip_min,
    )


def _hours(value: float):
    from datetime import timedelta

    return timedelta(hours=value)


def _severity(slack_h: float, params: ConnectionParams) -> RiskSeverity:
    if slack_h <= 0:
        return RiskSeverity.AT_RISK
    if slack_h < params.watch_threshold_h:
        return RiskSeverity.WATCH
    return RiskSeverity.SAFE


def _reason_codes(
    breakdown: SlackBreakdown, connection: SyntheticConnection
) -> tuple[ReasonCode, ...]:
    """Why this connection is under pressure.

    A's quality codes are deliberately *not* mapped in here. They describe how
    good the observation was, not why the cargo is at risk, and they already
    reach the agent through watcher confidence. Folding them in would double-
    count uncertainty as causation.
    """
    codes: list[ReasonCode] = []
    if breakdown.eta_slip_min > ETA_SLIP_TOLERANCE_MIN:
        codes.append(ReasonCode.INBOUND_ETA_SLIP)
    if connection.requires_transfer:
        codes.append(ReasonCode.INTER_TERMINAL_TRANSFER_TIME)
    return tuple(codes)


def to_risk_event(
    signal: ArrivalSignal, connection: SyntheticConnection
) -> RiskEvent | None:
    """Adapt one arrival signal into a risk event. None when unpredictable."""
    breakdown = compute_slack(signal, connection)
    if breakdown is None:
        return None

    return RiskEvent(
        connection_id=connection.connection_id,
        state=_severity(breakdown.current_plan_slack_h, connection.params),
        current_plan_slack_hours=round(breakdown.current_plan_slack_h, 3),
        no_itt_slack_hours=round(breakdown.no_itt_slack_h, 3),
        # A statement of fact — a transfer sits on the critical path — not a
        # judgement that removing it would save the connection. `RiskEvent`
        # derives that itself from the two slack figures.
        avoidable_by_terminal_prevention=connection.requires_transfer,
        affected_boxes=connection.boxes,
        watcher_confidence=_confidence(signal),
        reason_codes=_reason_codes(breakdown, connection),
        detected_at=signal.observed_at,
        ucid=f"UCID-SYNTH-{connection.connection_id.removeprefix('conn_')}",
        assumptions=Assumptions(
            connection_type=ConnectionType.from_crossing(
                connection.requires_transfer
            ),
            transfer_scenario=(
                "configured reference transfer scenario "
                f"({connection.params.planned_transfer_h:.1f}h assumed transfer)"
            ),
        ),
        inbound_terminal=connection.inbound_terminal,
        outbound_terminal=connection.outbound_terminal,
        # The terminals are ours, not the feed's. This lowers confidence
        # downstream, which is correct and deliberate.
        terminal_resolution=TerminalResolution.SIMULATED,
        inbound_vessel=signal.vessel_id,
        outbound_vessel=connection.outbound_service,
        source="ais_replay+synthetic_connection",
    )


def events_from_signals(
    signals,
    params: ConnectionParams = ConnectionParams(),
):
    """Adapt a stream of arrival signals, skipping the unpredictable ones.

    One connection per call, generated once and reused across that call's
    updates, so slack tightens as the vessel slips rather than the window
    moving with it.
    """
    connections: dict[str, SyntheticConnection] = {}
    for signal in signals:
        anchor = signal.reference_arrival or signal.predicted_arrival
        if anchor is None:
            continue
        connection = connections.get(signal.call_id)
        if connection is None:
            connection = connection_for(
                signal.call_id, signal.vessel_id, anchor, params
            )
            connections[signal.call_id] = connection
        event = to_risk_event(signal, connection)
        if event is not None:
            yield event


# --- PR #4 causal connection assessment ------------------------------------
#
# The functions above are the original inbound-only demo bridge.  They remain
# intact because historical/demo callers still use ``latch.connections``.  The
# PR #4 path below consumes the merged PR #3 graph directly and never generates
# a connection or UCID of its own.


class AssessmentStatus(StrEnum):
    """Whether both causal vessel predictions exist at assessment time."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class WatcherConfig:
    """Experimental Watcher thresholds and one selected PR #3 scenario.

    The two durations are benchmark configuration, not PSA or industry
    operating standards.  They are required explicitly so a caller cannot
    accidentally inherit an unstated operational threshold.
    """

    warning_margin: timedelta
    reference_delay_threshold: timedelta
    process_scenario: ProcessScenario = ProcessScenario.REFERENCE

    def __post_init__(self) -> None:
        if self.warning_margin < timedelta(0):
            raise ValueError("warning_margin must not be negative")
        if self.reference_delay_threshold < timedelta(0):
            raise ValueError("reference_delay_threshold must not be negative")


@dataclass(frozen=True, slots=True)
class ConnectionSlackBreakdown:
    """Auditable PR #4 arithmetic from two current causal predictions."""

    inbound_predicted_arrival: datetime
    outbound_predicted_arrival: datetime
    cargo_ready_offset: timedelta
    inbound_cargo_ready_at: datetime
    transfer_duration: timedelta
    current_plan_ready_at: datetime
    cargo_cutoff_lead: timedelta
    outbound_cargo_cutoff: datetime
    current_plan_slack: timedelta
    no_itt_slack: timedelta

    @property
    def current_plan_slack_h(self) -> float:
        return self.current_plan_slack.total_seconds() / 3600.0

    @property
    def no_itt_slack_h(self) -> float:
        return self.no_itt_slack.total_seconds() / 3600.0

    @property
    def transfer_h(self) -> float:
        return self.transfer_duration.total_seconds() / 3600.0


@dataclass(frozen=True, slots=True)
class DerivedReferenceDelayAssessment:
    """The derived reference-delay baseline, never an official schedule rule."""

    call_id: str | None
    assessed_at: datetime
    predicted_arrival: datetime | None
    reference_arrival: datetime | None
    delay: timedelta | None
    threshold: timedelta
    alert: bool | None
    data_quality: DataQuality | None
    quality_reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ConnectionRiskAssessment:
    """Canonical PR #4 result, including unavailable causal assessments.

    PR #2 supplies real AIS-derived timing.  The identity, topology, process
    scenario, impact and evidence below are the immutable synthetic PR #3
    benchmark assignment.  Historical call IDs are retained only as opaque
    join keys; they are never used in the arithmetic or UCID construction.
    """

    identity: UCIDConnectionIdentity
    assignment: UCIDAssignment
    origin: BenchmarkTerminal
    destination: BenchmarkTerminal
    assessed_at: datetime
    status: AssessmentStatus
    severity: RiskSeverity | None
    inbound_prediction: CausalArrivalUpdate | None
    outbound_prediction: CausalArrivalUpdate | None
    inbound_prediction_age_min: float | None
    outbound_prediction_age_min: float | None
    slack: ConnectionSlackBreakdown | None
    avoidable_by_terminal_prevention: bool
    reason_codes: tuple[ReasonCode, ...]
    data_quality: DataQuality | None
    inbound_quality_reason_codes: tuple[str, ...]
    outbound_quality_reason_codes: tuple[str, ...]
    process_scenario: ProcessScenario
    transfer_mode: TransferMode
    impact_band: ImpactBand
    box_count: int | None
    topology_version: str
    evidence: tuple[BenchmarkEvidence, ...]
    baseline: DerivedReferenceDelayAssessment

    @property
    def ucid(self) -> str:
        return self.identity.ucid


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _update_order(update: CausalArrivalUpdate) -> tuple[datetime, int]:
    return update.observed_at, update.source_observation.source_row_number


def _select_latest(
    updates: Iterable[CausalArrivalUpdate],
    *,
    assessed_at: datetime,
    available_only: bool,
) -> dict[str, CausalArrivalUpdate]:
    selected: dict[str, CausalArrivalUpdate] = {}
    selected_keys: dict[str, tuple[datetime, int]] = {}
    for update in updates:
        if update.observed_at > assessed_at:
            continue
        if available_only and not (
            update.prediction_status is PredictionStatus.AVAILABLE
            and update.predicted_arrival is not None
            and update.reference_arrival is not None
        ):
            continue
        key = _update_order(update)
        previous_key = selected_keys.get(update.call_id)
        if previous_key is None or key > previous_key:
            selected[update.call_id] = update
            selected_keys[update.call_id] = key
        elif key == previous_key and selected[update.call_id] != update:
            raise ValueError(
                "conflicting causal updates share call_id, observed_at, and source row"
            )
    return selected


def latest_available_predictions(
    updates: Iterable[CausalArrivalUpdate],
    *,
    assessed_at: datetime,
) -> dict[str, CausalArrivalUpdate]:
    """Select each call's latest AVAILABLE prediction known at ``assessed_at``.

    Future observations and ineligible updates are ignored.  A later ineligible
    observation therefore does not erase the latest earlier available estimate.
    The retrospectively constructed call ID is used only as the dictionary join
    key.  No crossing outcome or PR #3 reference timestamp is consulted.
    """

    _require_aware(assessed_at, "assessed_at")
    return _select_latest(updates, assessed_at=assessed_at, available_only=True)


def assess_derived_reference_delay(
    inbound: CausalArrivalUpdate | None,
    *,
    assessed_at: datetime,
    threshold: timedelta,
) -> DerivedReferenceDelayAssessment:
    """Evaluate the derived reference-delay baseline from one inbound update.

    ``reference_arrival`` is PR #2's first available derived prediction, not an
    official PSA schedule.  This function deliberately has no connection or
    outbound input, making topology/process contamination impossible.
    """

    _require_aware(assessed_at, "assessed_at")
    if inbound is not None and inbound.observed_at > assessed_at:
        raise ValueError(
            "a future inbound observation cannot be assessed at an earlier time"
        )
    if threshold < timedelta(0):
        raise ValueError("threshold must not be negative")
    if inbound is None or not (
        inbound.observed_at <= assessed_at
        and inbound.prediction_status is PredictionStatus.AVAILABLE
        and inbound.predicted_arrival is not None
        and inbound.reference_arrival is not None
    ):
        return DerivedReferenceDelayAssessment(
            call_id=inbound.call_id if inbound is not None else None,
            assessed_at=assessed_at,
            predicted_arrival=None,
            reference_arrival=None,
            delay=None,
            threshold=threshold,
            alert=None,
            data_quality=inbound.data_quality if inbound is not None else None,
            quality_reason_codes=(
                inbound.quality_reason_codes if inbound is not None else ()
            ),
        )
    delay = inbound.predicted_arrival - inbound.reference_arrival
    return DerivedReferenceDelayAssessment(
        call_id=inbound.call_id,
        assessed_at=assessed_at,
        predicted_arrival=inbound.predicted_arrival,
        reference_arrival=inbound.reference_arrival,
        delay=delay,
        threshold=threshold,
        alert=delay >= threshold,
        data_quality=inbound.data_quality,
        quality_reason_codes=inbound.quality_reason_codes,
    )


_QUALITY_RANK: dict[DataQuality, int] = {
    DataQuality.GOOD: 0,
    DataQuality.DEGRADED: 1,
    DataQuality.EXCLUDED: 2,
}


def _weaker_quality(
    updates: Iterable[CausalArrivalUpdate | None],
) -> DataQuality | None:
    qualities = [item.data_quality for item in updates if item is not None]
    return max(qualities, key=_QUALITY_RANK.__getitem__) if qualities else None


def _projection_for(
    connection: BenchmarkSyntheticConnection, scenario: ProcessScenario
) -> ProcessProjection:
    matches = tuple(
        item for item in connection.process_projections if item.scenario is scenario
    )
    if len(matches) != 1:
        raise ValueError(
            f"connection {connection.identity.ucid} must contain exactly one "
            f"{scenario.value} process projection"
        )
    return matches[0]


def _validate_topology(
    connection: BenchmarkSyntheticConnection, projection: ProcessProjection
) -> bool:
    same_terminal = connection.origin.terminal == connection.destination.terminal
    if same_terminal and not (
        projection.transfer_mode is TransferMode.NONE
        and projection.transfer_duration == timedelta(0)
    ):
        raise ValueError(
            "same-terminal PR #3 connection must use NONE and zero transfer duration"
        )
    if not same_terminal and (
        projection.transfer_mode is TransferMode.NONE
        or projection.transfer_duration <= timedelta(0)
    ):
        raise ValueError(
            "inter-terminal PR #3 connection must use a positive ROAD or SEA transfer"
        )
    return same_terminal


def _assessment_severity(
    slack: timedelta, warning_margin: timedelta
) -> RiskSeverity:
    if slack <= timedelta(0):
        return RiskSeverity.AT_RISK
    if slack <= warning_margin:
        return RiskSeverity.WATCH
    return RiskSeverity.SAFE


def _assessment_reason_codes(
    inbound: CausalArrivalUpdate,
    outbound: CausalArrivalUpdate,
    *,
    same_terminal: bool,
) -> tuple[ReasonCode, ...]:
    codes: list[ReasonCode] = []
    assert inbound.predicted_arrival is not None
    assert inbound.reference_arrival is not None
    assert outbound.predicted_arrival is not None
    assert outbound.reference_arrival is not None
    if inbound.predicted_arrival - inbound.reference_arrival > timedelta(
        minutes=ETA_SLIP_TOLERANCE_MIN
    ):
        codes.append(ReasonCode.INBOUND_ETA_SLIP)
    if outbound.reference_arrival - outbound.predicted_arrival > timedelta(
        minutes=ETA_SLIP_TOLERANCE_MIN
    ):
        codes.append(ReasonCode.OUTBOUND_CUTOFF_ADVANCED)
    if not same_terminal:
        codes.append(ReasonCode.INTER_TERMINAL_TRANSFER_TIME)
    return tuple(codes)


def assess_connection(
    connection: BenchmarkSyntheticConnection,
    updates: Iterable[CausalArrivalUpdate],
    *,
    assessed_at: datetime,
    config: WatcherConfig,
) -> ConnectionRiskAssessment:
    """Assess one immutable PR #3 connection using only PR #2 values by time t.

    The PR #3 projection contributes assumptions only.  Its reference-derived
    cargo-ready time, cutoff, margin and difficulty are deliberately ignored.
    The input stream may be retrospectively segmented historically, but no final
    crossing, eligibility, exclusion, or completed-track field is accepted.
    """

    _require_aware(assessed_at, "assessed_at")
    materialized = tuple(updates)
    available = latest_available_predictions(materialized, assessed_at=assessed_at)
    latest_known = _select_latest(
        materialized, assessed_at=assessed_at, available_only=False
    )
    projection = _projection_for(connection, config.process_scenario)
    same_terminal = _validate_topology(connection, projection)

    inbound_call_id = connection.assignment.inbound_source_call_id
    outbound_call_id = connection.assignment.outbound_source_call_id
    inbound = available.get(inbound_call_id)
    outbound = available.get(outbound_call_id)
    inbound_quality_source = inbound or latest_known.get(inbound_call_id)
    outbound_quality_source = outbound or latest_known.get(outbound_call_id)
    baseline = assess_derived_reference_delay(
        inbound,
        assessed_at=assessed_at,
        threshold=config.reference_delay_threshold,
    )

    common = {
        "identity": connection.identity,
        "assignment": connection.assignment,
        "origin": connection.origin,
        "destination": connection.destination,
        "assessed_at": assessed_at,
        "inbound_prediction": inbound,
        "outbound_prediction": outbound,
        "inbound_prediction_age_min": (
            calculate_data_age_minutes(inbound.observed_at, assessed_at)
            if inbound is not None
            else None
        ),
        "outbound_prediction_age_min": (
            calculate_data_age_minutes(outbound.observed_at, assessed_at)
            if outbound is not None
            else None
        ),
        "data_quality": _weaker_quality(
            (inbound_quality_source, outbound_quality_source)
        ),
        "inbound_quality_reason_codes": (
            inbound_quality_source.quality_reason_codes
            if inbound_quality_source is not None
            else ()
        ),
        "outbound_quality_reason_codes": (
            outbound_quality_source.quality_reason_codes
            if outbound_quality_source is not None
            else ()
        ),
        "process_scenario": projection.scenario,
        "transfer_mode": projection.transfer_mode,
        "impact_band": connection.impact_band,
        "box_count": connection.box_count,
        "topology_version": connection.identity.topology_version,
        "evidence": connection.evidence,
        "baseline": baseline,
    }

    if inbound is None or outbound is None:
        unavailable_codes: list[ReasonCode] = []
        if inbound is None:
            unavailable_codes.append(ReasonCode.INBOUND_PREDICTION_UNAVAILABLE)
        if outbound is None:
            unavailable_codes.append(ReasonCode.OUTBOUND_PREDICTION_UNAVAILABLE)
        return ConnectionRiskAssessment(
            **common,
            status=AssessmentStatus.UNAVAILABLE,
            severity=None,
            slack=None,
            avoidable_by_terminal_prevention=False,
            reason_codes=tuple(unavailable_codes),
        )

    assert inbound.predicted_arrival is not None
    assert outbound.predicted_arrival is not None
    inbound_cargo_ready_at = (
        inbound.predicted_arrival + projection.cargo_ready_offset
    )
    outbound_cargo_cutoff = (
        outbound.predicted_arrival - projection.cargo_cutoff_lead
    )
    current_plan_ready_at = inbound_cargo_ready_at + projection.transfer_duration
    current_plan_slack = outbound_cargo_cutoff - current_plan_ready_at
    no_itt_slack = outbound_cargo_cutoff - inbound_cargo_ready_at
    breakdown = ConnectionSlackBreakdown(
        inbound_predicted_arrival=inbound.predicted_arrival,
        outbound_predicted_arrival=outbound.predicted_arrival,
        cargo_ready_offset=projection.cargo_ready_offset,
        inbound_cargo_ready_at=inbound_cargo_ready_at,
        transfer_duration=projection.transfer_duration,
        current_plan_ready_at=current_plan_ready_at,
        cargo_cutoff_lead=projection.cargo_cutoff_lead,
        outbound_cargo_cutoff=outbound_cargo_cutoff,
        current_plan_slack=current_plan_slack,
        no_itt_slack=no_itt_slack,
    )
    avoidable = (
        not same_terminal
        and current_plan_slack < timedelta(0)
        and no_itt_slack >= timedelta(0)
    )
    return ConnectionRiskAssessment(
        **common,
        status=AssessmentStatus.AVAILABLE,
        severity=_assessment_severity(current_plan_slack, config.warning_margin),
        slack=breakdown,
        avoidable_by_terminal_prevention=avoidable,
        reason_codes=_assessment_reason_codes(
            inbound, outbound, same_terminal=same_terminal
        ),
    )


def _assessment_confidence(
    assessment: ConnectionRiskAssessment,
) -> WatcherConfidence:
    if assessment.inbound_prediction is None or assessment.outbound_prediction is None:
        return WatcherConfidence.LOW
    return min(
        (
            _confidence(assessment.inbound_prediction),
            _confidence(assessment.outbound_prediction),
        ),
        key=lambda item: {
            WatcherConfidence.LOW: 0,
            WatcherConfidence.MEDIUM: 1,
            WatcherConfidence.HIGH: 2,
        }[item],
    )


def risk_event_from_assessment(
    assessment: ConnectionRiskAssessment,
) -> RiskEvent | None:
    """Adapt an actionable-shaped assessment without inventing timing or volume."""

    if (
        assessment.status is AssessmentStatus.UNAVAILABLE
        or assessment.box_count is None
    ):
        return None
    if (
        assessment.severity is None
        or assessment.slack is None
        or assessment.inbound_prediction is None
        or assessment.outbound_prediction is None
    ):
        raise ValueError("AVAILABLE assessment is missing causal risk fields")
    inbound = assessment.inbound_prediction
    outbound = assessment.outbound_prediction
    if (
        inbound.reference_arrival is None
        or inbound.predicted_arrival is None
        or outbound.reference_arrival is None
        or outbound.predicted_arrival is None
    ):
        raise ValueError("AVAILABLE assessment contains an incomplete prediction")

    return RiskEvent(
        connection_id=assessment.ucid,
        state=assessment.severity,
        current_plan_slack_hours=assessment.slack.current_plan_slack_h,
        no_itt_slack_hours=assessment.slack.no_itt_slack_h,
        avoidable_by_terminal_prevention=(
            assessment.avoidable_by_terminal_prevention
        ),
        affected_boxes=assessment.box_count,
        watcher_confidence=_assessment_confidence(assessment),
        reason_codes=assessment.reason_codes,
        detected_at=assessment.assessed_at,
        ucid=assessment.ucid,
        assumptions=Assumptions(
            connection_type=ConnectionType.from_crossing(
                assessment.origin.terminal != assessment.destination.terminal
            ),
            transfer_scenario=(
                "synthetic PR #3 "
                f"{assessment.process_scenario.value} process scenario "
                f"({assessment.transfer_mode.value}; experimental assumptions, "
                "not a PSA operating rule)"
            ),
        ),
        inbound_terminal=assessment.origin.terminal,
        outbound_terminal=assessment.destination.terminal,
        terminal_resolution=TerminalResolution.SIMULATED,
        inbound_vessel=assessment.assignment.inbound_vessel_id,
        outbound_vessel=assessment.assignment.outbound_vessel_id,
        source="real_ais_causal_predictions+synthetic_pr3_connection",
        inbound_reference_arrival=inbound.reference_arrival,
        inbound_predicted_arrival=inbound.predicted_arrival,
        outbound_reference_arrival=outbound.reference_arrival,
        outbound_predicted_arrival=outbound.predicted_arrival,
    )
