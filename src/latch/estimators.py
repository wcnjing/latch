"""Arrival estimators, and the harness to compare them honestly.

The baseline divides straight-line distance by speed over ground. That assumes
the vessel is pointed at the boundary and will keep its current speed, and it
is wrong in the same direction every time: systematically early, by nearly the
full magnitude of its error at every horizon.

Two estimators here try to fix the *estimator* rather than correct its output,
because two post-hoc corrections were measured and both failed — helping long
horizons while destroying short ones.

  MedianSpeed   same geometry, but speed is the median over a trailing window
                instead of whatever the vessel was doing at one instant.
                Removes momentary slowdowns without removing real ones.

  ClosingRate   drops speed over ground entirely and measures how fast the gap
                to the boundary is actually shrinking. A vessel making fifteen
                knots on a tangential heading is not approaching at fifteen
                knots, and this is the only one of the three that knows that.

Every estimator sees a vessel's observations in order and may keep state, but
may only ever look backwards. `predict` is called once per observation with
that observation and nothing after it.
"""

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

KNOTS_TO_KMH = 1.852


class Estimator(Protocol):
    name: str

    def predict(
        self, vessel_id: str, observed_at: datetime, distance_km: float, speed_knots: float | None
    ) -> datetime | None: ...

    def reset(self, vessel_id: str) -> None: ...


@dataclass
class InstantaneousSpeed:
    """The current baseline: distance over speed at this instant."""

    minimum_speed_knots: float = 0.5
    name: str = "instantaneous_speed"

    def predict(self, vessel_id, observed_at, distance_km, speed_knots):
        if speed_knots is None or speed_knots < self.minimum_speed_knots:
            return None
        return observed_at + timedelta(hours=distance_km / (speed_knots * KNOTS_TO_KMH))

    def reset(self, vessel_id: str) -> None:
        return None


@dataclass
class MedianSpeed:
    """Same geometry, median speed over a trailing window.

    A vessel that momentarily drops to two knots in traffic has not changed its
    arrival time much, and the instantaneous estimator believes it has.
    """

    window_h: float = 3.0
    minimum_observations: int = 3
    minimum_speed_knots: float = 0.5
    name: str = "median_speed"
    _history: dict[str, deque] = field(default_factory=dict)

    def reset(self, vessel_id: str) -> None:
        self._history.pop(vessel_id, None)

    def predict(self, vessel_id, observed_at, distance_km, speed_knots):
        history = self._history.setdefault(vessel_id, deque())
        if speed_knots is not None:
            history.append((observed_at, speed_knots))
        cutoff = observed_at - timedelta(hours=self.window_h)
        while history and history[0][0] < cutoff:
            history.popleft()

        if len(history) < self.minimum_observations:
            return None
        speeds = sorted(s for _, s in history)
        median = speeds[len(speeds) // 2]
        if median < self.minimum_speed_knots:
            return None
        return observed_at + timedelta(hours=distance_km / (median * KNOTS_TO_KMH))


@dataclass
class ClosingRate:
    """Predict from how fast the gap to the boundary is actually closing.

    Uses no speed-over-ground at all. Routing, traffic separation and course
    changes are all absorbed automatically, because the only thing measured is
    whether the vessel is getting closer and how quickly.

    A vessel that is not closing gets no prediction rather than a fabricated
    one — which is also the anchored-vessel filter, arrived at for free.
    """

    window_h: float = 3.0
    minimum_observations: int = 3
    minimum_closing_kmh: float = 0.5
    name: str = "closing_rate"
    _history: dict[str, deque] = field(default_factory=dict)

    def reset(self, vessel_id: str) -> None:
        self._history.pop(vessel_id, None)

    def predict(self, vessel_id, observed_at, distance_km, speed_knots):
        history = self._history.setdefault(vessel_id, deque())
        history.append((observed_at, distance_km))
        cutoff = observed_at - timedelta(hours=self.window_h)
        while len(history) > self.minimum_observations and history[0][0] < cutoff:
            history.popleft()

        if len(history) < self.minimum_observations:
            return None

        oldest_at, oldest_distance = history[0]
        elapsed_h = (observed_at - oldest_at).total_seconds() / 3600.0
        if elapsed_h <= 0:
            return None

        closing_kmh = (oldest_distance - distance_km) / elapsed_h
        if closing_kmh < self.minimum_closing_kmh:
            # Stationary, drifting, or heading away. Not an arrival in progress.
            return None
        return observed_at + timedelta(hours=distance_km / closing_kmh)


def default_estimators(minimum_speed_knots: float = 0.5) -> list[Estimator]:
    return [
        InstantaneousSpeed(minimum_speed_knots=minimum_speed_knots),
        MedianSpeed(minimum_speed_knots=minimum_speed_knots),
        ClosingRate(),
    ]
