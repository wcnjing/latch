"""Measure arrival-prediction error against observed boundary crossings.

    uv run python scripts/eval_eta.py --limit 200000

This produces the one number in LATCH that is genuinely checkable: how far
wrong our arrival predictions are, compared with the ETA the vessel itself
broadcasts. Everything else in the system is scored against labels we wrote.
"""

import argparse
from pathlib import Path

from latch.eta_eval import Method, collect_predictions, summarise
from latch.replay import (
    ArrivalBoundary,
    ReplayConfig,
    causal_eta,
    haversine_km,
    iter_replay_observations,
)

DEFAULT_CSV = (
    Path(__file__).resolve().parent.parent
    / "Data Inspection"
    / "Singapore_anonymized.csv"
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--limit", type=int, default=200_000)
    args = parser.parse_args()

    if not args.csv.is_file() or args.csv.stat().st_size < 1_000:
        raise SystemExit(f"{args.csv} missing or still an LFS pointer")

    config = ReplayConfig(boundary=ArrivalBoundary())
    predictions, counts = collect_predictions(
        iter_replay_observations(args.csv, config),
        config.boundary,
        haversine_km,
        causal_eta,
        config.minimum_eta_speed_knots,
        limit=args.limit,
    )

    print(f"observations   {counts['observations']:,}")
    print(f"vessels        {counts['vessels']:,}")
    print(f"crossings      {counts['crossings']:,}")
    print(f"predictions    {counts['scored']:,}\n")

    stats = summarise(predictions)
    if not stats:
        print("No scored predictions in this slice — widen --limit.")
        return

    for method in (Method.DERIVED, Method.AIS_DECLARED):
        rows = [s for s in stats if s.method is method]
        if not rows:
            continue
        print(f"{method.value}")
        for row in rows:
            print(row.row())
        print()

    print(
        "The declared-ETA rows are NOT a baseline we beat. A vessel broadcasts\n"
        "an ETA for its next port, which for much of this traffic is not\n"
        "Singapore at all — the p90 running to thousands of hours is ships\n"
        "transiting to Europe, not a parsing bug. The two columns measure\n"
        "different quantities and the comparison is not a scoreboard.\n\n"
        "What it does show is that arrival timing has to be derived. You cannot\n"
        "read a usable Singapore ETA off the AIS feed.\n"
    )
    print(
        "Ground truth is a crossing of an exploratory circular boundary, not an\n"
        "official PSA berth arrival. That limitation belongs beside every figure\n"
        "above."
    )


if __name__ == "__main__":
    main()
