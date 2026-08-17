"""Wire format for the A to B handoff.

The Watcher runs in workstream A and the agent core runs here. Between them
sits JSON, so the contract needs an encoder and a decoder that are provably
inverses — otherwise "A emits ConnectionRisk" is a nominal agreement that
discovers its disagreements on day 10.

`risk_to_dict` and `risk_from_dict` round-trip. There is a test.
"""

from datetime import datetime
from typing import Any

from latch.models import (
    ConnectionRisk,
    Terminal,
    TerminalResolution,
    VesselCall,
)

WIRE_VERSION = 1


def _dt(value: datetime) -> str:
    return value.isoformat()


def vessel_call_to_dict(call: VesselCall) -> dict[str, Any]:
    return {
        "vessel_name": call.vessel_name,
        "imo": call.imo,
        "service_code": call.service_code,
        "terminal": call.terminal.value,
        "terminal_resolution": call.terminal_resolution.value,
        "berth": call.berth,
        "scheduled": _dt(call.scheduled),
        "estimated": _dt(call.estimated),
    }


def vessel_call_from_dict(payload: dict[str, Any]) -> VesselCall:
    return VesselCall(
        vessel_name=payload["vessel_name"],
        service_code=payload["service_code"],
        terminal=Terminal(payload["terminal"]),
        terminal_resolution=TerminalResolution(payload["terminal_resolution"]),
        scheduled=datetime.fromisoformat(payload["scheduled"]),
        estimated=datetime.fromisoformat(payload["estimated"]),
        imo=payload.get("imo"),
        berth=payload.get("berth"),
    )


def risk_to_dict(risk: ConnectionRisk) -> dict[str, Any]:
    """Encode a risk for the wire.

    Derived values (slack consumed, priority, whether it crosses terminals)
    are included even though they are recomputable. The console renders them
    and should not have to reimplement the arithmetic to do it.
    """
    return {
        "wire_version": WIRE_VERSION,
        "risk_id": risk.risk_id,
        "ucid": risk.ucid,
        "detected_at": _dt(risk.detected_at),
        "inbound": vessel_call_to_dict(risk.inbound),
        "outbound": vessel_call_to_dict(risk.outbound),
        "boxes_at_risk": risk.boxes_at_risk,
        "slack_total_min": risk.slack_total_min,
        "slack_remaining_min": risk.slack_remaining_min,
        "source": risk.source,
        "data_age_min": risk.data_age_min,
        "derived": {
            "eta_deviation_min": round(risk.eta_deviation_min, 1),
            "slack_consumed_pct": round(risk.slack_consumed_pct, 4),
            "priority": round(risk.priority, 2),
            "crosses_terminals": risk.crosses_terminals,
        },
    }


def risk_from_dict(payload: dict[str, Any]) -> ConnectionRisk:
    """Decode a risk from the wire. `derived` is ignored — it is recomputed.

    Trusting a sender's arithmetic would let a bug in A silently become a bug
    in B's priority ordering, which is the one number the Lock Table arbitrates
    on.
    """
    version = payload.get("wire_version", WIRE_VERSION)
    if version != WIRE_VERSION:
        raise ValueError(
            f"wire_version {version} does not match {WIRE_VERSION}; "
            "regenerate the producer rather than guessing at the difference"
        )
    return ConnectionRisk(
        risk_id=payload["risk_id"],
        ucid=payload["ucid"],
        detected_at=datetime.fromisoformat(payload["detected_at"]),
        inbound=vessel_call_from_dict(payload["inbound"]),
        outbound=vessel_call_from_dict(payload["outbound"]),
        boxes_at_risk=payload["boxes_at_risk"],
        slack_total_min=payload["slack_total_min"],
        slack_remaining_min=payload["slack_remaining_min"],
        source=payload["source"],
        data_age_min=payload.get("data_age_min", 0.0),
    )
