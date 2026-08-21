"""Compare arrival estimators against the same observed crossings.

    uv run python scripts/compare_estimators.py --limit 200000

Every estimator sees identical observations in identical order and may look
only backwards. Window sizes are set a priori, not tuned on this data — if
they get tuned, that has to be held out or the comparison stops meaning
anything.
"""

import argparse
from pathlib import Path

from latch.estimators import default_estimators
from latch.eta_eval import MAX_LOOKBACK_H, Prediction, percentile
from latch.replay import (
    ArrivalBoundary,
    ReplayConfig,
    haversine_km,
    iter_replay_observations,
)

DEFAULT_CSV = (
    Path(__file__).resolve().parent.parent
    / "Data Inspection"
    / "Singapore_anonymized.csv"
)
BUCKETS = (1.0, 3.0, 6.0, 12.0, 24.0)


def bucket_of(lead_h: float) -> float | None:
    if lead_h <= 0:
        return None
    for bound in BUCKETS:
        if lead_h <= bound:
            return bound
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--limit", type=int, default=200_000)
    args = parser.parse_args()

    config = ReplayConfig(boundary=ArrivalBoundary())
    boundary = config.boundary
    estimators = default_estimators(config.minimum_eta_speed_knots)

    inside: dict[str, bool] = {}
    pending: dict[str, list] = {}
    scored: dict[str, list[Prediction]] = {e.name: [] for e in estimators}
    crossings = 0

    for index, observation in enumerate(
        iter_replay_observations(args.csv, config)
    ):
        if index >= args.limit:
            break
        vessel = observation.vessel_id
        distance = haversine_km(
            observation.latitude,
            observation.longitude,
            boundary.latitude,
            boundary.longitude,
        )
        edge_distance = max(0.0, distance - boundary.radius_km)
        now_inside = distance <= boundary.radius_km

        if inside.get(vessel) is False and now_inside:
            crossings += 1
            actual = observation.observed_at
            for made_at, name, predicted in pending.get(vessel, []):
                scored[name].append(
                    Prediction(
                        vessel_id=vessel,
                        method=None,  # type: ignore[arg-type]
                        made_at=made_at,
                        predicted_arrival=predicted,
                        actual_arrival=actual,
                    )
                )
            pending[vessel] = []
            for estimator in estimators:
                estimator.reset(vessel)
            inside[vessel] = True
            continue

        inside[vessel] = now_inside
        if now_inside:
            continue

        buffer = pending.setdefault(vessel, [])
        cutoff = observation.observed_at.timestamp() - MAX_LOOKBACK_H * 3600
        pending[vessel] = [b for b in buffer if b[0].timestamp() >= cutoff]

        for estimator in estimators:
            predicted = estimator.predict(
                vessel,
                observation.observed_at,
                edge_distance,
                observation.speed_over_ground_knots,
            )
            if predicted is not None:
                pending[vessel].append(
                    (observation.observed_at, estimator.name, predicted)
                )

    print(f"observations  {args.limit:,}")
    print(f"crossings     {crossings:,}\n")

    header = f"{'lead':>6}" + "".join(f"{e.name:>22}" for e in estimators)
    print(header)
    for bound in BUCKETS:
        row = f"{bound:5.0f}h"
        for estimator in estimators:
            errors = [
                abs(p.error_h)
                for p in scored[estimator.name]
                if bucket_of(p.lead_time_h) == bound
            ]
            if errors:
                row += f"{percentile(errors, 0.5):>15.2f}h n={len(errors):<5}"
            else:
                row += f"{'—':>22}"
        print(row)

    print("\ncoverage: predictions offered per estimator")
    for estimator in estimators:
        total = len(scored[estimator.name])
        print(f"  {estimator.name:22} {total:7,}")
    print(
        "\nCoverage matters as much as error. An estimator that only predicts\n"
        "when it is confident looks accurate by declining the hard cases, so\n"
        "the two columns have to be read together."
    )


if __name__ == "__main__":
    main()
