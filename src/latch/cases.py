"""One connection, one live case.

The Watcher polls. A connection under pressure therefore produces a fresh risk
event every cycle, and without this the agent walks the whole ladder again on
every one — re-deliberating, re-claiming locks, re-asking for approval on a
decision it already made, and writing a separate trace each time.

That is not only wasteful. It corrupts every metric computed from the traces,
because the same connection is counted once per observation rather than once
per connection. A service rate over duplicated cases is not a rate.

`SUPERSEDED` already existed in the state machine for exactly this and nothing
used it. This is what uses it.

The registry answers one question per event: is this new work, a material
change to work in flight, or noise?

    NEW               nothing in flight for this connection; process it
    SUPERSEDES        in flight, and something material moved; close the old
                      case as SUPERSEDED and process the new one
    DUPLICATE         in flight, nothing material moved; drop it
    RECOVERED         in flight, and the risk has evaporated; close the old
                      case as SUPERSEDED and process nothing
    ALREADY_RESOLVED  we acted, and nothing has got worse since; drop it
"""

from dataclasses import dataclass
from enum import StrEnum

from latch.events import RiskEvent, RiskSeverity

# Below this, a change in slack is the ETA estimate jittering rather than the
# connection genuinely moving. Re-running the ladder on jitter would spend the
# expensive model on noise.
DEFAULT_SLACK_DELTA_H = 0.5


class Admission(StrEnum):
    NEW = "new"
    SUPERSEDES = "supersedes"
    DUPLICATE = "duplicate"
    RECOVERED = "recovered"
    ALREADY_RESOLVED = "already_resolved"


@dataclass(frozen=True, slots=True)
class AdmissionDecision:
    admission: Admission
    connection_id: str
    reason: str
    superseded_trace_id: str | None = None

    @property
    def should_process(self) -> bool:
        """Only new work and material changes reach the agent."""
        return self.admission in (Admission.NEW, Admission.SUPERSEDES)

    @property
    def closes_previous(self) -> bool:
        return self.superseded_trace_id is not None


@dataclass(slots=True)
class _Case:
    connection_id: str
    severity: RiskSeverity
    slack_h: float
    trace_id: str | None = None
    resolved: bool = False


class CaseRegistry:
    """Tracks what is in flight, keyed by connection."""

    def __init__(self, slack_delta_h: float = DEFAULT_SLACK_DELTA_H) -> None:
        self._cases: dict[str, _Case] = {}
        self._slack_delta_h = slack_delta_h
        self.counts: dict[str, int] = {a.value: 0 for a in Admission}

    def in_flight(self) -> int:
        return sum(1 for c in self._cases.values() if not c.resolved)

    def _record(self, decision: AdmissionDecision) -> AdmissionDecision:
        self.counts[decision.admission.value] += 1
        return decision

    def admit(self, event: RiskEvent) -> AdmissionDecision:
        """Decide what to do with one freshly-emitted risk event."""
        existing = self._cases.get(event.connection_id)
        slack = event.current_plan_slack_hours

        if existing is None:
            if not event.is_actionable:
                # A SAFE connection we have never seen is not a case. Admitting
                # it would fill the registry with the 65% of traffic that is
                # simply fine.
                return self._record(
                    AdmissionDecision(
                        Admission.DUPLICATE,
                        event.connection_id,
                        "not actionable and not in flight",
                    )
                )
            self._cases[event.connection_id] = _Case(
                event.connection_id, event.state, slack
            )
            return self._record(
                AdmissionDecision(Admission.NEW, event.connection_id, "first sighting")
            )

        moved = abs(slack - existing.slack_h)
        worse = slack < existing.slack_h - self._slack_delta_h

        if existing.resolved:
            if not worse:
                return self._record(
                    AdmissionDecision(
                        Admission.ALREADY_RESOLVED,
                        event.connection_id,
                        "acted already; nothing worse since",
                    )
                )
            # We acted, and the vessel has slipped further. The earlier
            # decision may no longer hold, so this is genuinely new work.
            self._cases[event.connection_id] = _Case(
                event.connection_id, event.state, slack
            )
            return self._record(
                AdmissionDecision(
                    Admission.NEW,
                    event.connection_id,
                    f"slipped a further {moved:.1f}h after we acted",
                )
            )

        if not event.is_actionable:
            previous_trace = existing.trace_id
            del self._cases[event.connection_id]
            return self._record(
                AdmissionDecision(
                    Admission.RECOVERED,
                    event.connection_id,
                    "ETA improved; connection no longer at risk",
                    superseded_trace_id=previous_trace,
                )
            )

        severity_changed = event.state is not existing.severity
        if not severity_changed and moved <= self._slack_delta_h:
            return self._record(
                AdmissionDecision(
                    Admission.DUPLICATE,
                    event.connection_id,
                    f"slack moved {moved:.2f}h; below the "
                    f"{self._slack_delta_h}h threshold",
                )
            )

        previous_trace = existing.trace_id
        existing.severity = event.state
        existing.slack_h = slack
        existing.trace_id = None
        reason = (
            f"severity {existing.severity.value}" if severity_changed
            else f"slack moved {moved:.1f}h"
        )
        return self._record(
            AdmissionDecision(
                Admission.SUPERSEDES,
                event.connection_id,
                reason,
                superseded_trace_id=previous_trace,
            )
        )

    def opened(self, connection_id: str, trace_id: str) -> None:
        """Attach the trace the agent opened, so a later event can supersede it."""
        case = self._cases.get(connection_id)
        if case is not None:
            case.trace_id = trace_id

    def resolved(self, connection_id: str) -> None:
        """Mark the case terminal. Later events reopen only if things worsen."""
        case = self._cases.get(connection_id)
        if case is not None:
            case.resolved = True
