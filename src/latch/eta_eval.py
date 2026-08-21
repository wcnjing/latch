"""How wrong are our arrival predictions, and wrong compared to what?

This is the only genuinely measurable accuracy in LATCH. Connection risk is
scored against labels we authored, so asking whether the agent "correctly"
detected a risk is circular. Arrival timing is different: A's replay gives us
observed boundary crossings, we predict them beforehand, and the difference is
a real number nobody can argue with.

Two things make it an evaluation rather than a statistic.

**Causality.** A prediction at T-6h uses only the observation at T-6h — its
position and its speed at that moment. Nothing downstream of it exists yet.
`causal_eta` enforces this and the lead-time bucketing preserves it.

**A baseline.** "Median error 3.2 hours" is meaningless alone. The vessel
broadcasts its own ETA over AIS, so we compare against what the master
declared. Beating it is a result; losing to it is a more important one, and
either way the comparison is what makes the number interpretable.

The ground truth is a crossing of an exploratory circular boundary, not an
official PSA berth arrival. That limitation belongs beside every figure this
module produces.
"""

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

# Predictions further out than this are dropped rather than buffered forever.
MAX_LOOKBACK_H = 24.0
# Lead-time buckets, in hours before the observed crossing.
LEAD_BUCKETS_H: tuple[float, ...] = (1.0, 3.0, 6.0, 12.0, 24.0)


class Method(StrEnum):
    DERIVED = "derived_causal_eta"  # ours: position and current speed
    AIS_DECLARED = "ais_declared_eta"  # the vessel's own broadcast ETA


@dataclass(frozen=True, slots=True)
class Prediction:
    vessel_id: str
    method: Method
    made_at: datetime
    predicted_arrival: datetime
    actual_arrival: datetime

    @property
    def lead_time_h(self) -> float:
        return (self.actual_arrival - self.made_at).total_seconds() / 3600.0

    @property
    def error_h(self) -> float:
        """Signed. Positive means we predicted the vessel later than it came.

        The sign matters operationally: predicting late means a connection
        looks doomed when it is fine, and predicting early means the opposite.
        Reporting only the absolute value hides which mistake we make.
        """
        return (
            self.predicted_arrival - self.actual_arrival
        ).total_seconds() / 3600.0

    @property
    def abs_error_h(self) -> float:
        return abs(self.error_h)

    def bucket(self) -> float | None:
        """Smallest bucket whose bound the lead time falls within."""
        lead = self.lead_time_h
        if lead <= 0:
            return None
        for bound in LEAD_BUCKETS_H:
            if lead <= bound:
                return bound
        return None


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    weight = position - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


@dataclass(frozen=True, slots=True)
class BucketStats:
    method: Method
    lead_bucket_h: float
    count: int
    median_abs_error_h: float
    p90_abs_error_h: float
    median_signed_error_h: float
    within_1h: float
    within_3h: float

    def row(self) -> str:
        return (
            f"  <={self.lead_bucket_h:4.0f}h  n={self.count:6,}  "
            f"median |err| {self.median_abs_error_h:6.2f}h  "
            f"p90 {self.p90_abs_error_h:7.2f}h  "
            f"bias {self.median_signed_error_h:+6.2f}h  "
            f"within 1h {self.within_1h:5.1%}  3h {self.within_3h:5.1%}"
        )


def summarise(predictions: list[Prediction]) -> list[BucketStats]:
    """Group by method and lead-time bucket. Buckets with nothing in them are
    omitted rather than reported as zero, which would read as perfect."""
    grouped: dict[tuple[Method, float], list[Prediction]] = {}
    for prediction in predictions:
        bucket = prediction.bucket()
        if bucket is None:
            continue
        grouped.setdefault((prediction.method, bucket), []).append(prediction)

    stats: list[BucketStats] = []
    for (method, bucket), items in sorted(
        grouped.items(), key=lambda kv: (kv[0][0].value, kv[0][1])
    ):
        absolute = [p.abs_error_h for p in items]
        signed = [p.error_h for p in items]
        stats.append(
            BucketStats(
                method=method,
                lead_bucket_h=bucket,
                count=len(items),
                median_abs_error_h=percentile(absolute, 0.5),
                p90_abs_error_h=percentile(absolute, 0.9),
                median_signed_error_h=percentile(signed, 0.5),
                within_1h=sum(1 for e in absolute if e <= 1.0) / len(absolute),
                within_3h=sum(1 for e in absolute if e <= 3.0) / len(absolute),
            )
        )
    return stats


@dataclass(slots=True)
class _Track:
    """Per-vessel buffer of predictions awaiting an observed crossing."""

    inside: bool | None = None
    pending: deque = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.pending is None:
            self.pending = deque()

    def prune(self, now: datetime) -> None:
        cutoff = now - timedelta(hours=MAX_LOOKBACK_H)
        while self.pending and self.pending[0][0] < cutoff:
            self.pending.popleft()


def collect_predictions(
    observations,
    boundary,
    haversine,
    causal_eta_fn,
    minimum_speed_knots: float,
    limit: int | None = None,
) -> tuple[list[Prediction], dict[str, int]]:
    """Stream observations, buffer predictions, resolve them at each crossing.

    A crossing is the first transition from outside the boundary to inside it.
    Only predictions made while the vessel was still outside are scored — a
    prediction made after arrival is not a prediction.
    """
    tracks: dict[str, _Track] = {}
    predictions: list[Prediction] = []
    counts = {"observations": 0, "crossings": 0, "scored": 0, "vessels": 0}

    for index, observation in enumerate(observations):
        if limit is not None and index >= limit:
            break
        counts["observations"] += 1

        track = tracks.get(observation.vessel_id)
        if track is None:
            track = tracks[observation.vessel_id] = _Track()
            counts["vessels"] += 1

        distance = haversine(
            observation.latitude,
            observation.longitude,
            boundary.latitude,
            boundary.longitude,
        )
        inside = distance <= boundary.radius_km

        if track.inside is False and inside:
            # Crossing. Everything buffered was made from outside, before this.
            counts["crossings"] += 1
            actual = observation.observed_at
            for made_at, method, predicted in track.pending:
                predictions.append(
                    Prediction(
                        vessel_id=observation.vessel_id,
                        method=method,
                        made_at=made_at,
                        predicted_arrival=predicted,
                        actual_arrival=actual,
                    )
                )
                counts["scored"] += 1
            track.pending.clear()
            track.inside = True
            continue

        track.inside = inside
        if inside:
            continue

        track.prune(observation.observed_at)

        revision = causal_eta_fn(observation, boundary, minimum_speed_knots)
        if revision is not None:
            track.pending.append(
                (observation.observed_at, Method.DERIVED, revision.estimated_arrival)
            )
        declared = observation.ais_reported_eta
        if declared is not None:
            track.pending.append(
                (observation.observed_at, Method.AIS_DECLARED, declared)
            )

    return predictions, counts
