from dataclasses import replace
from datetime import timedelta

import pytest

import latch.historical_eval as historical_eval
from latch.historical_eval import (
    CausalReplayCall,
    HistoricalPopulationConfig,
    ReplayCursor,
    build_call_population,
    connection_activation,
    historical_synthetic_config,
    records_through,
    replay_watcher_assessments,
    update_cursor,
)
from latch.replay import DataQuality, DerivedArrivalEvent
from latch.synthetic import generate_synthetic_benchmark
from latch.watcher import AssessmentStatus, WatcherConfig
from scripts.make_synthetic_benchmark import (
    tiny_fixture_config,
    tiny_fixture_updates,
)


def accepted_calls(updates=None):
    updates = tiny_fixture_updates() if updates is None else tuple(updates)
    by_call = {}
    for update in updates:
        by_call.setdefault(update.call_id, []).append(update)
    calls = []
    for call_id, call_updates in by_call.items():
        ordered = tuple(sorted(call_updates, key=update_cursor))
        first = ordered[0]
        crossing = max(update.observed_at for update in ordered) + timedelta(hours=2)
        calls.append(
            DerivedArrivalEvent(
                vessel_id=first.vessel_id,
                call_id=call_id,
                derived_geofence_arrival=crossing,
                first_eligible_pre_event_observation=first.source_observation,
                eligible_pre_event_observations=len(ordered),
                pre_event_lookback=crossing - first.observed_at,
                benchmark_eligible=True,
                exclusion_reasons=(),
                quality_reason_codes=(),
                data_quality=DataQuality.GOOD,
                boundary_version=first.boundary_version,
                crossing_source_row_number=max(
                    update.source_observation.source_row_number
                    for update in ordered
                )
                + 1_000,
                arrival_updates=ordered,
                eta_revisions=(),
            )
        )
    return tuple(calls)


def evaluation(calls=None):
    calls = accepted_calls() if calls is None else tuple(calls)
    population = build_call_population(
        calls, HistoricalPopulationConfig(source_call_limit=len(calls))
    )
    config = historical_synthetic_config(
        dataset_sha256="historical-eval-test-dataset",
        connections_per_quota=1,
    )
    updates = tuple(
        update for call in population.replay_calls for update in call.updates
    )
    benchmark = generate_synthetic_benchmark(updates, config)
    watcher = WatcherConfig(
        warning_margin=timedelta(hours=2),
        reference_delay_threshold=timedelta(minutes=15),
    )
    return replay_watcher_assessments(population, benchmark, watcher)


def live_values(record):
    """Assessment values excluding manifests that legitimately identify inputs."""

    return (
        record.ucid,
        record.trigger_cursor,
        record.status,
        record.severity,
        record.current_plan_slack_h,
        record.no_itt_slack_h,
        record.reason_codes,
        record.inbound_prediction_observed_at,
        record.outbound_prediction_observed_at,
        record.inbound_predicted_arrival,
        record.outbound_predicted_arrival,
        record.baseline_alert,
        record.baseline_delay_h,
    )


@pytest.mark.parametrize("leg", ["inbound", "outbound"])
def test_future_leg_update_cannot_alter_an_earlier_assessment(leg):
    calls = list(accepted_calls())
    initial = evaluation(calls)
    connection = initial.benchmark.connections[0]
    call_id = getattr(connection.assignment, f"{leg}_source_call_id")
    event_index = next(
        index for index, event in enumerate(calls) if event.call_id == call_id
    )
    target = calls[event_index].arrival_updates[-1]
    last_cursor = max(record.trigger_cursor for record in initial.records)
    future_observation = replace(
        target.source_observation,
        observed_at=last_cursor.observed_at + timedelta(days=1),
        source_row_number=last_cursor.source_row_number + 100_000,
    )
    future = replace(
        target,
        observed_at=future_observation.observed_at,
        predicted_arrival=target.predicted_arrival + timedelta(days=90),
        source_observation=future_observation,
    )
    calls[event_index] = replace(
        calls[event_index],
        derived_geofence_arrival=future.observed_at + timedelta(hours=1),
        arrival_updates=(*calls[event_index].arrival_updates, future),
    )

    with_future = evaluation(calls)
    earlier = records_through(with_future.records, last_cursor)
    assert tuple(map(live_values, earlier)) == tuple(map(live_values, initial.records))
    assert all(
        record.inbound_predicted_arrival != future.predicted_arrival
        if leg == "inbound"
        else record.outbound_predicted_arrival != future.predicted_arrival
        for record in earlier
        if record.ucid == connection.identity.ucid
    )


def test_connection_is_not_assessed_before_both_candidates_are_knowable():
    result = evaluation()
    by_ucid = {activation.ucid: activation for activation in result.activations}
    for record in result.records:
        assert record.trigger_cursor >= by_ucid[record.ucid].active_cursor
    for connection in result.benchmark.connections:
        activation = connection_activation(connection)
        first = next(
            record
            for record in result.records
            if record.ucid == connection.identity.ucid
        )
        assert first.trigger_cursor == activation.active_cursor
        assert first.status == AssessmentStatus.AVAILABLE.value


def test_connection_legs_join_by_source_call_id_not_vessel_id():
    result = evaluation()
    connection = result.benchmark.connections[0]
    assignment = connection.assignment
    record = next(
        item for item in result.records if item.ucid == connection.identity.ucid
    )
    inbound_updates = {
        update.observed_at
        for update in tiny_fixture_updates()
        if update.call_id == assignment.inbound_source_call_id
    }
    outbound_updates = {
        update.observed_at
        for update in tiny_fixture_updates()
        if update.call_id == assignment.outbound_source_call_id
    }
    assert record.inbound_source_call_id == assignment.inbound_source_call_id
    assert record.outbound_source_call_id == assignment.outbound_source_call_id
    assert record.inbound_prediction_observed_at in inbound_updates
    assert record.outbound_prediction_observed_at in outbound_updates

    # A different call reusing one anonymised vessel ID must not trigger the
    # graph connection.  Only assignment source-call lineage is indexed.
    source_call = next(
        call
        for call in result.population.replay_calls
        if call.call_id == assignment.inbound_source_call_id
    )
    source = source_call.updates[-1]
    decoy_observation = replace(
        source.source_observation,
        observed_at=max(record.assessed_at for record in result.records)
        + timedelta(hours=1),
        source_row_number=999_999,
    )
    decoy = replace(
        source,
        call_id="decoy-call-with-same-vessel",
        observed_at=decoy_observation.observed_at,
        source_observation=decoy_observation,
    )
    decoy_population = replace(
        result.population,
        replay_calls=(
            *result.population.replay_calls,
            CausalReplayCall(decoy.call_id, decoy.vessel_id, (decoy,)),
        ),
    )
    rerun = replay_watcher_assessments(
        decoy_population,
        result.benchmark,
        WatcherConfig(timedelta(hours=2), timedelta(minutes=15)),
    )
    assert len(rerun.records) == len(result.records)
    assert all(item.trigger_source_call_id != decoy.call_id for item in rerun.records)


@pytest.mark.parametrize("change", ["crossing", "eligibility"])
def test_retrospective_metadata_cannot_influence_live_replay(change):
    calls = accepted_calls()
    if change == "crossing":
        changed = tuple(
            replace(
                event,
                derived_geofence_arrival=event.derived_geofence_arrival
                + timedelta(days=90),
                crossing_source_row_number=(
                    event.crossing_source_row_number + 1_000_000
                ),
            )
            for event in calls
        )
    else:
        changed = tuple(
            replace(
                event,
                benchmark_eligible=False,
                exclusion_reasons=("retrospective_only",),
                quality_reason_codes=("completed_call_only",),
                data_quality=DataQuality.EXCLUDED,
            )
            for event in calls
        )
    before = evaluation(calls)
    after = evaluation(changed)
    assert before.population.population_digest == after.population.population_digest
    assert before.benchmark == after.benchmark
    assert before.records == after.records


def test_input_permutation_has_the_same_deterministic_replay_result():
    calls = accepted_calls()
    permuted = tuple(
        replace(event, arrival_updates=tuple(reversed(event.arrival_updates)))
        for event in reversed(calls)
    )
    before = evaluation(calls)
    after = evaluation(permuted)
    assert before.population.selected_call_ids == after.population.selected_call_ids
    assert before.population.population_digest == after.population.population_digest
    assert before.benchmark == after.benchmark
    assert before.records == after.records
    assert before.diagnostics == after.diagnostics


def test_same_timestamp_source_row_tie_break_controls_activation_and_replay():
    calls = list(accepted_calls())
    first = calls[0].arrival_updates[0]
    second = calls[1].arrival_updates[0]
    tied_second_observation = replace(
        second.source_observation,
        observed_at=first.observed_at,
        source_row_number=first.source_observation.source_row_number + 1,
    )
    tied_second = replace(
        second,
        observed_at=first.observed_at,
        source_observation=tied_second_observation,
    )
    calls[1] = replace(
        calls[1],
        arrival_updates=(tied_second, *calls[1].arrival_updates[1:]),
    )
    result = evaluation(calls)
    assert tuple(record.trigger_cursor for record in result.records) == tuple(
        sorted(record.trigger_cursor for record in result.records)
    )
    for connection in result.benchmark.connections:
        activation = connection_activation(connection)
        first_record = next(
            record
            for record in result.records
            if record.ucid == connection.identity.ucid
        )
        assert first_record.trigger_cursor == activation.active_cursor


def test_repeated_ais_updates_do_not_create_extra_benchmark_connections():
    result = evaluation()
    assert all(len(call.updates) == 2 for call in result.population.replay_calls)
    assert result.benchmark.manifest.generated_connection_count == 4
    assert len(
        {connection.identity.ucid for connection in result.benchmark.connections}
    ) == 4
    assert len(
        {
            (
                connection.assignment.inbound_source_call_id,
                connection.assignment.outbound_source_call_id,
            )
            for connection in result.benchmark.connections
        }
    ) == 4


def test_watcher_and_baseline_retain_the_same_selected_inbound_prediction():
    result = evaluation()
    for record in result.records:
        assert record.baseline_available
        assert (
            record.baseline_prediction_observed_at
            == record.inbound_prediction_observed_at
        )


def test_records_through_never_uses_a_future_assessment():
    result = evaluation()
    cursors = sorted({record.trigger_cursor for record in result.records})
    cutoff = cursors[len(cursors) // 2]
    earlier = records_through(result.records, cutoff)
    assert earlier
    assert all(record.trigger_cursor <= cutoff for record in earlier)
    assert all(
        record not in earlier
        for record in result.records
        if record.trigger_cursor > cutoff
    )


def test_final_events_never_enter_assess_connection(monkeypatch):
    original = historical_eval.assess_connection
    seen = []

    def spy(connection, updates, **kwargs):
        materialized = tuple(updates)
        assert materialized
        assert not any(isinstance(item, DerivedArrivalEvent) for item in materialized)
        seen.extend(materialized)
        return original(connection, materialized, **kwargs)

    monkeypatch.setattr(historical_eval, "assess_connection", spy)
    result = evaluation()
    assert result.records
    assert seen


def test_historical_population_and_quota_are_explicit_and_not_tiny_fixture():
    calls = accepted_calls()
    bounded = build_call_population(
        reversed(calls), HistoricalPopulationConfig(source_call_limit=4)
    )
    historical = historical_synthetic_config(
        dataset_sha256="declared-dataset", connections_per_quota=2
    )
    tiny = tiny_fixture_config()
    assert len(bounded.replay_calls) == 4
    assert bounded.accepted_call_count == 6
    assert sum(quota.count for quota in historical.quotas) == 8
    assert historical.seed != tiny.seed
    assert historical.quotas != tiny.quotas
    with pytest.raises(ValueError, match="safety bound"):
        HistoricalPopulationConfig(source_call_limit=257)


def test_historical_graph_and_ucids_are_deterministic():
    result = evaluation()
    rerun = evaluation(tuple(reversed(accepted_calls())))
    assert (
        result.benchmark.manifest.output_digest
        == rerun.benchmark.manifest.output_digest
    )
    assert tuple(item.identity.ucid for item in result.benchmark.connections) == tuple(
        item.identity.ucid for item in rerun.benchmark.connections
    )


def test_activation_uses_source_row_when_reference_observation_times_tie():
    result = evaluation()
    connection = result.benchmark.connections[0]
    activation = connection_activation(connection)
    assignment = connection.assignment
    expected = max(
        ReplayCursor(
            assignment.inbound_candidate.reference_observed_at,
            assignment.inbound_candidate.source_row_number,
            assignment.inbound_source_call_id,
        ),
        ReplayCursor(
            assignment.outbound_candidate.reference_observed_at,
            assignment.outbound_candidate.source_row_number,
            assignment.outbound_source_call_id,
        ),
    )
    assert activation.active_at == expected.observed_at
    assert activation.active_cursor == expected
