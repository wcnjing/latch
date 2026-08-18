"""Deliberation tests. The guard against invented options is the important one."""

import pytest

from latch.deliberation import deliberate
from latch.events import RiskEvent
from latch.llm import FakeModel
from latch.models import Rung
from latch.tools import CacheEntry, ScriptedFailures, ToolStatus

AVOIDABLE = {
    "connection_id": "D-1",
    "state": "AT_RISK",
    "current_plan_slack_hours": -1.8,
    "no_itt_slack_hours": 2.4,
    "avoidable_by_terminal_prevention": True,
    "affected_boxes": 84,
    "confidence": "MEDIUM",
    "reason_codes": ["INTER_TERMINAL_TRANSFER_TIME"],
}
HOPELESS = AVOIDABLE | {
    "connection_id": "D-3",
    "no_itt_slack_hours": -0.9,
    "avoidable_by_terminal_prevention": False,
}


def run(payload: dict, chosen: str = "", **kwargs):
    event = RiskEvent.from_dict(payload)
    client = FakeModel(
        {
            "deliberation": {
                "chosen_plan_id": chosen,
                "ranking": [],
                "rationale": "scripted",
            }
        }
    )
    return event, deliberate(event.to_connection_risk(), event, client, **kwargs)


def test_avoidable_case_offers_prevention_move_and_offer():
    _, result = run(AVOIDABLE)
    rungs = {p.rung for p in result.plans}
    assert rungs == {Rung.INFORM, Rung.MOVE, Rung.OFFER}


def test_only_modes_that_arrive_in_time_are_offered():
    """Barge transit is 190 minutes against 144 minutes of slack. Cheaper and
    cleaner does not help if it arrives after the cutoff."""
    _, result = run(AVOIDABLE)
    moves = [p for p in result.plans if p.rung is Rung.MOVE]
    assert moves
    assert all("road" in a.detail for p in moves for a in p.actions)


def test_hopeless_case_falls_to_rung_four_only():
    """AT_RISK and not avoidable under the available options."""
    _, result = run(HOPELESS)
    assert [p.rung for p in result.plans] == [Rung.OFFER]


def test_prevention_is_not_offered_when_it_would_not_help():
    """Offered anyway, Rung 1 becomes noise the planner learns to ignore."""
    _, result = run(HOPELESS)
    assert Rung.INFORM not in {p.rung for p in result.plans}


def test_model_cannot_invent_an_option():
    """The whole reason code enumerates and the model only ranks. A chosen id
    that is not a candidate is rejected rather than executed."""
    _, result = run(AVOIDABLE, chosen="D-1-r3-a-slot-that-does-not-exist")

    assert result.rejected_choice == "D-1-r3-a-slot-that-does-not-exist"
    assert result.chosen is not None
    assert result.chosen.plan_id in {p.plan_id for p in result.plans}


def test_a_valid_choice_is_honoured():
    event, first = run(AVOIDABLE)
    target = first.plans[1].plan_id
    _, result = run(AVOIDABLE, chosen=target)

    assert result.rejected_choice is None
    assert result.chosen.plan_id == target


def test_chosen_plan_carries_the_models_rationale():
    _, result = run(AVOIDABLE, chosen="")
    assert result.chosen.rationale == "scripted"


def test_cache_fallback_lowers_confidence_without_anyone_deciding_to():
    clean = run(AVOIDABLE)[1]
    degraded = run(
        AVOIDABLE,
        failures=ScriptedFailures(
            {"query_itt_slot": [ToolStatus.TIMEOUT, ToolStatus.TIMEOUT]}
        ),
        itt_cache=CacheEntry(value=[], age_min=8.0),
    )[1]

    assert degraded.chosen.confidence < clean.chosen.confidence


def test_no_options_at_all_is_reported_not_crashed():
    """Both tools fail and there is no cache. The agent has nothing to offer and
    has to say so."""
    _, result = run(
        HOPELESS,
        failures=ScriptedFailures(
            {
                "query_itt_slot": [ToolStatus.ERROR, ToolStatus.ERROR],
                "query_outbound_services": [ToolStatus.ERROR, ToolStatus.ERROR],
            }
        ),
    )
    assert result.chosen is None
    assert result.plans == ()
    assert "No feasible option" in result.rationale


def test_options_alive_counts_what_the_line_could_still_take():
    _, result = run(HOPELESS)
    offer = next(p for p in result.plans if p.rung is Rung.OFFER)
    assert offer.options_alive == 3


def test_watcher_confidence_propagates_into_the_plan():
    """A LOW from the Watcher must reach the gate rather than being discarded
    at the boundary."""
    high = run(AVOIDABLE | {"confidence": "HIGH"})[1]
    low = run(AVOIDABLE | {"confidence": "LOW"})[1]
    assert low.chosen.confidence < high.chosen.confidence
