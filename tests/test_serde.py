"""Wire-format tests. These are what make the A to B contract real."""

import json

import pytest

from latch.models import Terminal, TerminalResolution
from latch.serde import WIRE_VERSION, risk_from_dict, risk_to_dict
from tests.conftest import make_risk


def test_round_trip_preserves_everything():
    original = make_risk(
        boxes=41,
        slack_total_min=640,
        slack_remaining_min=95,
        inbound_terminal=Terminal.TUAS,
        outbound_terminal=Terminal.BRANI,
        resolution=TerminalResolution.INFERRED,
    )
    restored = risk_from_dict(risk_to_dict(original))
    assert restored == original


def test_round_trip_survives_json():
    """The handoff is a file or an HTTP body, not a Python object."""
    original = make_risk()
    restored = risk_from_dict(json.loads(json.dumps(risk_to_dict(original))))
    assert restored == original


def test_derived_values_are_published_for_the_console():
    """C renders these and should not have to reimplement the arithmetic."""
    risk = make_risk(boxes=60, slack_remaining_min=60)
    derived = risk_to_dict(risk)["derived"]

    assert derived["priority"] == pytest.approx(60.0)
    assert derived["crosses_terminals"] is True
    assert "slack_consumed_pct" in derived


def test_derived_values_are_recomputed_not_trusted():
    """A bug in A's arithmetic must not silently become a bug in B's priority
    ordering — that is the one number the Lock Table arbitrates on."""
    payload = risk_to_dict(make_risk(boxes=60, slack_remaining_min=60))
    payload["derived"]["priority"] = 99_999.0

    assert risk_from_dict(payload).priority == pytest.approx(60.0)


def test_terminal_resolution_survives_the_wire():
    """If this were dropped in transit, the honesty claim would be lost exactly
    where it matters — between the workstream that knows and the one that renders."""
    for resolution in TerminalResolution:
        risk = make_risk(resolution=resolution)
        restored = risk_from_dict(risk_to_dict(risk))
        assert restored.inbound.terminal_resolution is resolution


def test_version_mismatch_fails_loudly():
    payload = risk_to_dict(make_risk())
    payload["wire_version"] = WIRE_VERSION + 1
    with pytest.raises(ValueError, match="wire_version"):
        risk_from_dict(payload)


def test_optional_fields_default_rather_than_crash():
    payload = risk_to_dict(make_risk())
    del payload["data_age_min"]
    assert risk_from_dict(payload).data_age_min == 0.0
