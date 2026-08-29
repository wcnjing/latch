"""Build a caller-directed PR #6 refinement report without selecting a margin.

This command does not modify the PR #5 report, PR #3 fixtures, Watcher defaults,
or the future reviewed artifact path.  It always evaluates the predeclared
experimental 0h/1h/2h/3h/4h margins at the frozen T-6h/T-3h/T-1h horizons.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from latch.historical_eval import (
    DEFAULT_CONNECTIONS_PER_QUOTA,
    DEFAULT_SOURCE_CALL_LIMIT,
    HistoricalPopulationConfig,
    evaluate_historical_csv,
    file_sha256,
    historical_synthetic_config,
    replay_watcher_assessments,
)
from latch.replay import ArrivalBoundary, ReplayConfig
from latch.synthetic import ProcessScenario
from latch.watcher import WatcherConfig
from latch.watcher_refinement_eval import (
    EXPERIMENTAL_WARNING_MARGINS,
    FROZEN_BASELINE_THRESHOLD,
    FROZEN_EVALUATION_HORIZONS,
    FROZEN_PR5_REFERENCE_MARGIN,
    build_watcher_refinement_report,
    validate_refinement_output_path,
    write_watcher_refinement_report,
)


DEFAULT_CSV = (
    Path(__file__).resolve().parent.parent
    / "Data Inspection"
    / "Singapore_anonymized.csv"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument(
        "--output",
        type=validate_refinement_output_path,
        required=True,
        help=(
            "caller-specified watcher-refinement-report-v1 path; there is no "
            "default tracked artifact"
        ),
    )
    return parser


def parse_cli_args(argv: list[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def run_refinement(args: argparse.Namespace) -> None:
    if not args.csv.is_file() or args.csv.stat().st_size < 1_000:
        raise SystemExit(
            f"{args.csv} is missing or is still an LFS pointer. "
            "Run: git lfs install && git lfs pull"
        )
    dataset_hash = file_sha256(args.csv)
    synthetic_config = historical_synthetic_config(
        dataset_sha256=dataset_hash,
        connections_per_quota=DEFAULT_CONNECTIONS_PER_QUOTA,
    )
    reference_config = WatcherConfig(
        warning_margin=FROZEN_PR5_REFERENCE_MARGIN,
        reference_delay_threshold=FROZEN_BASELINE_THRESHOLD,
        process_scenario=ProcessScenario.REFERENCE,
    )
    reference = evaluate_historical_csv(
        args.csv,
        replay_config=ReplayConfig(boundary=ArrivalBoundary()),
        population_config=HistoricalPopulationConfig(
            source_call_limit=DEFAULT_SOURCE_CALL_LIMIT
        ),
        synthetic_config=synthetic_config,
        watcher_config=reference_config,
    )
    results = tuple(
        reference
        if scenario is ProcessScenario.REFERENCE
        else replay_watcher_assessments(
            reference.population,
            reference.benchmark,
            replace(reference_config, process_scenario=scenario),
        )
        for scenario in ProcessScenario
    )
    report = build_watcher_refinement_report(
        results,
        dataset_hash=dataset_hash,
        warning_margins=EXPERIMENTAL_WARNING_MARGINS,
        evaluation_horizons=FROZEN_EVALUATION_HORIZONS,
    )
    write_watcher_refinement_report(report, args.output)


def main() -> None:
    args = parse_cli_args()
    run_refinement(args)
    print(f"Deterministic watcher-refinement-report-v1 written to {args.output}")
    print(
        "All experimental margins were reported; no preferred margin was selected."
    )


if __name__ == "__main__":
    main()
