from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
from pathlib import Path

import pytest

from latch.historical_eval import (
    HISTORICAL_REPORT_VERSION,
    ReplayCursor,
    build_historical_benchmark_report,
    build_retrospective_outcomes,
    historical_synthetic_config,
    replay_watcher_assessments,
)
from latch.replay import PredictionStatus
from latch.synthetic import ProcessScenario
from latch.watcher import AssessmentStatus, WatcherConfig
from latch.watcher_refinement_eval import (
    EXPERIMENTAL_WARNING_MARGINS,
    FROZEN_EVALUATION_HORIZONS,
    WATCHER_REFINEMENT_REPORT_VERSION,
    CommonSupportInvariantError,
    MissReason,
    build_alert_churn,
    build_causal_refinement_diagnostic,
    build_refinement_diagnostics,
    build_watcher_refinement_report,
    calculate_connection_alert_churn,
    classify_miss_reason,
    classify_watcher_state,
    join_retrospective_evaluation,
    synthetic_prevention_opportunity,
    validate_refinement_output_path,
    write_watcher_refinement_report,
)
from tests.test_historical_eval import accepted_calls, evaluation


ROOT = Path(__file__).resolve().parent.parent


def reference_result():
    return evaluation()


def scenario_result(result, scenario: ProcessScenario):
    if scenario is ProcessScenario.REFERENCE:
        return result
    return replay_watcher_assessments(
        result.population,
        result.benchmark,
        WatcherConfig(
            warning_margin=timedelta(hours=2),
            reference_delay_threshold=timedelta(minutes=15),
            process_scenario=scenario,
        ),
    )


def outcome_for(result, scenario=ProcessScenario.REFERENCE, index=-1):
    return build_retrospective_outcomes(result, scenario=scenario).outcomes[index]


def causal_after_all_records(result, *, margin=timedelta(hours=2), index=-1):
    outcome = outcome_for(result, index=index)
    timestamp = max(record.assessed_at for record in result.records) + timedelta(hours=1)
    return build_causal_refinement_diagnostic(
        result,
        ucid=outcome.ucid,
        scenario=ProcessScenario.REFERENCE,
        warning_margin=margin,
        evaluation_horizon=timedelta(hours=1),
        evaluation_timestamp=timestamp,
    )


def test_diagnostics_do_not_mutate_pr5_evaluation_records():
    result = reference_result()
    records_before = result.records
    benchmark_before = result.benchmark
    population_before = result.population

    rows = build_refinement_diagnostics(
        result, scenario=ProcessScenario.REFERENCE
    )

    assert len(rows) == 5 * 3 * len(result.benchmark.connections)
    assert result.records == records_before
    assert result.benchmark == benchmark_before
    assert result.population == population_before


def test_retrospective_changes_cannot_alter_causal_diagnostic_values():
    calls = accepted_calls()
    before = evaluation(calls)
    changed = tuple(
        replace(
            call,
            derived_geofence_arrival=call.derived_geofence_arrival
            + timedelta(days=30),
        )
        for call in calls
    )
    after = evaluation(changed)
    ucid = before.benchmark.connections[-1].identity.ucid
    timestamp = max(record.assessed_at for record in before.records) + timedelta(hours=1)

    first = build_causal_refinement_diagnostic(
        before,
        ucid=ucid,
        scenario=ProcessScenario.REFERENCE,
        warning_margin=timedelta(hours=3),
        evaluation_horizon=timedelta(hours=1),
        evaluation_timestamp=timestamp,
    )
    second = build_causal_refinement_diagnostic(
        after,
        ucid=ucid,
        scenario=ProcessScenario.REFERENCE,
        warning_margin=timedelta(hours=3),
        evaluation_horizon=timedelta(hours=1),
        evaluation_timestamp=timestamp,
    )

    assert first == second
    assert outcome_for(before) != outcome_for(after)


def test_missing_support_is_distinct_from_available_safe_policy_miss():
    result = reference_result()
    outcome = outcome_for(result)
    causal = causal_after_all_records(result)
    unavailable = replace(
        causal,
        inbound_causal_support_available=False,
        outbound_causal_support_available=True,
        watcher_assessment_available=False,
        selected_assessment_timestamp=None,
        watcher_state_under_margin=None,
        watcher_alert_under_margin=None,
    )
    policy_safe = replace(
        causal,
        inbound_causal_support_available=True,
        outbound_causal_support_available=True,
        watcher_assessment_available=True,
        current_plan_slack_hours=3.0,
        warning_margin_hours=2.0,
        watcher_state_under_margin="SAFE",
        watcher_alert_under_margin=False,
    )

    assert classify_miss_reason(unavailable, outcome) is MissReason.NO_INBOUND_SUPPORT
    assert (
        classify_miss_reason(policy_safe, outcome)
        is MissReason.POLICY_SAFE_ABOVE_WARNING_MARGIN
    )


def test_future_observation_cannot_change_earlier_horizon_diagnostic():
    result = reference_result()
    outcome = outcome_for(result)
    timestamp = max(record.assessed_at for record in result.records)
    before = build_causal_refinement_diagnostic(
        result,
        ucid=outcome.ucid,
        scenario=ProcessScenario.REFERENCE,
        warning_margin=timedelta(hours=2),
        evaluation_horizon=timedelta(hours=1),
        evaluation_timestamp=timestamp,
    )
    assignment = result.benchmark.connections[-1].assignment
    call_index = next(
        index
        for index, call in enumerate(result.population.replay_calls)
        if call.call_id == assignment.inbound_source_call_id
    )
    call = result.population.replay_calls[call_index]
    source = call.updates[-1]
    future_observation = replace(
        source.source_observation,
        observed_at=timestamp + timedelta(days=1),
        source_row_number=999_999,
    )
    future = replace(
        source,
        observed_at=future_observation.observed_at,
        predicted_arrival=source.predicted_arrival + timedelta(days=90),
        source_observation=future_observation,
    )
    changed_call = replace(call, updates=(*call.updates, future))
    calls = list(result.population.replay_calls)
    calls[call_index] = changed_call
    changed_result = replace(
        result,
        population=replace(result.population, replay_calls=tuple(calls)),
    )

    after = build_causal_refinement_diagnostic(
        changed_result,
        ucid=outcome.ucid,
        scenario=ProcessScenario.REFERENCE,
        warning_margin=timedelta(hours=2),
        evaluation_horizon=timedelta(hours=1),
        evaluation_timestamp=timestamp,
    )
    assert before == after


def test_margin_changes_only_policy_classification_and_alert_history():
    result = reference_result()
    outcome = outcome_for(result, index=1)
    timestamp = max(record.assessed_at for record in result.records) + timedelta(hours=1)
    rows = tuple(
        build_causal_refinement_diagnostic(
            result,
            ucid=outcome.ucid,
            scenario=ProcessScenario.REFERENCE,
            warning_margin=margin,
            evaluation_horizon=timedelta(hours=1),
            evaluation_timestamp=timestamp,
        )
        for margin in EXPERIMENTAL_WARNING_MARGINS
    )
    invariant = lambda row: (
        row.ucid,
        row.scenario,
        row.evaluation_timestamp,
        row.inbound_causal_support_available,
        row.outbound_causal_support_available,
        row.selected_assessment_timestamp,
        row.selected_inbound_prediction_timestamp,
        row.selected_outbound_prediction_timestamp,
        row.current_plan_slack_hours,
        row.no_itt_slack_hours,
        row.baseline_alert,
        row.population_digest,
        row.graph_output_digest,
    )
    assert len({invariant(row) for row in rows}) == 1
    assert [row.watcher_state_under_margin for row in rows] == [
        "SAFE",
        "WATCH",
        "WATCH",
        "WATCH",
        "WATCH",
    ]


def test_report_declares_every_margin_once_in_declaration_order():
    result = reference_result()
    report = build_watcher_refinement_report(
        (result,), dataset_hash="test-dataset"
    )
    assert report.report_version == WATCHER_REFINEMENT_REPORT_VERSION
    assert report.experiment.warning_margin_hours == (0.0, 1.0, 2.0, 3.0, 4.0)
    assert report.experiment.evaluation_horizon_hours == (6.0, 3.0, 1.0)
    assert not any(
        key in report.as_dict()
        for key in ("best_margin", "winning_margin", "recommended_margin", "optimal_margin")
    )


def test_two_hour_reclassification_reproduces_pr5_alert_semantics():
    result = reference_result()
    for record in result.records:
        if record.status == AssessmentStatus.AVAILABLE.value:
            assert classify_watcher_state(
                record.current_plan_slack_h, timedelta(hours=2)
            ) == record.severity


def test_common_support_requires_both_legs_and_available_assessment():
    result = reference_result()
    causal = causal_after_all_records(result)
    assert causal.common_support
    assert causal.inbound_causal_support_available
    assert causal.outbound_causal_support_available
    assert causal.watcher_assessment_available

    before_activation = build_causal_refinement_diagnostic(
        result,
        ucid=causal.ucid,
        scenario=ProcessScenario.REFERENCE,
        warning_margin=timedelta(hours=2),
        evaluation_horizon=timedelta(hours=1),
        evaluation_timestamp=min(
            call.updates[0].observed_at for call in result.population.replay_calls
        )
        - timedelta(seconds=1),
    )
    assert not before_activation.common_support


def test_common_support_asserts_same_baseline_and_watcher_inbound_prediction():
    result = reference_result()
    causal = causal_after_all_records(result)
    assert (
        causal.baseline_selected_inbound_prediction_timestamp
        == causal.selected_inbound_prediction_timestamp
    )
    records = list(result.records)
    for index, record in enumerate(records):
        if record.ucid == causal.ucid:
            records[index] = replace(
                record,
                baseline_prediction_observed_at=record.assessed_at
                + timedelta(seconds=1),
            )
    changed = replace(result, records=tuple(records))
    with pytest.raises(CommonSupportInvariantError):
        causal_after_all_records(changed)


def test_assessment_not_emitted_with_common_support_is_surfaced():
    result = reference_result()
    causal = causal_after_all_records(result)
    outcome = outcome_for(result)
    missing = replace(
        causal,
        inbound_causal_support_available=True,
        outbound_causal_support_available=True,
        selected_assessment_timestamp=None,
        watcher_assessment_available=False,
        watcher_state_under_margin=None,
        watcher_alert_under_margin=None,
    )
    assert (
        classify_miss_reason(missing, outcome)
        is MissReason.ASSESSMENT_NOT_EMITTED_WITH_COMMON_SUPPORT
    )


def test_prevention_opportunity_is_joined_only_after_causal_diagnostic():
    result = reference_result()
    outcome = outcome_for(result)
    causal = causal_after_all_records(result)
    assert not hasattr(causal, "retrospective_outcome")
    assert not hasattr(causal, "synthetic_prevention_opportunity")

    row = join_retrospective_evaluation(causal, outcome, result=result)
    assert row.synthetic_prevention_opportunity
    assert synthetic_prevention_opportunity(outcome)
    assert row.causal is causal


def test_zero_prevention_opportunity_denominator_is_explicit_null():
    reference = reference_result()
    low = scenario_result(reference, ProcessScenario.LOW)
    report = build_watcher_refinement_report((low,), dataset_hash="test-dataset")
    assert report.prevention_opportunity_summaries
    assert all(
        summary.opportunity_count == 0
        and summary.recall is None
        and summary.common_support_recall is None
        and summary.median_first_alert_lead_time_hours is None
        for summary in report.prevention_opportunity_summaries
    )


def churn_record(template, *, row, slack, available=True):
    timestamp = template.assessed_at + timedelta(minutes=row)
    return replace(
        template,
        ucid="churn-ucid",
        assessed_at=timestamp,
        trigger_cursor=ReplayCursor(timestamp, row + 1, f"trigger-{row}"),
        trigger_source_call_id=f"trigger-{row}",
        status=(
            AssessmentStatus.AVAILABLE.value
            if available
            else AssessmentStatus.UNAVAILABLE.value
        ),
        severity="SAFE" if available else None,
        current_plan_slack_h=slack if available else None,
        no_itt_slack_h=slack if available else None,
    )


def test_alert_churn_transitions_repeated_entries_and_recoveries_are_deterministic():
    template = reference_result().records[0]
    # AVAILABLE states at 2h: SAFE, WATCH, WATCH, AT_RISK, WATCH, SAFE,
    # WATCH, SAFE, WATCH. The unavailable gap between WATCH rows is not SAFE.
    specifications = (
        (3.0, True),
        (1.0, True),
        (None, False),
        (1.0, True),
        (-1.0, True),
        (1.0, True),
        (3.0, True),
        (1.0, True),
        (3.0, True),
        (1.0, True),
    )
    records = tuple(
        churn_record(template, row=index, slack=slack, available=available)
        for index, (slack, available) in enumerate(specifications)
    )
    cutoff = records[-1].assessed_at
    first = calculate_connection_alert_churn(
        records,
        ucid="churn-ucid",
        scenario=ProcessScenario.REFERENCE,
        warning_margin=timedelta(hours=2),
        cutoff=cutoff,
    )
    second = calculate_connection_alert_churn(
        reversed(records),
        ucid="churn-ucid",
        scenario=ProcessScenario.REFERENCE,
        warning_margin=timedelta(hours=2),
        cutoff=cutoff,
    )
    assert first == second
    assert first.unavailable_assessments == 1
    assert first.non_alert_to_alert_entries == 3
    assert first.repeated_alert_entries == 2
    assert first.recoveries_to_safe == 2
    assert first.within_alert_escalations == 1
    assert first.within_alert_deescalations == 1
    assert first.total_available_state_changes == 7


def test_unavailable_gap_is_not_treated_as_safe():
    template = reference_result().records[0]
    records = (
        churn_record(template, row=0, slack=1.0),
        churn_record(template, row=1, slack=None, available=False),
        churn_record(template, row=2, slack=1.0),
    )
    churn = calculate_connection_alert_churn(
        records,
        ucid="churn-ucid",
        scenario=ProcessScenario.REFERENCE,
        warning_margin=timedelta(hours=2),
        cutoff=records[-1].assessed_at,
    )
    assert churn.unavailable_assessments == 1
    assert churn.total_available_state_changes == 0
    assert churn.non_alert_to_alert_entries == 0
    assert churn.recoveries_to_safe == 0


def test_input_permutation_does_not_change_diagnostics_or_churn():
    result = reference_result()
    permuted_population = replace(
        result.population,
        replay_calls=tuple(
            replace(call, updates=tuple(reversed(call.updates)))
            for call in reversed(result.population.replay_calls)
        ),
    )
    permuted = replace(
        result,
        population=permuted_population,
        records=tuple(reversed(result.records)),
    )
    assert build_refinement_diagnostics(
        result, scenario=ProcessScenario.REFERENCE
    ) == build_refinement_diagnostics(
        permuted, scenario=ProcessScenario.REFERENCE
    )
    assert build_alert_churn(
        result, scenario=ProcessScenario.REFERENCE
    ) == build_alert_churn(
        permuted, scenario=ProcessScenario.REFERENCE
    )


def test_margin_grid_order_is_preserved_not_sorted():
    result = reference_result()
    margins = (timedelta(hours=4), timedelta(0), timedelta(hours=2))
    report = build_watcher_refinement_report(
        (result,), dataset_hash="test-dataset", warning_margins=margins
    )
    assert report.experiment.warning_margin_hours == (4.0, 0.0, 2.0)
    first_ucid = result.benchmark.connections[0].identity.ucid
    observed = [
        row.causal.warning_margin_hours
        for row in report.diagnostics
        if row.causal.ucid == first_ucid
        and row.causal.evaluation_horizon_hours == 6.0
    ]
    assert observed == [4.0, 0.0, 2.0]


def test_pr5_historical_report_v2_contract_remains_unchanged():
    reference = reference_result()
    results = tuple(scenario_result(reference, scenario) for scenario in ProcessScenario)
    watcher = WatcherConfig(timedelta(hours=2), timedelta(minutes=15))
    report = build_historical_benchmark_report(
        results,
        synthetic_config=historical_synthetic_config(
            dataset_sha256="historical-eval-test-dataset",
            connections_per_quota=1,
        ),
        watcher_config=watcher,
    )
    payload = report.as_dict()
    assert report.report_version == HISTORICAL_REPORT_VERSION
    assert HISTORICAL_REPORT_VERSION == "historical-watcher-report-v2"
    assert "diagnostics" not in payload
    assert "warning_margin_hours" not in payload


@pytest.mark.parametrize(
    ("relative_path", "expected"),
    (
        (
            "fixtures/synthetic/manifest.json",
            "63a7bb514c3d987702aef4e6d54e9ac222cfe06f85fc70cdbc4744a37bf2f6bd",
        ),
        (
            "fixtures/synthetic/benchmark.json",
            "289ea7acaafb1899639940daef234ad73e196aebb15bbc26a50bec5c16557c3a",
        ),
        (
            "fixtures/synthetic/assumptions.json",
            "deb1840c7b73e9769739878e2f77afc959ce2778d5d832ebfe399eaa982b5bdd",
        ),
        (
            "fixtures/synthetic/quotas.json",
            "c9b35c57341e30505013fa4083ba14e20a7bb1a42fcdfb662c0947b25a0ec7ed",
        ),
    ),
)
def test_existing_pr3_fixture_hashes_remain_unchanged(relative_path, expected):
    assert sha256((ROOT / relative_path).read_bytes()).hexdigest() == expected


def test_refinement_writer_cannot_target_or_overwrite_pr5_report(tmp_path):
    result = reference_result()
    report = build_watcher_refinement_report((result,), dataset_hash="test-dataset")
    with pytest.raises(ValueError, match="PR #5 report path"):
        write_watcher_refinement_report(
            report, tmp_path / "historical-watcher-report.json"
        )
    disguised = tmp_path / "renamed.json"
    disguised.write_text(
        '{"report_version": "historical-watcher-report-v2"}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="overwrite a PR #5 report"):
        validate_refinement_output_path(disguised)
    assert not (tmp_path / "historical-watcher-report.json").exists()
