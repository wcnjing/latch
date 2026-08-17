"""Confidence, computed from provenance. Never self-reported.

The dynamic gating mechanism hinges on this number. If the model sets it, a
judge asks "so the agent decides how much you should trust it?" and the Gate
Controller's whole point collapses. So the model may reason about its
certainty in the rationale; it may never write this field.

The formula is deliberately simple enough to put on a slide:

    confidence = source x age_decay x tool_outcome - unverified_penalty

where each factor is taken from the *weakest* input in the plan. A plan is
only as trustworthy as the worst thing it rests on.

Workstream C owns the production engine. `ConfidenceEngine` is the interface
it must satisfy; `ProvenanceConfidence` below is a working implementation the
agent core runs against in the meantime.
"""

from dataclasses import dataclass
from typing import Protocol

from latch.config import (
    CONFIDENCE_AGE_SCALE_MIN,
    CONFIDENCE_FLOOR,
    CONFIDENCE_SOURCE_FACTOR,
    CONFIDENCE_TOOL_FACTOR,
    CONFIDENCE_UNVERIFIED_PENALTY,
)
from latch.models import Provenance


@dataclass(frozen=True, slots=True)
class ConfidenceBreakdown:
    """Every factor that produced a score, kept for the trace and the deck.

    Emitting the derivation rather than the bare number is what turns "the
    agent cannot self-certify" from a claim into a demonstration.
    """

    confidence: float
    source_factor: float
    age_factor: float
    tool_factor: float
    unverified_penalty: float
    weakest_source: str
    max_age_min: float
    worst_tool_outcome: str
    unverified_count: int
    input_count: int

    def explain(self) -> str:
        """Human-readable derivation. Goes in the appendix, verbatim."""
        return (
            f"source={self.source_factor:.2f} ({self.weakest_source}) x "
            f"age={self.age_factor:.3f} ({self.max_age_min:.0f}m) x "
            f"tool={self.tool_factor:.2f} ({self.worst_tool_outcome}) "
            f"- unverified={self.unverified_penalty:.2f} "
            f"({self.unverified_count} of {self.input_count}) "
            f"= {self.confidence:.2f}"
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "computed": round(self.confidence, 4),
            "method": "provenance",
            "factors": {
                "source": self.weakest_source,
                "source_factor": self.source_factor,
                "data_age_min": self.max_age_min,
                "age_factor": round(self.age_factor, 4),
                "tool_outcome": self.worst_tool_outcome,
                "tool_factor": self.tool_factor,
                "unverified_inputs": self.unverified_count,
                "unverified_penalty": round(self.unverified_penalty, 4),
            },
            "derivation": self.explain(),
        }


class ConfidenceEngine(Protocol):
    """The seam workstream C implements against."""

    def score(self, provenance: tuple[Provenance, ...]) -> ConfidenceBreakdown: ...


def age_factor(age_min: float) -> float:
    """Decay for stale inputs.

    Reciprocal rather than exponential: an eight-minute-old cache read should
    be mildly discounted, not gutted, while a genuinely stale input still
    decays without ever reaching zero.
    """
    return 1.0 / (1.0 + max(age_min, 0.0) / CONFIDENCE_AGE_SCALE_MIN)


class ProvenanceConfidence:
    """Reference implementation. Deterministic and side-effect free."""

    def score(self, provenance: tuple[Provenance, ...]) -> ConfidenceBreakdown:
        if not provenance:
            # A plan resting on nothing we can name is not a confident plan.
            return ConfidenceBreakdown(
                confidence=CONFIDENCE_FLOOR,
                source_factor=0.0,
                age_factor=0.0,
                tool_factor=0.0,
                unverified_penalty=0.0,
                weakest_source="none",
                max_age_min=0.0,
                worst_tool_outcome="none",
                unverified_count=0,
                input_count=0,
            )

        weakest = min(provenance, key=lambda p: CONFIDENCE_SOURCE_FACTOR[p.source])
        worst_tool = min(provenance, key=lambda p: CONFIDENCE_TOOL_FACTOR[p.tool_outcome])
        oldest = max(p.age_min for p in provenance)
        unverified = sum(1 for p in provenance if not p.verified)

        s_factor = CONFIDENCE_SOURCE_FACTOR[weakest.source]
        a_factor = age_factor(oldest)
        t_factor = CONFIDENCE_TOOL_FACTOR[worst_tool.tool_outcome]
        penalty = CONFIDENCE_UNVERIFIED_PENALTY * unverified

        raw = (s_factor * a_factor * t_factor) - penalty
        confidence = min(max(raw, CONFIDENCE_FLOOR), 1.0)

        return ConfidenceBreakdown(
            confidence=confidence,
            source_factor=s_factor,
            age_factor=a_factor,
            tool_factor=t_factor,
            unverified_penalty=penalty,
            weakest_source=weakest.source.value,
            max_age_min=oldest,
            worst_tool_outcome=worst_tool.tool_outcome.value,
            unverified_count=unverified,
            input_count=len(provenance),
        )


DEFAULT_ENGINE: ConfidenceEngine = ProvenanceConfidence()


def score(provenance: tuple[Provenance, ...]) -> ConfidenceBreakdown:
    """Module-level convenience over the default engine."""
    return DEFAULT_ENGINE.score(provenance)
