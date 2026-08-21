"""Why long-range arrival prediction is hard here, measured rather than assumed.

Three estimators were tried against observed crossings and all three were
marginal beyond a few hours. This script explains why, and the answer changes
what LATCH should claim.

A vessel twenty-four hours from the boundary is not steaming for twenty-four
hours. It steams for a few and then waits — at anchor, for a berth, for a
pilot. No estimator built on the vessel's own motion can predict that wait,
because the wait is set by berth availability rather than by the ship.

That bounds the useful horizon, and it is worth stating precisely rather than
discovering during questions.

    uv run python scripts/analyse_waiting.py --limit 200000
"""

import argparse
from collections import defaultdict
from pathlib import Path

from latch.eta_eval import percentile
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
WAITING_KNOTS = 1.0
WINDOW_H = 24.0
MIN_OBSERVATIONS = 8


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--limit", type=int, default=200_000)
    args = parser.parse_args()

    config = ReplayConfig(boundary=ArrivalBoundary())
    boundary = config.boundary
    history: dict[str, list] = defaultdict(list)
    inside: dict[str, bool] = {}
    waiting_shares: list[float] = []

    for index, observation in enumerate(iter_replay_observations(args.csv, config)):
        if index >= args.limit:
            break
        vessel = observation.vessel_id
        distance = haversine_km(
            observation.latitude,
            observation.longitude,
            boundary.latitude,
            boundary.longitude,
        )
        now_inside = distance <= boundary.radius_km

        if inside.get(vessel) is False and now_inside:
            recent = [
                entry
                for entry in history[vessel]
                if (observation.observed_at - entry[0]).total_seconds()
                <= WINDOW_H * 3600
            ]
            if len(recent) >= MIN_OBSERVATIONS:
                stopped = sum(
                    1
                    for _, speed in recent
                    if speed is not None and speed < WAITING_KNOTS
                )
                waiting_shares.append(stopped / len(recent))
            history[vessel] = []
            inside[vessel] = True
            continue

        inside[vessel] = now_inside
        if not now_inside:
            history[vessel].append(
                (observation.observed_at, observation.speed_over_ground_knots)
            )
            if len(history[vessel]) > 400:
                history[vessel] = history[vessel][-400:]

    if not waiting_shares:
        print("No crossings with enough prior history in this slice.")
        return

    print(f"crossings analysed   {len(waiting_shares):,}")
    print(
        f"\nshare of the final {WINDOW_H:.0f}h before crossing spent "
        f"below {WAITING_KNOTS:.0f} knot:"
    )
    for quantile in (0.25, 0.5, 0.75, 0.9):
        print(f"  p{int(quantile * 100):<3} {percentile(waiting_shares, quantile):6.1%}")

    waited = sum(1 for s in waiting_shares if s > 0.3) / len(waiting_shares)
    steamed = sum(1 for s in waiting_shares if s < 0.05) / len(waiting_shares)
    print(f"\nwaited for more than 30% of the window   {waited:6.1%}")
    print(f"arrived with essentially no waiting       {steamed:6.1%}")

    print(
        "\nThis is why better speed estimation stopped helping past a few hours.\n"
        "The residual error is not mismeasured motion, it is unpredicted queueing,\n"
        "and the queue is set by berth and pilot availability rather than by the\n"
        "vessel. Predicting it needs data we do not have — and that PSA does."
    )


if __name__ == "__main__":
    main()
