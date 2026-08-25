"""Regenerate only the tiny PR #3 synthetic contract fixture.

TEST-ONLY SYNTHETIC FIXTURE VALUES. NOT PSA OPERATIONAL ESTIMATES OR
PREVALENCE. Historical CSV generation is deliberately disabled until explicit
historical quota and assumption configuration has been frozen.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from latch.replay import (
    CausalArrivalUpdate,
    DataQuality,
    PredictionStatus,
    VesselObservation,
)
from latch.synthetic import (
    DifficultyThresholds,
    ImpactBand,
    ProcessAssumptions,
    ProcessScenario,
    ReferenceArrivalGapBand,
    SyntheticBenchmarkConfig,
    TOPOLOGY_VERSION,
    TransferMode,
    approved_assumption_register,
    canonical_digest,
    generate_synthetic_benchmark,
    to_primitive,
    BenchmarkQuota,
)
from latch.models import Terminal


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "fixtures" / "synthetic"
TINY_DATASET_DIGEST = canonical_digest("tiny PR3 causal update contract fixture")


def tiny_fixture_updates() -> tuple[CausalArrivalUpdate, ...]:
    arrivals = (
        datetime(2023, 10, 1, 0, tzinfo=UTC),
        datetime(2023, 10, 1, 6, tzinfo=UTC),
        datetime(2023, 10, 1, 9, tzinfo=UTC),
        datetime(2023, 10, 1, 14, tzinfo=UTC),
        datetime(2023, 10, 1, 20, tzinfo=UTC),
        datetime(2023, 10, 2, 2, tzinfo=UTC),
    )
    updates: list[CausalArrivalUpdate] = []
    for index, arrival in enumerate(arrivals, start=1):
        observed_at = arrival - timedelta(hours=1)
        observation = VesselObservation(
            vessel_id=f"fixture-vessel-{index}",
            observed_at=observed_at,
            source_row_number=100 + index,
            latitude=1.20 + index / 1_000,
            longitude=103.70 + index / 1_000,
            speed_over_ground_knots=10.0,
            course_over_ground_degrees=90.0,
            true_heading_degrees=90.0,
            rate_of_turn=0.0,
            navigation_status=0,
            vessel_type=70,
            ais_reported_eta=None,
            quality_flags=(),
        )
        updates.append(
            CausalArrivalUpdate(
                call_id=f"fixture-call-{index}",
                vessel_id=observation.vessel_id,
                observed_at=observed_at,
                prediction_status=PredictionStatus.AVAILABLE,
                reference_arrival=arrival,
                predicted_arrival=arrival,
                data_quality=DataQuality.GOOD,
                quality_reason_codes=(),
                source_type="real_ais_observation",
                boundary_version="exploratory-circle-v1",
                source_observation=observation,
            )
        )
        # A later prediction is deliberately present to prove it cannot enter
        # candidate construction or identity.
        later_observation = replace(
            observation,
            observed_at=observed_at + timedelta(minutes=20),
            source_row_number=200 + index,
        )
        updates.append(
            replace(
                updates[-1],
                observed_at=later_observation.observed_at,
                predicted_arrival=arrival + timedelta(minutes=15),
                source_observation=later_observation,
            )
        )
    return tuple(updates)


def tiny_fixture_config() -> SyntheticBenchmarkConfig:
    return SyntheticBenchmarkConfig(
        seed="latch-pr3-tiny-fixture-seed",
        topology_version=TOPOLOGY_VERSION,
        dataset_sha256=TINY_DATASET_DIGEST,
        quotas=(
            BenchmarkQuota(
                origin_terminal=Terminal.TUAS,
                destination_terminal=Terminal.TUAS,
                transfer_mode=TransferMode.NONE,
                impact_band=ImpactBand.SMALL,
                count=1,
                reference_arrival_gap_band=ReferenceArrivalGapBand(
                    minimum_gap=timedelta(hours=6),
                    maximum_gap=timedelta(hours=12),
                ),
            ),
            BenchmarkQuota(
                origin_terminal=Terminal.TUAS,
                destination_terminal=Terminal.PASIR_PANJANG,
                transfer_mode=TransferMode.ROAD,
                impact_band=ImpactBand.MEDIUM,
                count=1,
                reference_arrival_gap_band=ReferenceArrivalGapBand(
                    maximum_gap=timedelta(hours=6),
                ),
                box_count=24,
            ),
            BenchmarkQuota(
                origin_terminal=Terminal.PASIR_PANJANG,
                destination_terminal=Terminal.TUAS,
                transfer_mode=TransferMode.SEA,
                impact_band=ImpactBand.LARGE,
                count=1,
                reference_arrival_gap_band=ReferenceArrivalGapBand(
                    minimum_gap=timedelta(hours=13),
                ),
                box_count=60,
            ),
        ),
        process_assumptions=(
            ProcessAssumptions(
                ProcessScenario.LOW,
                cargo_ready_offset=timedelta(hours=1),
                cargo_cutoff_lead=timedelta(hours=2),
                road_transfer_duration=timedelta(minutes=45),
                sea_transfer_duration=timedelta(minutes=90),
            ),
            ProcessAssumptions(
                ProcessScenario.REFERENCE,
                cargo_ready_offset=timedelta(hours=2),
                cargo_cutoff_lead=timedelta(hours=3),
                road_transfer_duration=timedelta(hours=1),
                sea_transfer_duration=timedelta(hours=2),
            ),
            ProcessAssumptions(
                ProcessScenario.CONSERVATIVE,
                cargo_ready_offset=timedelta(hours=3),
                cargo_cutoff_lead=timedelta(hours=4),
                road_transfer_duration=timedelta(hours=2),
                sea_transfer_duration=timedelta(hours=3),
            ),
        ),
        difficulty_thresholds=DifficultyThresholds(
            tight_upper_bound=timedelta(hours=2),
            standard_upper_bound=timedelta(hours=6),
        ),
        evidence=approved_assumption_register(),
    )


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(to_primitive(value), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    config = tiny_fixture_config()
    benchmark = generate_synthetic_benchmark(tiny_fixture_updates(), config)
    write_json(args.output_dir / "quotas.json", config.quotas)
    write_json(args.output_dir / "assumptions.json", config.evidence)
    write_json(args.output_dir / "benchmark.json", benchmark.connections)
    write_json(args.output_dir / "manifest.json", benchmark.manifest)


if __name__ == "__main__":
    main()
