"""Generate the separate deterministic terminal-prevention challenge report."""

from __future__ import annotations

import argparse
from pathlib import Path

from latch.historical_eval import (
    DEFAULT_CONNECTIONS_PER_QUOTA,
    DEFAULT_SOURCE_CALL_LIMIT,
    HistoricalPopulationConfig,
    evaluate_historical_csv,
    file_sha256,
    historical_synthetic_config,
)
from latch.replay import ArrivalBoundary, ReplayConfig
from latch.synthetic import ProcessScenario
from latch.terminal_prevention_challenge import (
    CAUSAL_ACTIONABILITY_CURATION_LABEL,
    CHALLENGE_CURATION_LABEL,
    build_terminal_prevention_challenge_report,
    validate_challenge_output_path,
    write_terminal_prevention_challenge_report,
)
from latch.watcher import WatcherConfig
from latch.watcher_refinement_eval import (
    FROZEN_BASELINE_THRESHOLD,
    FROZEN_PR5_REFERENCE_MARGIN,
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
        type=validate_challenge_output_path,
        required=True,
        help=(
            "caller-specified terminal-prevention-challenge-v1 path; historical "
            "artifacts and frozen evidence are rejected"
        ),
    )
    return parser


def parse_cli_args(argv: list[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def run_challenge(args: argparse.Namespace) -> None:
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
    frozen_reference = evaluate_historical_csv(
        args.csv,
        replay_config=ReplayConfig(boundary=ArrivalBoundary()),
        population_config=HistoricalPopulationConfig(
            source_call_limit=DEFAULT_SOURCE_CALL_LIMIT
        ),
        synthetic_config=synthetic_config,
        watcher_config=WatcherConfig(
            warning_margin=FROZEN_PR5_REFERENCE_MARGIN,
            reference_delay_threshold=FROZEN_BASELINE_THRESHOLD,
            process_scenario=ProcessScenario.REFERENCE,
        ),
    )
    report = build_terminal_prevention_challenge_report(
        frozen_reference,
        synthetic_config=synthetic_config,
        dataset_hash=dataset_hash,
    )
    write_terminal_prevention_challenge_report(report, args.output)


def main() -> None:
    args = parse_cli_args()
    run_challenge(args)
    print(f"Deterministic terminal-prevention-challenge-v1 written to {args.output}")
    print(CHALLENGE_CURATION_LABEL)
    print(CAUSAL_ACTIONABILITY_CURATION_LABEL)
    print("The frozen historical benchmark was not extended or rescored.")


if __name__ == "__main__":
    main()
