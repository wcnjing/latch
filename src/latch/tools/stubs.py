"""The tool surface. Every one of these terminates in a stub.

We have no write access to any terminal system and are not implying otherwise.
The interfaces are modelled on the message semantics named beside each tool;
the contribution is the decision layer above them, and the execution layer is
deliberately out of scope. Say this on the slide, not in the appendix.

The inventory below is the synthetic layer, gathered in one visible object
rather than scattered through the functions, so its parameters can be frozen
before evaluation and reported as-is.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from latch.models import Terminal


class TransferMode(StrEnum):
    """Road is fast and dirty; barge is slow and clean. Rung 3 picks."""

    ROAD = "road"
    BARGE = "barge"


@dataclass(frozen=True, slots=True)
class ITTSlot:
    """An inter-terminal transfer slot. Synthetic."""

    slot_id: str
    from_terminal: Terminal
    to_terminal: Terminal
    departs_at: datetime
    capacity_teu: int
    mode: TransferMode
    cost_sgd: float
    emissions_kg_co2e: float

    @property
    def resource_key(self) -> str:
        """The key the Lock Table arbitrates on."""
        return f"itt_slot:{self.slot_id}"


@dataclass(frozen=True, slots=True)
class OutboundService:
    """An alternative outbound service a rolled box could be offered."""

    service_code: str
    vessel_name: str
    terminal: Terminal
    departs_at: datetime
    transit_days: int
    capacity_available: int


# --- synthetic inventory ----------------------------------------------------
# Frozen before the agent existed. Do not tune these to flatter a demo.

_ITT_COST_PER_BOX: dict[TransferMode, float] = {
    TransferMode.ROAD: 48.0,
    TransferMode.BARGE: 31.0,
}
_ITT_EMISSIONS_PER_BOX: dict[TransferMode, float] = {
    TransferMode.ROAD: 12.4,
    TransferMode.BARGE: 4.1,
}
_ITT_TRANSIT_MIN: dict[TransferMode, int] = {
    TransferMode.ROAD: 55,
    TransferMode.BARGE: 190,
}


def itt_transit_minutes(mode: TransferMode) -> int:
    return _ITT_TRANSIT_MIN[mode]


def build_itt_inventory(
    origin: datetime,
    from_terminal: Terminal,
    to_terminal: Terminal,
    count: int = 4,
) -> list[ITTSlot]:
    """Deterministic slot inventory for a terminal pair.

    Alternating modes and widening departure gaps, so a plan that needs speed
    and a plan that needs low emissions genuinely diverge.
    """
    slots: list[ITTSlot] = []
    for i in range(count):
        mode = TransferMode.ROAD if i % 2 == 0 else TransferMode.BARGE
        departs = origin + timedelta(minutes=40 * (i + 1))
        capacity = 250 if mode is TransferMode.BARGE else 120
        slots.append(
            ITTSlot(
                slot_id=f"{from_terminal.value[:3]}{to_terminal.value[:3]}_{1100 + i * 20}",
                from_terminal=from_terminal,
                to_terminal=to_terminal,
                departs_at=departs,
                capacity_teu=capacity,
                mode=mode,
                cost_sgd=_ITT_COST_PER_BOX[mode],
                emissions_kg_co2e=_ITT_EMISSIONS_PER_BOX[mode],
            )
        )
    return slots


# --- tool implementations ---------------------------------------------------


def query_itt_slot(
    origin: datetime,
    from_terminal: Terminal,
    to_terminal: Terminal,
    boxes: int,
) -> list[ITTSlot]:
    """Available inter-terminal slots for a move. Read-only.

    Stub. A real integration would query the ITT booking system; no public
    dataset of Singapore ITT capacity exists, and inventing one and calling it
    real would be the single fastest way to lose a judge who works here.
    """
    return [
        slot
        for slot in build_itt_inventory(origin, from_terminal, to_terminal)
        if slot.capacity_teu >= boxes
    ]


def book_itt_slot(slot: ITTSlot, boxes: int, ucid: str) -> dict[str, object]:
    """Reserve capacity on a slot. Write.

    Stub, shaped after an IFTMBF booking request. Returns an acknowledgement
    with the fields a real booking would echo back.
    """
    return {
        "booking_ref": f"BK-{slot.slot_id}-{ucid[-6:]}",
        "slot_id": slot.slot_id,
        "boxes": boxes,
        "mode": slot.mode.value,
        "departs_at": slot.departs_at.isoformat(),
        "cost_sgd": round(slot.cost_sgd * boxes, 2),
        "emissions_kg_co2e": round(slot.emissions_kg_co2e * boxes, 2),
        "stubbed": True,
    }


def query_outbound_services(
    after: datetime, terminal: Terminal, count: int = 3
) -> list[OutboundService]:
    """Alternative outbound services still callable. Read-only.

    Drives `options_alive` — how many viable services still existed when the
    line was asked. Detect early and it is a choice; detect late and it is a
    notification.
    """
    return [
        OutboundService(
            service_code=f"SVC{i + 1}",
            vessel_name=f"SYNTHETIC CARRIER {i + 1}",
            terminal=terminal,
            departs_at=after + timedelta(hours=8 * (i + 1)),
            transit_days=14 + i * 3,
            capacity_available=120 - i * 35,
        )
        for i in range(count)
    ]


def connection_density_score(
    berth_assignment: str, connections_served: int, connections_stranded: int
) -> dict[str, object]:
    """Rung 1: the consequence of one candidate berth assignment. Advisory only.

    Planners already weigh connections when assigning berths; this does not
    discover that. What it does is compute the full connection-density
    consequence across thousands of concurrent boxes and keep it current as
    ETAs move. The planner still decides.
    """
    total = connections_served + connections_stranded
    return {
        "berth_assignment": berth_assignment,
        "connections_served": connections_served,
        "connections_stranded": connections_stranded,
        "density_score": round(connections_served / total, 4) if total else 0.0,
        "advisory": True,
    }


def send_options_to_line(
    line: str, ucid: str, option_ids: list[str], window_min: int
) -> dict[str, object]:
    """Rung 4: put ranked options to the shipping line. Write.

    Stub. PSA cannot re-route cargo; the line can. Designed on the principle
    that the line owns the final connection decision — a principle we have
    taken from PSA and have not yet validated with a liner-side contact, which
    is stated as such rather than asserted as observed behaviour.
    """
    return {
        "offer_ref": f"OF-{ucid[-6:]}-{len(option_ids)}",
        "line": line,
        "options_sent": len(option_ids),
        "option_ids": list(option_ids),
        "window_min": window_min,
        "stubbed": True,
    }
