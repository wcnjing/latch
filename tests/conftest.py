"""Shared fixtures. Every timestamp here is fixed so tests never depend on now()."""

from datetime import UTC, datetime, timedelta

import pytest

from latch.models import (
    ConnectionRisk,
    Terminal,
    TerminalResolution,
    VesselCall,
)

T0 = datetime(2026, 8, 30, 4, 17, tzinfo=UTC)


def make_risk(
    risk_id: str = "cr_0001",
    boxes: int = 34,
    slack_total_min: float = 720.0,
    slack_remaining_min: float = 110.0,
    eta_slip_min: float = 361.0,
    inbound_terminal: Terminal = Terminal.TUAS,
    outbound_terminal: Terminal = Terminal.PASIR_PANJANG,
    resolution: TerminalResolution = TerminalResolution.TERMINAL,
) -> ConnectionRisk:
    inbound = VesselCall(
        vessel_name="SYNTHETIC MAERSK",
        service_code="AE7",
        terminal=inbound_terminal,
        terminal_resolution=resolution,
        scheduled=T0,
        estimated=T0 + timedelta(minutes=eta_slip_min),
    )
    outbound = VesselCall(
        vessel_name="SYNTHETIC FEEDER",
        service_code="SEA3",
        terminal=outbound_terminal,
        terminal_resolution=resolution,
        scheduled=T0 + timedelta(minutes=slack_total_min),
        estimated=T0 + timedelta(minutes=slack_total_min),
    )
    return ConnectionRisk(
        risk_id=risk_id,
        ucid=f"UCID-SGSIN-{risk_id[-4:]}",
        detected_at=T0,
        inbound=inbound,
        outbound=outbound,
        boxes_at_risk=boxes,
        slack_total_min=slack_total_min,
        slack_remaining_min=slack_remaining_min,
        source="oceans_x.vessel_movements",
        data_age_min=2.0,
    )


@pytest.fixture
def risk() -> ConnectionRisk:
    return make_risk()


class FrozenClock:
    """A clock the tests advance by hand, so expiry is testable without sleeping."""

    def __init__(self, start: datetime = T0) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock()
