"""Tool result envelope, retry policy, and deterministic failure injection.

Two things matter here beyond plumbing.

First, every tool result carries its own `Provenance`. Confidence is therefore
computed from what the tools actually did on this run — a retried call or a
cache fallback moves the number by itself, with nobody deciding it should.

Second, failures are injected from a plan rather than sampled at wall-clock
random. The baseline demo has to replay identically every time it is recorded,
and a scenario suite whose failures move between runs cannot be reported as an
accuracy figure.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from random import Random
from typing import Any, Protocol

from latch.models import Provenance, SourceKind, ToolOutcome


class ToolStatus(StrEnum):
    OK = "ok"
    TIMEOUT = "timeout"
    ERROR = "error"
    CACHED_FALLBACK = "cached_fallback"  # live call failed; stale value served


@dataclass(frozen=True, slots=True)
class ToolResult:
    tool: str
    status: ToolStatus
    value: Any
    latency_ms: int
    source: SourceKind
    age_min: float = 0.0
    attempts: int = 1
    error_class: str | None = None

    @property
    def ok(self) -> bool:
        return self.status in (ToolStatus.OK, ToolStatus.CACHED_FALLBACK)

    @property
    def tool_outcome(self) -> ToolOutcome:
        if self.status is ToolStatus.OK:
            return ToolOutcome.OK if self.attempts == 1 else ToolOutcome.RETRIED
        if self.status is ToolStatus.CACHED_FALLBACK:
            return ToolOutcome.RETRIED
        return ToolOutcome.FAILED

    def provenance(self, field_name: str, verified: bool = True) -> Provenance:
        """The confidence engine's view of this call."""
        return Provenance(
            field_name=field_name,
            source=self.source,
            age_min=self.age_min,
            tool_outcome=self.tool_outcome,
            verified=verified and self.status is ToolStatus.OK,
        )


class FailurePlan(Protocol):
    """Decides what a given tool attempt does. Deterministic by contract."""

    def next_outcome(self, tool: str) -> ToolStatus: ...


class NoFailures:
    """Everything succeeds. The default."""

    def next_outcome(self, tool: str) -> ToolStatus:
        return ToolStatus.OK


class ScriptedFailures:
    """An explicit outcome sequence per tool, for the recorded demo.

    `ScriptedFailures({"query_itt_slot": [TIMEOUT, TIMEOUT]})` gives the
    baseline scenario: the call times out, the retry times out, and the caller
    falls back to cache. Once a script is exhausted the tool succeeds.
    """

    def __init__(self, script: dict[str, list[ToolStatus]]) -> None:
        self._script = {tool: list(seq) for tool, seq in script.items()}

    def next_outcome(self, tool: str) -> ToolStatus:
        queue = self._script.get(tool)
        if not queue:
            return ToolStatus.OK
        return queue.pop(0)


class SeededFailures:
    """Reproducible pseudo-random failures, for the scenario suite.

    Same seed, same failures, every run — so a reported accuracy figure means
    something.
    """

    def __init__(self, seed: int, timeout_rate: float = 0.10, error_rate: float = 0.05) -> None:
        self._rng = Random(seed)
        self._timeout_rate = timeout_rate
        self._error_rate = error_rate

    def next_outcome(self, tool: str) -> ToolStatus:
        roll = self._rng.random()
        if roll < self._timeout_rate:
            return ToolStatus.TIMEOUT
        if roll < self._timeout_rate + self._error_rate:
            return ToolStatus.ERROR
        return ToolStatus.OK


# Base latency per tool, in ms. Fixed rather than sampled so the demo timeline
# is identical on every take.
BASE_LATENCY_MS: dict[str, int] = {
    "query_itt_slot": 420,
    "book_itt_slot": 850,
    "query_berth_plan": 300,
    "connection_density_score": 180,
    "query_outbound_services": 260,
    "send_options_to_line": 640,
}
DEFAULT_LATENCY_MS = 250
TIMEOUT_LATENCY_MS = 5_000


@dataclass(frozen=True, slots=True)
class CacheEntry:
    value: Any
    age_min: float


def call(
    tool: str,
    fn: Callable[[], Any],
    plan: FailurePlan,
    *,
    max_retries: int = 1,
    cache: CacheEntry | None = None,
) -> ToolResult:
    """Invoke a stub tool under a failure plan, with retry and cache fallback.

    `max_retries=1` means two attempts total. On exhaustion, a cache entry (if
    supplied) is served with its real age attached — which is what drops
    confidence in the baseline scenario, without anyone choosing to drop it.
    """
    base = BASE_LATENCY_MS.get(tool, DEFAULT_LATENCY_MS)
    elapsed = 0
    last_status = ToolStatus.OK

    for attempt in range(1, max_retries + 2):
        outcome = plan.next_outcome(tool)
        if outcome is ToolStatus.OK:
            elapsed += base * attempt
            return ToolResult(
                tool=tool,
                status=ToolStatus.OK,
                value=fn(),
                latency_ms=elapsed,
                source=SourceKind.LIVE_API,
                attempts=attempt,
            )
        last_status = outcome
        # A timeout costs the full wait; a hard error returns fast.
        elapsed += TIMEOUT_LATENCY_MS if outcome is ToolStatus.TIMEOUT else base

    attempts = max_retries + 1
    if cache is not None:
        return ToolResult(
            tool=tool,
            status=ToolStatus.CACHED_FALLBACK,
            value=cache.value,
            latency_ms=elapsed,
            source=SourceKind.CACHE,
            age_min=cache.age_min,
            attempts=attempts,
            error_class=last_status.value,
        )

    return ToolResult(
        tool=tool,
        status=last_status,
        value=None,
        latency_ms=elapsed,
        source=SourceKind.ASSUMED_DEFAULT,
        attempts=attempts,
        error_class=last_status.value,
    )
