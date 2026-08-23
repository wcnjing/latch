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
from datetime import datetime
from typing import Protocol, runtime_checkable

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
