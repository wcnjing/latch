"""The Lock Table: a reservation store for contested resources.

Disruption is correlated by definition — that is the premise of the whole
pitch. Twenty risks fire at once and compete for the same scarce inter-terminal
slot. Without this, two Deliberation agents both happily book the last one and
the system quietly produces an impossible plan.

This is not a full resource broker and should not be described as one. It does
four things:

  - a plan claims a slot before committing
  - a competing claim is arbitrated on boxes-at-risk over slack, not first-come
  - the loser is told, so it can re-deliberate with that option removed
  - reservations expire, so a plan that dies mid-flight does not leak the slot

The reservation/commit split is what makes preemption safe. A reservation is
provisional and can be taken by a more urgent risk; a commit means the action
has fired and is never preempted, because the physical move has begun.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from latch.config import LOCK_TTL_SEC


def _default_clock() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class Reservation:
    resource: str
    risk_id: str
    priority: float
    claimed_at: datetime
    expires_at: datetime
    committed: bool = False

    def expired(self, now: datetime) -> bool:
        # A committed reservation holds until explicitly released: the move is
        # already happening, and a TTL sweep must not un-book it.
        return not self.committed and now >= self.expires_at


@dataclass(frozen=True, slots=True)
class ClaimResult:
    """Outcome of one claim, shaped for the trace `lock` step."""

    granted: bool
    resource: str
    risk_id: str
    our_priority: float
    winner_priority: float | None = None
    preempted_risk_id: str | None = None
    reason: str = ""

    @property
    def status(self) -> str:
        return "held" if self.granted else "lost"


class LockTable:
    """In-memory reservation store, single-process.

    A clock is injectable so contention and expiry are testable without
    sleeping — the demo needs to be reproducible frame by frame.
    """

    def __init__(
        self,
        ttl_sec: int = LOCK_TTL_SEC,
        clock: Callable[[], datetime] = _default_clock,
    ) -> None:
        self._held: dict[str, Reservation] = {}
        self._ttl = timedelta(seconds=ttl_sec)
        self._clock = clock

    # --- inspection ---------------------------------------------------------

    def holder(self, resource: str) -> Reservation | None:
        self._sweep()
        return self._held.get(resource)

    def held_by(self, risk_id: str) -> list[str]:
        self._sweep()
        return sorted(r for r, res in self._held.items() if res.risk_id == risk_id)

    def _sweep(self) -> None:
        now = self._clock()
        for resource, res in list(self._held.items()):
            if res.expired(now):
                del self._held[resource]

    # --- claiming -----------------------------------------------------------

    def claim(self, resource: str, risk_id: str, priority: float) -> ClaimResult:
        """Attempt to reserve `resource` for `risk_id`.

        Returns a granted result, possibly naming a risk that was preempted
        and must be moved to LOST_LOCK by the caller.
        """
        self._sweep()
        now = self._clock()
        incumbent = self._held.get(resource)

        if incumbent is None:
            self._grant(resource, risk_id, priority, now)
            return ClaimResult(
                granted=True,
                resource=resource,
                risk_id=risk_id,
                our_priority=priority,
                reason="uncontested",
            )

        if incumbent.risk_id == risk_id:
            # Re-claiming our own reservation refreshes it rather than
            # deadlocking against ourselves.
            self._grant(resource, risk_id, priority, now, incumbent.committed)
            return ClaimResult(
                granted=True,
                resource=resource,
                risk_id=risk_id,
                our_priority=priority,
                reason="already_held",
            )

        if incumbent.committed:
            return ClaimResult(
                granted=False,
                resource=resource,
                risk_id=risk_id,
                our_priority=priority,
                winner_priority=incumbent.priority,
                reason="incumbent_committed",
            )

        # Strictly greater, so equal priority leaves the incumbent in place.
        # Ties going to whoever asked first is the only stable rule available,
        # and stability matters more here than the coin flip does.
        if priority > incumbent.priority:
            self._grant(resource, risk_id, priority, now)
            return ClaimResult(
                granted=True,
                resource=resource,
                risk_id=risk_id,
                our_priority=priority,
                winner_priority=priority,
                preempted_risk_id=incumbent.risk_id,
                reason="preempted_lower_priority",
            )

        return ClaimResult(
            granted=False,
            resource=resource,
            risk_id=risk_id,
            our_priority=priority,
            winner_priority=incumbent.priority,
            reason="outranked",
        )

    def _grant(
        self,
        resource: str,
        risk_id: str,
        priority: float,
        now: datetime,
        committed: bool = False,
    ) -> None:
        self._held[resource] = Reservation(
            resource=resource,
            risk_id=risk_id,
            priority=priority,
            claimed_at=now,
            expires_at=now + self._ttl,
            committed=committed,
        )

    # --- lifecycle ----------------------------------------------------------

    def commit(self, resource: str, risk_id: str) -> bool:
        """Promote a reservation to committed. Returns False if we lost it.

        Checking the return value is the whole point: between claiming and
        committing, a more urgent risk may have taken the slot.
        """
        self._sweep()
        res = self._held.get(resource)
        if res is None or res.risk_id != risk_id:
            return False
        self._held[resource] = Reservation(
            resource=res.resource,
            risk_id=res.risk_id,
            priority=res.priority,
            claimed_at=res.claimed_at,
            expires_at=res.expires_at,
            committed=True,
        )
        return True

    def release(self, resource: str, risk_id: str) -> bool:
        """Give up a resource. Only the holder may release it."""
        res = self._held.get(resource)
        if res is None or res.risk_id != risk_id:
            return False
        del self._held[resource]
        return True

    def release_all(self, risk_id: str) -> list[str]:
        """Release everything a risk holds. Called when it reaches a terminal state."""
        released = [r for r, res in self._held.items() if res.risk_id == risk_id]
        for resource in released:
            del self._held[resource]
        return sorted(released)
