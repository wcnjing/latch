"""Tool layer tests, including a full replay of the §7.1 baseline scenario."""

import pytest

from latch.confidence import score
from latch.config import CONFIDENCE_ESCALATION_THRESHOLD
from latch.models import SourceKind, Terminal, ToolOutcome
from latch.tools import (
    CacheEntry,
    NoFailures,
    ScriptedFailures,
    SeededFailures,
    ToolStatus,
    build_itt_inventory,
    call,
    connection_density_score,
    query_itt_slot,
    query_outbound_services,
    send_options_to_line,
)
from latch.tools.stubs import TransferMode
from tests.conftest import T0


def test_successful_call_is_live_and_verified():
    result = call("query_itt_slot", lambda: ["slot"], NoFailures())
    assert result.status is ToolStatus.OK
    assert result.source is SourceKind.LIVE_API
    assert result.attempts == 1
    assert result.provenance("itt_capacity").verified


def test_retry_then_success_is_recorded_as_retried():
    plan = ScriptedFailures({"query_itt_slot": [ToolStatus.TIMEOUT]})
    result = call("query_itt_slot", lambda: ["slot"], plan, max_retries=1)

    assert result.status is ToolStatus.OK
    assert result.attempts == 2
    assert result.tool_outcome is ToolOutcome.RETRIED


def test_baseline_scenario_falls_back_to_cache_and_drops_confidence():
    """§7.1, end to end.

    T+45s  query_itt_slot times out. Retry with backoff, times out again.
    T+55s  Falls back to cached inventory.
    T+60s  Provenance drops confidence below the gate threshold.

    Nobody decides to lower the confidence. It falls out of what the tools did.
    """
    plan = ScriptedFailures(
        {"query_itt_slot": [ToolStatus.TIMEOUT, ToolStatus.TIMEOUT]}
    )
    cached = CacheEntry(value=["stale_slot"], age_min=8.0)

    result = call(
        "query_itt_slot",
        lambda: pytest.fail("live call must not succeed in this scenario"),
        plan,
        max_retries=1,
        cache=cached,
    )

    assert result.status is ToolStatus.CACHED_FALLBACK
    assert result.source is SourceKind.CACHE
    assert result.age_min == 8.0
    assert result.attempts == 2
    assert result.error_class == "timeout"
    assert result.value == ["stale_slot"]

    provenance = (result.provenance("itt_capacity", verified=False),)
    assert score(provenance).confidence < CONFIDENCE_ESCALATION_THRESHOLD


def test_exhausted_retries_with_no_cache_is_an_assumed_default():
    plan = ScriptedFailures({"book_itt_slot": [ToolStatus.ERROR, ToolStatus.ERROR]})
    result = call("book_itt_slot", lambda: "ok", plan, max_retries=1)

    assert not result.ok
    assert result.source is SourceKind.ASSUMED_DEFAULT
    assert result.tool_outcome is ToolOutcome.FAILED
    assert result.value is None


def test_timeouts_cost_more_wall_clock_than_hard_errors():
    """The demo timeline depends on this: a timeout is a visible pause."""
    timeout = call(
        "query_itt_slot",
        lambda: "x",
        ScriptedFailures({"query_itt_slot": [ToolStatus.TIMEOUT]}),
    )
    error = call(
        "query_itt_slot",
        lambda: "x",
        ScriptedFailures({"query_itt_slot": [ToolStatus.ERROR]}),
    )
    assert timeout.latency_ms > error.latency_ms


def test_scripted_failures_replay_identically():
    """The recorded video must be reproducible frame for frame."""

    def run() -> list[ToolStatus]:
        plan = ScriptedFailures(
            {"query_itt_slot": [ToolStatus.TIMEOUT, ToolStatus.TIMEOUT]}
        )
        return [
            call("query_itt_slot", lambda: "x", plan, max_retries=2).status
            for _ in range(1)
        ]

    assert run() == run()


def test_seeded_failures_are_reproducible_across_instances():
    """A scenario suite whose failures move between runs cannot be reported as
    an accuracy figure."""
    first = [SeededFailures(seed=7).next_outcome("t") for _ in range(50)]
    second = [SeededFailures(seed=7).next_outcome("t") for _ in range(50)]
    assert first == second
    assert SeededFailures(seed=8).next_outcome("t") is not None


# --- stub surface -----------------------------------------------------------


def test_itt_inventory_offers_a_real_time_versus_emissions_tradeoff():
    """Rung 3 picks a mode. If road and barge scored the same the choice would
    be theatre."""
    slots = build_itt_inventory(T0, Terminal.TUAS, Terminal.PASIR_PANJANG)
    road = [s for s in slots if s.mode is TransferMode.ROAD]
    barge = [s for s in slots if s.mode is TransferMode.BARGE]

    assert road and barge
    assert road[0].emissions_kg_co2e > barge[0].emissions_kg_co2e
    assert road[0].cost_sgd > barge[0].cost_sgd


def test_itt_inventory_is_deterministic():
    a = build_itt_inventory(T0, Terminal.TUAS, Terminal.BRANI)
    b = build_itt_inventory(T0, Terminal.TUAS, Terminal.BRANI)
    assert [s.slot_id for s in a] == [s.slot_id for s in b]


def test_query_itt_slot_filters_on_capacity():
    big = query_itt_slot(T0, Terminal.TUAS, Terminal.PASIR_PANJANG, boxes=200)
    small = query_itt_slot(T0, Terminal.TUAS, Terminal.PASIR_PANJANG, boxes=10)
    assert len(big) < len(small)
    assert all(s.capacity_teu >= 200 for s in big)


def test_slot_resource_key_is_what_the_lock_table_arbitrates_on():
    slot = build_itt_inventory(T0, Terminal.TUAS, Terminal.BRANI)[0]
    assert slot.resource_key.startswith("itt_slot:")
    assert slot.slot_id in slot.resource_key


def test_outbound_services_decay_in_availability():
    """Options alive decays with time — which is why the agent should sometimes
    escalate to the customer before finishing internal evaluation."""
    services = query_outbound_services(T0, Terminal.PASIR_PANJANG)
    departures = [s.departs_at for s in services]
    assert departures == sorted(departures)
    assert services[0].capacity_available > services[-1].capacity_available


def test_density_score_is_advisory_only():
    """Rung 1 outputs a number for the planner. It does not decide anything."""
    result = connection_density_score("B7-TUAS-0400", 180, 20)
    assert result["density_score"] == pytest.approx(0.90)
    assert result["advisory"] is True


def test_write_tools_declare_that_they_are_stubbed():
    """Honesty about the action side, enforced by a test rather than a promise."""
    offer = send_options_to_line("SYNTHETIC LINE", "UCID-SGSIN-0001", ["p1", "p2"], 180)
    assert offer["stubbed"] is True
    assert offer["options_sent"] == 2
