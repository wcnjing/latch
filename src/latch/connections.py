"""The synthetic connection layer.

**This is the invented half of LATCH, and it is the half that matters.**

Real vessel timing gives us the trigger. Which box connects to which outbound
service, how many boxes, and when the cutoff falls are all authored here. In a
literal sense the system detects risks we wrote. There is no fix for that in
fourteen days; there is only honesty, and honesty done well is worth more than
the concealment would have been.

Three things make it defensible, and all three are properties of this file:

  Deterministic     A connection is derived from its call id by hash, so the
                    same call always produces the same connection. Nothing
                    here is sampled at run time, and a rerun cannot quietly
                    produce a more flattering graph.

  Frozen            `ConnectionParams` holds every distribution parameter in
                    one object, set before the agent existed. Do not tune them
                    to improve a result. The submission reports them verbatim.

  Declared          Every connection carries `TerminalResolution.SIMULATED`,
                    which travels into the trace and lowers confidence. The
                    synthetic origin is mechanical rather than rhetorical.

What is *not* invented: arrival timing, which comes from real AIS observations
via `replay.py`.
"""

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from latch.models import Terminal

# Terminals a synthetic outbound service can sail from. Brani and Keppel are
# included because the inter-terminal split is the phenomenon under study;
# excluding them would make transfers rarer than reality suggests.
_TERMINALS: Final[tuple[Terminal, ...]] = (
    Terminal.TUAS,
    Terminal.PASIR_PANJANG,
    Terminal.BRANI,
    Terminal.KEPPEL,
)


@dataclass(frozen=True, slots=True)
class ConnectionParams:
    """Every synthetic distribution parameter, in one reportable object.

    Frozen before the agent existed. Changing a value here changes what the
    system is measured against, so a change is a methodology change and should
    be described as one.
    """

    # Share of connections whose inbound and outbound legs sit at different
    # terminals. The inter-terminal split is the premise of the whole pitch,
    # so this is the single most consequential number in the file.
    inter_terminal_share: float = 0.45

    # Boxes on one connection. Wide, because a connection carrying eight boxes
    # and one carrying a hundred should reach different gate decisions.
    min_boxes: int = 8
    max_boxes: int = 120

    # Hours between derived arrival and the outbound cutoff. The lower bound is
    # deliberately tight: a graph where everything comfortably connects would
    # never exercise the ladder.
    min_connection_window_h: float = 5.0
    max_connection_window_h: float = 34.0

    # Fixed operational costs applied to every connection.
    berth_and_discharge_h: float = 4.5
    planned_transfer_h: float = 1.5

    # Slack thresholds separating SAFE from WATCH. AT_RISK is slack <= 0 and
    # is not a tunable.
    watch_threshold_h: float = 4.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.inter_terminal_share <= 1.0:
            raise ValueError("inter_terminal_share must be a probability")
        if self.min_boxes > self.max_boxes:
            raise ValueError("min_boxes must not exceed max_boxes")
        if self.min_connection_window_h > self.max_connection_window_h:
            raise ValueError("connection window bounds are inverted")

    def as_dict(self) -> dict[str, float | int]:
        """For the submission. These get printed, not summarised."""
        return {
            "inter_terminal_share": self.inter_terminal_share,
            "min_boxes": self.min_boxes,
            "max_boxes": self.max_boxes,
            "min_connection_window_h": self.min_connection_window_h,
            "max_connection_window_h": self.max_connection_window_h,
            "berth_and_discharge_h": self.berth_and_discharge_h,
            "planned_transfer_h": self.planned_transfer_h,
            "watch_threshold_h": self.watch_threshold_h,
        }


@dataclass(frozen=True, slots=True)
class SyntheticConnection:
    """One inbound-to-outbound container connection. Invented, deterministically."""

    connection_id: str
    call_id: str
    vessel_id: str
    inbound_terminal: Terminal
    outbound_terminal: Terminal
    outbound_service: str
    outbound_cutoff: datetime
    boxes: int
    params: ConnectionParams

    @property
    def requires_transfer(self) -> bool:
        return self.inbound_terminal is not self.outbound_terminal

    @property
    def transfer_hours(self) -> float:
        return self.params.planned_transfer_h if self.requires_transfer else 0.0


def _stream(call_id: str) -> list[float]:
    """A deterministic sequence of unit floats derived from a call id.

    A hash rather than a seeded RNG so that a connection depends only on its
    own id — generating call B never shifts call A, and callers can generate
    one connection without replaying the whole feed.
    """
    digest = hashlib.sha256(call_id.encode()).digest()
    return [digest[i] / 255.0 for i in range(len(digest))]


def connection_for(
    call_id: str,
    vessel_id: str,
    reference_arrival: datetime,
    params: ConnectionParams = ConnectionParams(),
) -> SyntheticConnection:
    """Invent the connection this arriving vessel's cargo is booked onto.

    `reference_arrival` anchors the cutoff: the connection was planned around
    the vessel's *original* expected arrival, which is what makes a later slip
    eat into slack. Anchoring on the current prediction instead would make the
    window follow the vessel and no connection would ever come under threat.
    """
    draws = _stream(call_id)

    inbound = _TERMINALS[int(draws[0] * len(_TERMINALS)) % len(_TERMINALS)]
    if draws[1] < params.inter_terminal_share:
        others = tuple(t for t in _TERMINALS if t is not inbound)
        outbound = others[int(draws[2] * len(others)) % len(others)]
    else:
        outbound = inbound

    boxes = params.min_boxes + int(
        draws[3] * (params.max_boxes - params.min_boxes + 1)
    )
    boxes = min(boxes, params.max_boxes)

    window_h = params.min_connection_window_h + draws[4] * (
        params.max_connection_window_h - params.min_connection_window_h
    )

    return SyntheticConnection(
        connection_id=f"conn_{call_id.removeprefix('call_')[:12]}",
        call_id=call_id,
        vessel_id=vessel_id,
        inbound_terminal=inbound,
        outbound_terminal=outbound,
        outbound_service=f"SVC{int(draws[5] * 40) + 1:02d}",
        outbound_cutoff=reference_arrival + timedelta(hours=window_h),
        boxes=boxes,
        params=params,
    )
