from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from latch.historical_eval import (
    HISTORICAL_CONFIG_VERSION,
    RETROSPECTIVE_OUTCOME_VERSION,
    BinaryCounts,
    ReplayCursor,
    RetrospectiveConnectionOutcome,
    SyntheticScenarioFeasibility,
    alert_churn_statistics,
    binary_rates,
    build_historical_benchmark_report,
    build_retrospective_outcomes,
    evaluate_fixed_horizon,
    first_alert_lead_times,
    historical_synthetic_config,
    replay_watcher_assessments,
    select_assessment_at_horizon,
    watcher_alert,
)
from latch.synthetic import ProcessScenario
from latch.watcher import AssessmentStatus, WatcherConfig
from tests.test_historical_eval import accepted_calls, evaluation


NOW = datetime(2023, 10, 20, 12, tzinfo=UTC)


def outcome(
    ucid: str,
    *,
    cutoff: datetime = NOW,
    infeasible: bool,
) -> RetrospectiveConnectionOutcome:
    slack = timedelta(hours=-1 if infeasible else 1)
    inbound_crossing = cutoff - slack
    feasibility = (
        SyntheticScenarioFeasibility.INFEASIBLE
        if infeasible
        else SyntheticScenarioFeasibility.FEASIBLE
    )
    return RetrospectiveConnectionOutcome(
        outcome_version=RETROSPECTIVE_OUTCOME_VERSION,
        ucid=ucid,
        inbound_source_call_id=f"{ucid}-in",
        outbound_source_call_id=f"{ucid}-out",
        process_assumption_id=f"{HISTORICAL_CONFIG_VERSION}:reference",
        final_inbound_derived_crossing=inbound_crossing,
        final_outbound_derived_crossing=cutoff,
        cargo_ready_offset=timedelta(0),
        cargo_cutoff_lead=timedelta(0),
        transfer_duration=timedelta(0),
        retrospective_inbound_ready=inbound_crossing,
        retrospective_outbound_cutoff=cutoff,
        retrospective_slack=slack,
        feasibility=feasibility,
        retrospective_no_itt_slack=slack,
        synthetic_terminal_prevention_opportunity=False,
    )


def record(
    template,
    ucid: str,
    assessed_at: datetime,
    *,
    watcher: bool | None,
    baseline: bool | None,
    row: int,
):
    if watcher is None:
        status = AssessmentStatus.UNAVAILABLE.value
        severity = None
    else:
        status = AssessmentStatus.AVAILABLE.value
        severity = "WATCH" if watcher else "SAFE"
    return replace(
        template,
        ucid=ucid,
        assessed_at=assessed_at,
        trigger_cursor=ReplayCursor(assessed_at, row, f"trigger-{row}"),
        trigger_source_call_id=f"trigger-{row}",
        status=status,
        severity=severity,
        reason_codes=("prediction_unavailable",) if watcher is None else (),
        baseline_available=baseline is not None,
        baseline_alert=baseline,
    )


def template_record():
    return evaluation().records[0]


def test_retrospective_outcome_uses_exact_slack_formula_and_no_itt_separately():
    result = evaluation()
    outcomes = build_retrospective_outcomes(
        result, scenario=ProcessScenario.REFERENCE
    ).outcomes
    assert outcomes
    value = outcomes[0]
    assert value.retrospective_inbound_ready == (
        value.final_inbound_derived_crossing
        + value.cargo_ready_offset
        + value.transfer_duration
    )
    assert value.retrospective_outbound_cutoff == (
        value.final_outbound_derived_crossing - value.cargo_cutoff_lead
    )
    assert value.retrospective_slack == (
        value.retrospective_outbound_cutoff
        - value.retrospective_inbound_ready
    )
    assert value.retrospective_no_itt_slack == (
        value.retrospective_outbound_cutoff
        - (value.final_inbound_derived_crossing + value.cargo_ready_offset)
    )


@pytest.mark.parametrize(
    ("slack", "expected"),
    [
        (timedelta(0), SyntheticScenarioFeasibility.INFEASIBLE),
        (timedelta(microseconds=1), SyntheticScenarioFeasibility.FEASIBLE),
    ],
)
def test_zero_slack_is_infeasible_and_positive_slack_is_feasible(slack, expected):
    cutoff = NOW
    inbound = cutoff - slack
    value = RetrospectiveConnectionOutcome(
        outcome_version=RETROSPECTIVE_OUTCOME_VERSION,
        ucid="ucid",
        inbound_source_call_id="in",
        outbound_source_call_id="out",
        process_assumption_id="scenario",
        final_inbound_derived_crossing=inbound,
        final_outbound_derived_crossing=cutoff,
        cargo_ready_offset=timedelta(0),
        cargo_cutoff_lead=timedelta(0),
        transfer_duration=timedelta(0),
        retrospective_inbound_ready=inbound,
        retrospective_outbound_cutoff=cutoff,
        retrospective_slack=slack,
        feasibility=expected,
        retrospective_no_itt_slack=slack,
        synthetic_terminal_prevention_opportunity=False,
    )
    assert value.feasibility is expected


def test_changed_final_crossing_changes_only_post_replay_outcome():
    calls = accepted_calls()
    before = evaluation(calls)
    connection = before.benchmark.connections[0]
    changed_call_id = connection.assignment.inbound_source_call_id
    changed_calls = tuple(
        replace(
            call,
            derived_geofence_arrival=(
                call.derived_geofence_arrival + timedelta(hours=12)
                if call.call_id == changed_call_id
                else call.derived_geofence_arrival
            ),
        )
        for call in calls
    )
    after = evaluation(changed_calls)
    before_outcomes = build_retrospective_outcomes(
        before, scenario=ProcessScenario.REFERENCE
    )
    after_outcomes = build_retrospective_outcomes(
        after, scenario=ProcessScenario.REFERENCE
    )
    assert before.records == after.records
    assert before_outcomes != after_outcomes


def test_outcomes_require_completed_replay_result_and_remain_separate():
    result = evaluation()
    with pytest.raises(AttributeError):
        build_retrospective_outcomes(  # type: ignore[arg-type]
            result.population, scenario=ProcessScenario.REFERENCE
        )
    assert not any(
        field in result.records[0].__slots__
        for field in (
            "retrospective_slack",
            "feasibility",
            "final_inbound_derived_crossing",
        )
    )


def test_no_itt_opportunity_is_synthetic_and_not_the_primary_label():
    cutoff = NOW
    transfer = timedelta(hours=2)
    inbound = cutoff - timedelta(hours=1)
    value = RetrospectiveConnectionOutcome(
        outcome_version=RETROSPECTIVE_OUTCOME_VERSION,
        ucid="opportunity",
        inbound_source_call_id="in",
        outbound_source_call_id="out",
        process_assumption_id="scenario",
        final_inbound_derived_crossing=inbound,
        final_outbound_derived_crossing=cutoff,
        cargo_ready_offset=timedelta(0),
        cargo_cutoff_lead=timedelta(0),
        transfer_duration=transfer,
        retrospective_inbound_ready=inbound + transfer,
        retrospective_outbound_cutoff=cutoff,
        retrospective_slack=timedelta(hours=-1),
        feasibility=SyntheticScenarioFeasibility.INFEASIBLE,
        retrospective_no_itt_slack=timedelta(hours=1),
        synthetic_terminal_prevention_opportunity=True,
    )
    assert value.feasibility is SyntheticScenarioFeasibility.INFEASIBLE
    assert value.synthetic_terminal_prevention_opportunity


def test_watcher_primary_alert_includes_watch_and_at_risk():
    template = template_record()
    watch = record(
        template, "watch", NOW, watcher=True, baseline=False, row=1
    )
    at_risk = replace(watch, severity="AT_RISK")
    safe = replace(watch, severity="SAFE")
    assert watcher_alert(watch) is True
    assert watcher_alert(at_risk) is True
    assert watcher_alert(safe) is False
    assert watcher_alert(None) is None


def test_fixed_horizon_selects_latest_at_or_before_and_never_looks_forward():
    template = template_record()
    value = outcome("one", infeasible=True)
    records = (
        record(template, "one", NOW - timedelta(hours=7), watcher=False, baseline=False, row=1),
        record(template, "one", NOW - timedelta(hours=6), watcher=True, baseline=True, row=2),
        record(template, "one", NOW - timedelta(hours=5), watcher=False, baseline=False, row=3),
        record(template, "one", NOW - timedelta(hours=3), watcher=False, baseline=False, row=4),
        record(template, "one", NOW - timedelta(hours=1), watcher=True, baseline=False, row=5),
    )
    assert select_assessment_at_horizon(records, value, timedelta(hours=6)) == records[1]
    assert select_assessment_at_horizon(records, value, timedelta(hours=3)) == records[3]
    assert select_assessment_at_horizon(records, value, timedelta(hours=1)) == records[4]


def test_fixed_horizon_absence_is_unavailable_and_rows_do_not_multiply_denominator():
    template = template_record()
    outcomes = (outcome("one", infeasible=True), outcome("two", infeasible=False))
    repeated = tuple(
        record(
            template,
            "one",
            NOW - timedelta(hours=8) + timedelta(minutes=index),
            watcher=True,
            baseline=False,
            row=index + 1,
        )
        for index in range(20)
    )
    scored = evaluate_fixed_horizon(repeated, outcomes, timedelta(hours=6))
    assert scored.availability.total_benchmark_connections == 2
    assert scored.watcher.raw_connection_level.tp == 1
    assert scored.watcher.raw_connection_level.unavailable == 1
    assert scored.watcher.end_to_end_support.support == 2


def test_horizon_selection_is_deterministic_under_permutation():
    template = template_record()
    value = outcome("one", infeasible=True)
    records = tuple(
        record(
            template,
            "one",
            NOW - timedelta(hours=8) + timedelta(minutes=index),
            watcher=bool(index % 2),
            baseline=False,
            row=index + 1,
        )
        for index in range(5)
    )
    assert select_assessment_at_horizon(records, value, timedelta(hours=6)) == (
        select_assessment_at_horizon(reversed(records), value, timedelta(hours=6))
    )


def test_connection_level_confusion_rates_and_unavailable():
    template = template_record()
    cases = (
        ("tp", True, True, False),
        ("fp", False, True, True),
        ("tn", False, False, False),
        ("fn", True, False, True),
        ("unavailable", True, None, None),
    )
    outcomes = tuple(outcome(name, infeasible=actual) for name, actual, _, _ in cases)
    records = tuple(
        record(
            template,
            name,
            NOW - timedelta(hours=7),
            watcher=watcher_value,
            baseline=baseline_value,
            row=index + 1,
        )
        for index, (name, _, watcher_value, baseline_value) in enumerate(cases)
        if watcher_value is not None
    )
    scored = evaluate_fixed_horizon(records, outcomes, timedelta(hours=6))
    watcher = scored.watcher
    assert (
        watcher.raw_connection_level.tp,
        watcher.raw_connection_level.fp,
        watcher.raw_connection_level.tn,
        watcher.raw_connection_level.fn,
        watcher.raw_connection_level.unavailable,
    ) == (1, 1, 1, 1, 1)
    assert watcher.available_support.rates.recall == pytest.approx(0.5)
    assert watcher.available_support.rates.precision == pytest.approx(0.5)
    assert watcher.available_support.rates.false_alarm_rate == pytest.approx(0.5)
    assert watcher.available_support.rates.specificity == pytest.approx(0.5)
    assert watcher.available_support.rates.f1 == pytest.approx(0.5)
    assert watcher.end_to_end_support.counts.fn == 2


def test_zero_denominator_rates_are_explicit_none():
    rates = binary_rates(BinaryCounts(0, 0, 0, 0))
    assert rates.recall is None
    assert rates.precision is None
    assert rates.false_alarm_rate is None
    assert rates.specificity is None
    assert rates.f1 is None


def test_paired_true_and_false_alert_disagreements():
    template = template_record()
    cases = (
        ("i-both", True, True, True),
        ("i-watcher", True, True, False),
        ("i-baseline", True, False, True),
        ("i-neither", True, False, False),
        ("f-both", False, True, True),
        ("f-watcher", False, True, False),
        ("f-baseline", False, False, True),
        ("f-neither", False, False, False),
    )
    outcomes = tuple(outcome(name, infeasible=actual) for name, actual, _, _ in cases)
    records = tuple(
        record(
            template,
            name,
            NOW - timedelta(hours=7),
            watcher=watcher_value,
            baseline=baseline_value,
            row=index + 1,
        )
        for index, (name, _, watcher_value, baseline_value) in enumerate(cases)
    )
    paired = evaluate_fixed_horizon(
        records, outcomes, timedelta(hours=6)
    ).paired_comparison
    assert (
        paired.retrospectively_infeasible.both_alert,
        paired.retrospectively_infeasible.watcher_only,
        paired.retrospectively_infeasible.baseline_only,
        paired.retrospectively_infeasible.neither,
    ) == (1, 1, 1, 1)
    assert (
        paired.retrospectively_feasible.both_alert,
        paired.retrospectively_feasible.watcher_only,
        paired.retrospectively_feasible.baseline_only,
        paired.retrospectively_feasible.neither,
    ) == (1, 1, 1, 1)


def test_first_alert_lead_time_is_independent_and_ignores_after_cutoff():
    template = template_record()
    outcomes = (outcome("caught", infeasible=True), outcome("missed", infeasible=True))
    records = (
        record(template, "caught", NOW - timedelta(hours=5), watcher=True, baseline=False, row=1),
        record(template, "caught", NOW - timedelta(hours=4), watcher=True, baseline=False, row=2),
        record(template, "caught", NOW - timedelta(hours=2), watcher=False, baseline=True, row=3),
        record(template, "missed", NOW + timedelta(minutes=1), watcher=True, baseline=True, row=4),
    )
    lead = first_alert_lead_times(records, outcomes)
    assert lead.watcher.caught_infeasible_connections == 1
    assert lead.watcher.missed_infeasible_connections == 1
    assert lead.watcher.median_lead_time_h == 5
    assert lead.reference_delay_baseline.median_lead_time_h == 2


def test_churn_counts_real_state_changes_not_identical_repeats_and_is_deterministic():
    template = template_record()
    outcomes = (outcome("changing", infeasible=True), outcome("quiet", infeasible=False))
    states = (False, False, True, True, True, False)
    rows = tuple(
        record(
            template,
            "changing",
            NOW - timedelta(hours=6) + timedelta(minutes=index),
            watcher=value,
            baseline=False,
            row=index + 1,
        )
        for index, value in enumerate(states)
    )
    before = alert_churn_statistics(rows, outcomes)
    after = alert_churn_statistics(reversed(rows), reversed(outcomes))
    assert before == after
    assert before.median_transitions_per_connection == 1
    assert before.zero_transition_connections == 1


def test_identical_bounded_reports_are_byte_reproducible_across_all_scenarios():
    reference = evaluation()
    watcher = WatcherConfig(timedelta(hours=2), timedelta(minutes=15))
    results = tuple(
        reference
        if scenario is ProcessScenario.REFERENCE
        else replay_watcher_assessments(
            reference.population,
            reference.benchmark,
            replace(watcher, process_scenario=scenario),
        )
        for scenario in ProcessScenario
    )
    synthetic_config = historical_synthetic_config(
        dataset_sha256="historical-eval-test-dataset",
        connections_per_quota=1,
    )
    first = build_historical_benchmark_report(
        results,
        synthetic_config=synthetic_config,
        watcher_config=watcher,
    )
    second = build_historical_benchmark_report(
        tuple(reversed(tuple(reversed(results)))),
        synthetic_config=synthetic_config,
        watcher_config=watcher,
    )
    assert first.to_json() == second.to_json()
    assert '"report_version": "historical-watcher-report-v1"' in first.to_json()
