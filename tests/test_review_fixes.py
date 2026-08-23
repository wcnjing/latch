"""Regressions for the day-6 review findings.

Each test here corresponds to a defect that reached main. They are grouped in
one file deliberately: the common thread is that all of them were reachable
through a path no test exercised, and keeping them together makes the shape of
that gap visible rather than scattering it across seven files.
"""

import json
import subprocess
import sys

from latch.console import case_view
from latch.events import ConnectionType, RiskEvent
from latch.models import OUTCOMES, Resolution
from latch.trace import TraceStore

BASE = {
    "connection_id": "X-1",
    "state": "AT_RISK",
    "current_plan_slack_hours": -1.0,
    "no_itt_slack_hours": 1.0,
    "affected_boxes": 10,
    "confidence": "HIGH",
    "reason_codes": [],
}


def event(**extra) -> RiskEvent:
    return RiskEvent.from_dict(BASE | extra)


# --- provenance -------------------------------------------------------------


def test_real_terminals_are_not_reported_as_synthetic():
    """The trace said `terminal_resolution: berth` and `terminals_synthetic:
    True` on the same connection. Both cannot be true, and the trace is
    append-only, so nothing downstream can correct it afterwards."""
    a = event(
        avoidable_by_terminal_prevention=True,
        inbound_terminal="tuas",
        outbound_terminal="pasir_panjang",
        terminal_resolution="berth",
        ucid="UCID-REAL-1",
    ).assumptions
    assert a.terminals_synthetic is False
    assert a.ucid_synthetic is False


def test_unstated_provenance_defaults_to_synthetic():
    """The claim that cannot mislead. An event that says nothing about where
    its values came from must not be recorded as though they were observed."""
    a = event(avoidable_by_terminal_prevention=True).assumptions
    assert a.ucid_synthetic
    assert a.pairing_synthetic
    assert a.terminals_synthetic
    assert a.boxes_synthetic


def test_connection_type_is_derived_not_defaulted():
    """`from_dict` left this at SAME_TERMINAL for every event on the wire,
    which is what #7 was."""
    assert (
        event(
            inbound_terminal="tuas",
            outbound_terminal="pasir_panjang",
            avoidable_by_terminal_prevention=True,
        ).assumptions.connection_type
        is ConnectionType.INTER_TERMINAL
    )
    assert (
        event(
            inbound_terminal="tuas",
            outbound_terminal="tuas",
            avoidable_by_terminal_prevention=False,
        ).assumptions.connection_type
        is ConnectionType.SAME_TERMINAL
    )


def test_contradictory_input_resolves_toward_the_transfer():
    """Identical terminals and a prevention flag disagree. Believing the
    terminals would drop the prevention rung entirely; believing the flag
    costs one advisory nobody needed. The asymmetry is the point."""
    a = event(
        inbound_terminal="tuas",
        outbound_terminal="tuas",
        avoidable_by_terminal_prevention=True,
    ).assumptions
    assert a.connection_type is ConnectionType.INTER_TERMINAL


def test_empty_transfer_scenario_is_not_silently_replaced():
    """A falsy check turned a producer bug into the default label, so the
    trace claimed a reference scenario the producer never sent."""
    a = event(
        avoidable_by_terminal_prevention=False, transfer_scenario=""
    ).assumptions
    assert a.transfer_scenario == ""


def test_watcher_and_wire_agree_on_connection_type():
    """The mapping was written twice, two different ways, and #7 was one of
    them being wrong."""
    assert ConnectionType.from_crossing(True) is ConnectionType.INTER_TERMINAL
    assert ConnectionType.from_crossing(False) is ConnectionType.SAME_TERMINAL


# --- outcome classification -------------------------------------------------


def test_every_resolution_is_classified():
    """Two hand-maintained tuples meant a new member defaulted to `internal
    failure` in silence — the exact misattribution the split existed to fix."""
    assert set(OUTCOMES) == set(Resolution)


def test_a_crash_is_not_counted_as_an_internal_decline():
    """`FAILED` means the code broke. Folding it in with a deliberate decline
    reports an infrastructure fault as a business decision."""
    assert Resolution.FAILED.is_agent_fault
    assert not Resolution.INTERNALLY_DECLINED.is_agent_fault
    assert not Resolution.APPROVAL_LAPSED.is_agent_fault


# --- reporting --------------------------------------------------------------


def test_case_view_tells_the_console_whose_failure_it_was(risk):
    """An internal decline and a lapsed customer window both arrive as
    `service_success: False`. Without this the screen has to guess."""
    store = TraceStore()
    trace = store.open(risk)
    trace.close(Resolution.INTERNALLY_DECLINED)

    view = case_view(trace)
    assert view["service_success"] is False
    assert view["reached_the_line"] is False
    assert view["agent_fault"] is False


def test_cli_survives_a_run_where_nothing_is_at_risk(tmp_path):
    """Every connection triaged clean is an ordinary outcome. It used to end
    the run in a TypeError from a format string, after all the work was done."""
    events = tmp_path / "safe.json"
    events.write_text(
        json.dumps(
            [
                BASE
                | {
                    "connection_id": "SAFE-1",
                    "current_plan_slack_hours": 9.0,
                    "no_itt_slack_hours": 11.0,
                    "affected_boxes": 4,
                    "avoidable_by_terminal_prevention": False,
                }
            ]
        )
    )
    result = subprocess.run(
        [sys.executable, "-m", "latch.cli", "--events", str(events), "--model", "fake"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "no service rate" in result.stdout
