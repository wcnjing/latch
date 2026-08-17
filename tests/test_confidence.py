"""Confidence engine tests.

The point of these is that the number is reproducible and derived. If a judge
asks "how did you get 0.62?", `explain()` answers it in one line.
"""

import pytest

from latch.confidence import ProvenanceConfidence, age_factor, score
from latch.models import Provenance, SourceKind, ToolOutcome

ENGINE = ProvenanceConfidence()


def live(name: str = "itt_capacity") -> Provenance:
    return Provenance(name, SourceKind.LIVE_API, age_min=0.0)


def test_all_live_and_verified_scores_high():
    result = ENGINE.score((live("a"), live("b")))
    assert result.confidence == pytest.approx(1.0)


def test_no_provenance_scores_at_the_floor():
    """A plan resting on nothing we can name is not a confident plan."""
    result = ENGINE.score(())
    assert result.confidence == pytest.approx(0.05)
    assert result.input_count == 0


def test_baseline_demo_scenario_derivation():
    """The §7.1 scenario: live call fails, cache serves an 8-minute-old value,
    two inputs unverified.

    Worked derivation, for the appendix:
        source (cache)      0.85
        age    (8 min)      1 / (1 + 8/120)  = 0.9375
        tool   (retried)    0.90
        penalty             2 x 0.05         = 0.10
        confidence = 0.85 x 0.9375 x 0.90 - 0.10 = 0.6172
    """
    provenance = (
        Provenance(
            "itt_capacity",
            SourceKind.CACHE,
            age_min=8.0,
            tool_outcome=ToolOutcome.RETRIED,
            verified=False,
        ),
        Provenance(
            "outbound_capacity",
            SourceKind.LIVE_API,
            age_min=1.0,
            verified=False,
        ),
        live("berth_window"),
    )
    result = ENGINE.score(provenance)

    assert result.confidence == pytest.approx(0.6172, abs=1e-4)
    assert result.weakest_source == "cache"
    assert result.worst_tool_outcome == "retried"
    assert result.unverified_count == 2
    assert "= 0.62" in result.explain()


def test_score_falls_below_the_escalation_threshold_in_the_demo():
    """The Gate Controller escalates under 0.70; the baseline scenario must
    actually cross it, or the demo has no gate to show."""
    from latch.config import CONFIDENCE_ESCALATION_THRESHOLD

    provenance = (
        Provenance(
            "itt_capacity",
            SourceKind.CACHE,
            age_min=8.0,
            tool_outcome=ToolOutcome.RETRIED,
            verified=False,
        ),
        Provenance("outbound_capacity", SourceKind.LIVE_API, verified=False),
    )
    assert ENGINE.score(provenance).confidence < CONFIDENCE_ESCALATION_THRESHOLD


def test_weakest_input_governs_not_the_average():
    """One assumed default among nine live reads should still hurt. Averaging
    would let a plan hide a guess behind a crowd of good inputs."""
    good = tuple(live(f"f{i}") for i in range(9))
    with_guess = good + (Provenance("guess", SourceKind.ASSUMED_DEFAULT),)

    assert ENGINE.score(with_guess).confidence < ENGINE.score(good).confidence
    assert ENGINE.score(with_guess).weakest_source == "assumed_default"


def test_assumed_defaults_are_penalised_hardest():
    cached = ENGINE.score((Provenance("x", SourceKind.CACHE),)).confidence
    assumed = ENGINE.score((Provenance("x", SourceKind.ASSUMED_DEFAULT),)).confidence
    live_only = ENGINE.score((live(),)).confidence
    assert assumed < cached < live_only


def test_tool_failure_reduces_sharply():
    ok = ENGINE.score((Provenance("x", SourceKind.LIVE_API),)).confidence
    failed = ENGINE.score(
        (Provenance("x", SourceKind.LIVE_API, tool_outcome=ToolOutcome.FAILED),)
    ).confidence
    assert failed < ok
    assert failed == pytest.approx(0.70)


def test_age_decays_monotonically_and_never_reaches_zero():
    ages = [0, 5, 30, 120, 600, 5_000]
    factors = [age_factor(a) for a in ages]
    assert factors == sorted(factors, reverse=True)
    assert factors[0] == pytest.approx(1.0)
    assert factors[-1] > 0.0


def test_unverified_penalty_is_linear():
    base = (live("a"),)
    one = base + (Provenance("b", SourceKind.LIVE_API, verified=False),)
    two = one + (Provenance("c", SourceKind.LIVE_API, verified=False),)
    assert ENGINE.score(one).confidence - ENGINE.score(two).confidence == pytest.approx(
        0.05
    )


def test_confidence_is_clamped_into_range():
    many_unverified = tuple(
        Provenance(f"f{i}", SourceKind.ASSUMED_DEFAULT, age_min=9_000, verified=False)
        for i in range(40)
    )
    result = ENGINE.score(many_unverified)
    assert 0.0 < result.confidence <= 1.0
    assert result.confidence == pytest.approx(0.05)


def test_engine_is_deterministic():
    provenance = (
        Provenance("a", SourceKind.CACHE, age_min=8.0, verified=False),
        live("b"),
    )
    assert score(provenance).confidence == score(provenance).confidence


def test_breakdown_serialises_with_its_derivation():
    result = ENGINE.score((Provenance("x", SourceKind.CACHE, age_min=8.0),))
    payload = result.as_dict()
    assert payload["method"] == "provenance"
    assert payload["factors"]["source"] == "cache"
    assert "derivation" in payload
