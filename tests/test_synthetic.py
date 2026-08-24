from __future__ import annotations

import csv
import json
import sys
from dataclasses import FrozenInstanceError, fields, replace
from datetime import timedelta

import pytest

from latch.models import Terminal, TerminalResolution
from latch.replay import (
    ArrivalBoundary,
    PredictionStatus,
    ReplayConfig,
    iter_retrospectively_segmented_arrival_updates,
)
from latch.synthetic import (
    AssumptionBasis,
    BenchmarkQuota,
    DifficultyBand,
    DifficultyThresholds,
    ImpactBand,
    ImpossibleQuotaError,
    MPA_PSA_AIGF_CLARIFICATIONS,
    MPA_PSA_AIGF_EOI,
    ProcessAssumptions,
    ProcessScenario,
    ReferenceArrivalGapBand,
    SMDG_TCL_V20260609,
    SyntheticCallCandidate,
    TransferMode,
    UCIDAssignment,
    UCIDConnectionIdentity,
    UNECE_TRANSSHIPMENT_WHITE_PAPER,
    ValueOrigin,
    generate_synthetic_benchmark,
    generate_synthetic_benchmark_from_csv,
    make_ucid_identity,
    project_first_available_candidates,
    to_primitive,
)
from scripts.make_synthetic_benchmark import (
    DEFAULT_OUTPUT,
    main as make_fixture_main,
    tiny_fixture_config,
    tiny_fixture_updates,
)


EXPECTED_PUBLIC_EVIDENCE_FIELDS = frozenset(
    {
        "ais_source_fields",
        "first_available_reference_arrival",
        "reference_arrival_window",
        "reference_arrival_gap",
        "reference_arrival_gap_band",
        "candidate_id",
        "source_call_lineage",
        "vessel_lineage",
        "terminal_identity_tuas",
        "terminal_identity_pasir_panjang",
        "terminal_cluster_context",
        "terminal_assignment",
        "candidate_pairing",
        "topology_version_and_sequence",
        "transfer_mode_catalog",
        "transfer_mode_assignment",
        "process_scenario_configuration",
        "cargo_ready_offset",
        "cargo_ready_at",
        "cargo_cutoff_lead",
        "transfer_duration",
        "planned_cutoff",
        "planning_margin",
        "impact_band",
        "box_count",
        "difficulty_band",
        "ucid_identity",
        "public_sea_transit_reference",
    }
)


def identities(benchmark):
    return tuple(connection.identity for connection in benchmark.connections)


def test_canonical_mapping_rejects_non_string_keys_without_coercion():
    with pytest.raises(
        TypeError, match="canonical mapping keys must be strings; got int"
    ):
        to_primitive({1: "integer", "1": "string"})


def test_canonicalization_accepts_dataclass_instances_but_rejects_classes():
    candidate = SyntheticCallCandidate(
        reference_observed_at=tiny_fixture_updates()[0].observed_at,
        reference_arrival=tiny_fixture_updates()[0].reference_arrival,
        source_row_number=tiny_fixture_updates()[0].source_observation.source_row_number,
        boundary_version=tiny_fixture_updates()[0].boundary_version,
        source_type=tiny_fixture_updates()[0].source_type,
    )

    assert to_primitive(candidate)["source_row_number"] == candidate.source_row_number
    with pytest.raises(
        TypeError, match="dataclass classes are not supported canonical values"
    ):
        to_primitive(SyntheticCallCandidate)


def test_same_input_config_and_seed_are_deterministic():
    updates = tiny_fixture_updates()
    config = tiny_fixture_config()

    assert generate_synthetic_benchmark(updates, config) == generate_synthetic_benchmark(
        updates, config
    )


def test_input_permutation_does_not_change_output():
    updates = tiny_fixture_updates()
    shuffled = tuple(reversed(updates[::2])) + tuple(reversed(updates[1::2]))
    config = tiny_fixture_config()

    assert generate_synthetic_benchmark(updates, config) == generate_synthetic_benchmark(
        shuffled, config
    )


def test_first_available_is_projected_and_later_predictions_are_discarded():
    updates = list(tiny_fixture_updates())
    first = updates[0]
    later = updates[1]
    assert first.prediction_status is PredictionStatus.AVAILABLE
    assert later.prediction_status is PredictionStatus.AVAILABLE

    candidates = project_first_available_candidates(updates)
    first_candidate = next(
        item for item in candidates if item.reference_observed_at == first.observed_at
    )
    assert first_candidate.reference_arrival == first.predicted_arrival
    assert first_candidate.reference_observed_at == first.observed_at
    assert not hasattr(first_candidate, "call_id")
    assert not hasattr(first_candidate, "vessel_id")
    assert not hasattr(first_candidate, "derived_geofence_arrival")
    assert not hasattr(first_candidate, "benchmark_eligible")

    updates[1] = replace(
        later,
        predicted_arrival=later.predicted_arrival + timedelta(days=30),
    )
    before = generate_synthetic_benchmark(tiny_fixture_updates(), tiny_fixture_config())
    after = generate_synthetic_benchmark(updates, tiny_fixture_config())
    assert before == after


def test_pr2_source_call_id_changes_do_not_change_graph():
    updates = tiny_fixture_updates()
    changed = tuple(replace(update, call_id=f"changed-{update.call_id}") for update in updates)

    before = generate_synthetic_benchmark(updates, tiny_fixture_config())
    after = generate_synthetic_benchmark(changed, tiny_fixture_config())
    assert identities(before) == identities(after)
    assert before.manifest.graph_digest == after.manifest.graph_digest
    assert before.manifest.input_digest == after.manifest.input_digest
    assert before.connections[0].assignment.inbound_source_call_id != (
        after.connections[0].assignment.inbound_source_call_id
    )


def test_final_crossing_changes_do_not_change_graph(tmp_path):
    fieldnames = [
        "UserID",
        "timestamp",
        "Latitude",
        "Longitude",
        "speed",
        "Cog",
        "TrueHeading",
        "RateOfTurn",
        "NavigationalStatus",
        "ShipType",
        "EtaMonth",
        "EtaDay",
        "EtaHour",
        "EtaMinute",
    ]

    def write_source(name, crossing_time):
        path = tmp_path / name
        rows = (
            {
                "UserID": "crossing-vessel",
                "timestamp": "2023-01-01 00:00:00",
                "Latitude": "0",
                "Longitude": "0.3",
                "speed": "12",
                "Cog": "90",
                "TrueHeading": "90",
                "RateOfTurn": "0",
                "NavigationalStatus": "0",
                "ShipType": "70",
                "EtaMonth": "1",
                "EtaDay": "2",
                "EtaHour": "3",
                "EtaMinute": "4",
            },
            {
                "UserID": "crossing-vessel",
                "timestamp": crossing_time,
                "Latitude": "0",
                "Longitude": "0",
                "speed": "8",
                "Cog": "90",
                "TrueHeading": "90",
                "RateOfTurn": "0",
                "NavigationalStatus": "0",
                "ShipType": "70",
                "EtaMonth": "1",
                "EtaDay": "2",
                "EtaHour": "3",
                "EtaMinute": "4",
            },
        )
        with path.open("w", encoding="ascii", newline="") as target:
            writer = csv.DictWriter(target, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        return path

    replay_config = ReplayConfig(
        boundary=ArrivalBoundary(0, 0, 10),
        minimum_track_observations=1,
        minimum_pre_arrival_observations=1,
    )
    updates_a = tuple(
        iter_retrospectively_segmented_arrival_updates(
            write_source("early-crossing.csv", "2023-01-01 01:00:00"),
            replay_config,
        )
    )
    updates_b = tuple(
        iter_retrospectively_segmented_arrival_updates(
            write_source("late-crossing.csv", "2023-01-01 02:00:00"),
            replay_config,
        )
    )
    assert updates_a[0].call_id != updates_b[0].call_id
    assert updates_a[0].reference_arrival == updates_b[0].reference_arrival

    before = generate_synthetic_benchmark(
        tiny_fixture_updates() + updates_a, tiny_fixture_config()
    )
    after = generate_synthetic_benchmark(
        tiny_fixture_updates() + updates_b, tiny_fixture_config()
    )
    assert identities(before) == identities(after)
    assert before.manifest.graph_digest == after.manifest.graph_digest


def test_anonymised_vessel_id_changes_do_not_change_ranking_or_ucid():
    updates = tiny_fixture_updates()
    changed = tuple(
        replace(
            update,
            vessel_id=f"renamed-{update.vessel_id}",
            source_observation=replace(
                update.source_observation,
                vessel_id=f"renamed-{update.source_observation.vessel_id}",
            ),
        )
        for update in updates
    )

    before = generate_synthetic_benchmark(updates, tiny_fixture_config())
    after = generate_synthetic_benchmark(changed, tiny_fixture_config())
    assert identities(before) == identities(after)
    assert before.manifest.graph_digest == after.manifest.graph_digest
    assert before.manifest.input_digest == after.manifest.input_digest


def test_same_vessel_cannot_connect_to_itself():
    updates = tuple(
        replace(
            update,
            vessel_id="one-vessel",
            source_observation=replace(update.source_observation, vessel_id="one-vessel"),
        )
        for update in tiny_fixture_updates()
    )

    with pytest.raises(ImpossibleQuotaError, match="impossible quota cell"):
        generate_synthetic_benchmark(updates, tiny_fixture_config())


def test_same_terminal_uses_none_and_zero_transfer_duration():
    benchmark = generate_synthetic_benchmark(tiny_fixture_updates(), tiny_fixture_config())
    same_terminal = next(
        connection
        for connection in benchmark.connections
        if connection.origin.terminal == connection.destination.terminal
    )

    assert same_terminal.origin.terminal_resolution is TerminalResolution.SIMULATED
    assert all(
        projection.transfer_mode is TransferMode.NONE
        and projection.transfer_duration == timedelta(0)
        for projection in same_terminal.process_projections
    )


def test_inter_terminal_connections_use_configured_road_or_sea_duration():
    config = tiny_fixture_config()
    benchmark = generate_synthetic_benchmark(tiny_fixture_updates(), config)
    assumptions = {item.scenario: item for item in config.process_assumptions}

    for connection in benchmark.connections:
        if connection.origin.terminal == connection.destination.terminal:
            continue
        for projection in connection.process_projections:
            assert projection.transfer_mode in (TransferMode.ROAD, TransferMode.SEA)
            assert projection.transfer_duration == assumptions[
                projection.scenario
            ].transfer_duration(projection.transfer_mode)
    sea_reference = next(
        connection.reference_projection
        for connection in benchmark.connections
        if connection.reference_projection.transfer_mode is TransferMode.SEA
    )
    assert sea_reference.transfer_duration == timedelta(hours=2)
    assert sea_reference.transfer_duration != timedelta(hours=4)


def test_ucid_identity_is_independent_of_replacement_assignment():
    connection = generate_synthetic_benchmark(
        tiny_fixture_updates(), tiny_fixture_config()
    ).connections[0]
    original = connection.assignment
    independent_identity = make_ucid_identity(
        origin_terminal=connection.identity.origin_terminal,
        destination_terminal=connection.identity.destination_terminal,
        reference_arrival_window=connection.identity.reference_arrival_window,
        topology_version=connection.identity.topology_version,
        sequence=connection.identity.sequence,
    )
    replacement_inbound = replace(
        original.inbound_candidate,
        source_row_number=original.inbound_candidate.source_row_number + 10_000,
    )
    replacement_outbound = replace(
        original.outbound_candidate,
        source_row_number=original.outbound_candidate.source_row_number + 20_000,
    )
    reassigned = UCIDAssignment(
        identity=independent_identity,
        inbound_candidate=replacement_inbound,
        outbound_candidate=replacement_outbound,
        inbound_candidate_id="candidate_reassigned_inbound",
        outbound_candidate_id="candidate_reassigned_outbound",
        inbound_source_call_id="different-inbound-call",
        outbound_source_call_id="different-outbound-call",
        inbound_vessel_id="different-inbound-vessel",
        outbound_vessel_id="different-outbound-vessel",
    )

    assert reassigned != original
    assert reassigned.identity is not connection.identity
    assert reassigned.identity == connection.identity
    assert reassigned.identity.ucid == connection.identity.ucid


def test_end_to_end_process_sensitivity_changes_do_not_change_topology_or_ucid():
    config = tiny_fixture_config()
    changed_assumptions = tuple(
        ProcessAssumptions(
            scenario,
            cargo_ready_offset=timedelta(hours=10 + index),
            cargo_cutoff_lead=timedelta(hours=11 + index),
            road_transfer_duration=timedelta(hours=12 + index),
            sea_transfer_duration=timedelta(hours=13 + index),
        )
        for index, scenario in enumerate(ProcessScenario)
    )
    changed_config = replace(
        config,
        process_assumptions=changed_assumptions,
    )
    before = generate_synthetic_benchmark(tiny_fixture_updates(), config)
    after = generate_synthetic_benchmark(tiny_fixture_updates(), changed_config)

    before_pairs = tuple(
        (
            item.assignment.inbound_candidate_id,
            item.assignment.outbound_candidate_id,
        )
        for item in before.connections
    )
    after_pairs = tuple(
        (
            item.assignment.inbound_candidate_id,
            item.assignment.outbound_candidate_id,
        )
        for item in after.connections
    )
    assert before_pairs == after_pairs
    assert identities(before) == identities(after)
    assert before.manifest.graph_digest == after.manifest.graph_digest
    assert tuple(item.process_projections for item in before.connections) != tuple(
        item.process_projections for item in after.connections
    )
    assert any(
        before_projection.difficulty_band is not after_projection.difficulty_band
        for before_connection, after_connection in zip(
            before.connections, after.connections, strict=True
        )
        for before_projection, after_projection in zip(
            before_connection.process_projections,
            after_connection.process_projections,
            strict=True,
        )
    )
    identity_fields = {field.name for field in fields(UCIDConnectionIdentity)}
    assert not {
        "process_scenario",
        "cargo_ready_offset",
        "cargo_ready_at",
        "cargo_cutoff_lead",
        "planned_cutoff",
        "transfer_duration",
        "impact_band",
        "difficulty_band",
    }.intersection(identity_fields)


def test_changing_impact_band_leaves_ucid_unchanged():
    config = tiny_fixture_config()
    changed_first = replace(config.quotas[0], impact_band=ImpactBand.LARGE)
    changed = replace(config, quotas=(changed_first,) + config.quotas[1:])

    before = generate_synthetic_benchmark(tiny_fixture_updates(), config)
    after = generate_synthetic_benchmark(tiny_fixture_updates(), changed)
    assert identities(before) == identities(after)
    assert before.connections[0].impact_band is ImpactBand.SMALL
    assert after.connections[0].impact_band is ImpactBand.LARGE


def test_every_synthetic_assumption_has_explicit_provenance():
    config = tiny_fixture_config()
    register = config.evidence
    by_field = {item.field_name: item for item in register}

    assert set(by_field) == EXPECTED_PUBLIC_EVIDENCE_FIELDS
    for evidence in register:
        if evidence.value_origin is ValueOrigin.SYNTHETIC:
            assert evidence.assumption_basis is AssumptionBasis.EXPERIMENTAL
            assert evidence.source_reference
    assert by_field["ais_source_fields"].assumption_basis is AssumptionBasis.NOT_APPLICABLE
    assert by_field["first_available_reference_arrival"].value_origin is ValueOrigin.DERIVED
    assert (
        by_field["first_available_reference_arrival"].assumption_basis
        is AssumptionBasis.NOT_APPLICABLE
    )
    assert by_field["planned_cutoff"].value_origin is ValueOrigin.DERIVED
    assert by_field["planned_cutoff"].assumption_basis is AssumptionBasis.EXPERIMENTAL
    assert by_field["cargo_ready_at"].value_origin is ValueOrigin.DERIVED
    assert by_field["cargo_ready_at"].assumption_basis is AssumptionBasis.EXPERIMENTAL
    assert by_field["planning_margin"].value_origin is ValueOrigin.DERIVED
    assert by_field["planning_margin"].assumption_basis is AssumptionBasis.EXPERIMENTAL
    assert (
        by_field["process_scenario_configuration"].value_origin
        is ValueOrigin.SYNTHETIC
    )
    assert (
        by_field["process_scenario_configuration"].assumption_basis
        is AssumptionBasis.EXPERIMENTAL
    )

    approved_public_sources = {
        UNECE_TRANSSHIPMENT_WHITE_PAPER,
        MPA_PSA_AIGF_EOI,
        MPA_PSA_AIGF_CLARIFICATIONS,
        SMDG_TCL_V20260609,
    }
    public_sources = {
        item.source_reference
        for item in register
        if item.assumption_basis is AssumptionBasis.PUBLIC_ANCHOR
    }
    assert public_sources <= approved_public_sources
    benchmark = generate_synthetic_benchmark(tiny_fixture_updates(), config)
    assert all(
        {item.field_name for item in connection.evidence}
        == EXPECTED_PUBLIC_EVIDENCE_FIELDS
        for connection in benchmark.connections
    )


def test_quota_cells_are_explicit_and_exact_without_cartesian_requirement():
    benchmark = generate_synthetic_benchmark(tiny_fixture_updates(), tiny_fixture_config())

    assert len(benchmark.connections) == 3
    assert benchmark.manifest.requested_connection_count == 3
    assert benchmark.manifest.generated_connection_count == 3
    assert [connection.impact_band for connection in benchmark.connections] == [
        ImpactBand.SMALL,
        ImpactBand.MEDIUM,
        ImpactBand.LARGE,
    ]
    assert [connection.box_count for connection in benchmark.connections] == [None, 24, 60]
    assert all(
        quota.reference_arrival_gap_band is not None
        for quota in tiny_fixture_config().quotas
    )


def test_global_allocation_succeeds_when_rank_first_greedy_would_fail():
    base = tiny_fixture_config()
    broad = BenchmarkQuota(
        origin_terminal=Terminal.TUAS,
        destination_terminal=Terminal.TUAS,
        transfer_mode=TransferMode.NONE,
        impact_band=ImpactBand.SMALL,
        count=1,
    )
    narrow = BenchmarkQuota(
        origin_terminal=Terminal.TUAS,
        destination_terminal=Terminal.PASIR_PANJANG,
        transfer_mode=TransferMode.ROAD,
        impact_band=ImpactBand.MEDIUM,
        count=1,
        reference_arrival_gap_band=ReferenceArrivalGapBand(
            maximum_gap=timedelta(hours=4)
        ),
    )
    broad_only = generate_synthetic_benchmark(
        tiny_fixture_updates(), replace(base, seed="overlap-4", quotas=(broad,))
    )
    narrow_only = generate_synthetic_benchmark(
        tiny_fixture_updates(), replace(base, seed="overlap-4", quotas=(narrow,))
    )
    greedy_pair = (
        broad_only.connections[0].assignment.inbound_candidate_id,
        broad_only.connections[0].assignment.outbound_candidate_id,
    )
    constrained_pair = (
        narrow_only.connections[0].assignment.inbound_candidate_id,
        narrow_only.connections[0].assignment.outbound_candidate_id,
    )
    assert greedy_pair == constrained_pair

    combined = generate_synthetic_benchmark(
        tiny_fixture_updates(),
        replace(base, seed="overlap-4", quotas=(broad, narrow)),
    )
    combined_pairs = tuple(
        (
            connection.assignment.inbound_candidate_id,
            connection.assignment.outbound_candidate_id,
        )
        for connection in combined.connections
    )
    assert len(set(combined_pairs)) == 2
    assert combined_pairs[1] == constrained_pair
    assert combined_pairs[0] != constrained_pair


def test_difficulty_is_projection_metadata_with_explicit_infeasible_band():
    thresholds = DifficultyThresholds(
        tight_upper_bound=timedelta(hours=2),
        standard_upper_bound=timedelta(hours=6),
    )

    assert thresholds.classify(timedelta(microseconds=-1)) is DifficultyBand.INFEASIBLE
    assert thresholds.classify(timedelta(0)) is DifficultyBand.TIGHT
    assert thresholds.classify(timedelta(hours=2)) is DifficultyBand.STANDARD
    assert thresholds.classify(timedelta(hours=6)) is DifficultyBand.COMFORTABLE


def test_impossible_quotas_fail_explicitly_without_partial_output():
    config = tiny_fixture_config()
    impossible = replace(config.quotas[0], count=10_000)

    with pytest.raises(ImpossibleQuotaError, match="requested=10000"):
        generate_synthetic_benchmark(
            tiny_fixture_updates(), replace(config, quotas=(impossible,))
        )


def test_invalid_topology_mode_combinations_are_rejected():
    with pytest.raises(ValueError, match="same-terminal"):
        BenchmarkQuota(
            origin_terminal=Terminal.TUAS,
            destination_terminal=Terminal.TUAS,
            transfer_mode=TransferMode.ROAD,
            impact_band=ImpactBand.SMALL,
            count=1,
        )
    with pytest.raises(ValueError, match="inter-terminal"):
        BenchmarkQuota(
            origin_terminal=Terminal.TUAS,
            destination_terminal=Terminal.PASIR_PANJANG,
            transfer_mode=TransferMode.NONE,
            impact_band=ImpactBand.SMALL,
            count=1,
        )


def test_inputs_and_models_remain_immutable():
    updates = list(tiny_fixture_updates())
    snapshot = tuple(updates)
    config = tiny_fixture_config()
    benchmark = generate_synthetic_benchmark(updates, config)

    assert tuple(updates) == snapshot
    with pytest.raises(FrozenInstanceError):
        benchmark.connections[0].impact_band = ImpactBand.LARGE
    with pytest.raises(FrozenInstanceError):
        config.seed = "different"


def test_candidate_digest_and_order_exclude_vessel_and_call_ids():
    candidate_fields = {field.name for field in fields(SyntheticCallCandidate)}
    assignment_fields = {field.name for field in fields(UCIDAssignment)}
    assert "vessel_id" not in candidate_fields
    assert "call_id" not in candidate_fields
    assert {
        "inbound_candidate_id",
        "outbound_candidate_id",
        "inbound_source_call_id",
        "outbound_source_call_id",
        "inbound_vessel_id",
        "outbound_vessel_id",
    } <= assignment_fields


def test_csv_adapter_uses_unfiltered_retrospectively_segmented_source(monkeypatch):
    seen = {}

    def source(path):
        seen["path"] = path
        return iter(tiny_fixture_updates())

    monkeypatch.setattr(
        "latch.replay.iter_retrospectively_segmented_arrival_updates", source
    )
    benchmark = generate_synthetic_benchmark_from_csv(
        "historical.csv", tiny_fixture_config()
    )

    assert seen == {"path": "historical.csv"}
    assert len(benchmark.connections) == 3


def test_fixture_cli_rejects_historical_csv(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["make_synthetic_benchmark.py", "--csv", "historical.csv"],
    )

    with pytest.raises(SystemExit) as error:
        make_fixture_main()

    assert error.value.code == 2


def test_committed_tiny_fixture_matches_generator():
    benchmark = generate_synthetic_benchmark(tiny_fixture_updates(), tiny_fixture_config())
    expected_files = {
        "quotas.json": tiny_fixture_config().quotas,
        "assumptions.json": tiny_fixture_config().evidence,
        "benchmark.json": benchmark.connections,
        "manifest.json": benchmark.manifest,
    }
    for name, value in expected_files.items():
        assert json.loads((DEFAULT_OUTPUT / name).read_text(encoding="utf-8")) == (
            to_primitive(value)
        )
