from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
from inspect import signature
from pathlib import Path

import pytest

from latch.historical_eval import (
    HISTORICAL_REPORT_VERSION,
    HistoricalPopulationConfig,
    ReplayCursor,
    build_call_population,
    build_retrospective_outcomes,
    evaluate_historical_csv,
    historical_synthetic_config,
    records_through,
    replay_watcher_assessments,
)
from latch.replay import ArrivalBoundary, ReplayConfig
from latch.synthetic import ProcessScenario, canonical_digest
from latch.terminal_prevention_challenge import (
    CAUSAL_ACTIONABILITY_CAPABILITY_VERSION,
    CAUSAL_ACTIONABILITY_CURATION_LABEL,
    CHALLENGE_CURATION_LABEL,
    CHALLENGE_SELECTION_RULE_VERSION,
    TERMINAL_PREVENTION_CHALLENGE_VERSION,
    ChallengeCategory,
    RetrospectivePreventionActionability,
    build_causal_actionability_capability_selection,
    build_terminal_prevention_challenge_report,
    build_terminal_prevention_challenge_selection,
    causal_prevention_signal,
    classify_challenge_category,
    first_causal_prevention_signal,
    validate_challenge_output_path,
    write_terminal_prevention_challenge_report,
)
from latch.watcher import AssessmentStatus, WatcherConfig
from latch.watcher_refinement_eval import (
    FROZEN_BASELINE_THRESHOLD,
    FROZEN_PR5_REFERENCE_MARGIN,
)
from tests.test_historical_eval import accepted_calls, evaluation


ROOT = Path(__file__).resolve().parent.parent
HISTORICAL_CSV = ROOT / "Data Inspection" / "Singapore_anonymized.csv"
FROZEN_POPULATION_DIGEST = (
    "2cb9b23d006344f7f8e3d38b98ae030e727e846b83936a99a3272cfda5dd7291"
)
FROZEN_GRAPH_DIGEST = (
    "25c1a7a1f989da12f7a58729532797fc69777e53fcba2ba2d76fec182e5b60a2"
)
FROZEN_GRAPH_OUTPUT_DIGEST = (
    "0df7cd032f84ced28227a10cd8978524be46eaac1710ad5d86e9eccd8fcf3132"
)


def challenge_fixture():
    result = evaluation()
    config = historical_synthetic_config(
        dataset_sha256="historical-eval-test-dataset",
        connections_per_quota=1,
    )
    return result, config


def challenge_selection():
    result, config = challenge_fixture()
    return build_terminal_prevention_challenge_selection(
        result.population, config, target_per_category=1
    )


def test_challenge_contract_is_explicitly_curated_and_separate():
    result, config = challenge_fixture()
    report = build_terminal_prevention_challenge_report(
        result,
        synthetic_config=config,
        dataset_hash="historical-eval-test-dataset",
        target_per_category=1,
    )
    assert report.report_version == TERMINAL_PREVENTION_CHALLENGE_VERSION
    assert report.selection_rule_version == CHALLENGE_SELECTION_RULE_VERSION
    assert report.curation == CHALLENGE_CURATION_LABEL
    assert "DELIBERATELY CURATED" in report.curation
    assert report.challenge_graph_digest != report.frozen_historical_graph_digest
    assert report.ordered_case_ids == tuple(
        case.identity.challenge_case_id for case in report.cases
    )


def test_challenge_build_does_not_mutate_or_extend_historical_evaluation():
    result, config = challenge_fixture()
    population_before = result.population
    benchmark_before = result.benchmark
    records_before = result.records
    diagnostics_before = result.diagnostics
    historical_ucids = tuple(
        connection.identity.ucid for connection in result.benchmark.connections
    )

    report = build_terminal_prevention_challenge_report(
        result,
        synthetic_config=config,
        dataset_hash="historical-eval-test-dataset",
        target_per_category=1,
    )

    assert result.population == population_before
    assert result.benchmark == benchmark_before
    assert result.records == records_before
    assert result.diagnostics == diagnostics_before
    assert tuple(
        connection.identity.ucid for connection in result.benchmark.connections
    ) == historical_ucids
    assert not {
        case.identity.ucid for case in report.cases
    }.intersection(historical_ucids)


def test_process_assumptions_are_reused_without_mutation():
    result, config = challenge_fixture()
    assumptions_before = config.process_assumptions
    digest_before = canonical_digest(assumptions_before)
    selection = build_terminal_prevention_challenge_selection(
        result.population, config, target_per_category=1
    )
    assert config.process_assumptions == assumptions_before
    assert canonical_digest(config.process_assumptions) == digest_before
    for case in selection.selected_cases:
        assert tuple(
            (item.scenario, item.cargo_ready_offset, item.cargo_cutoff_lead)
            for item in case.connection.process_projections
        ) == tuple(
            (item.scenario, item.cargo_ready_offset, item.cargo_cutoff_lead)
            for item in config.process_assumptions
        )


def test_changed_process_assumptions_are_rejected():
    result, config = challenge_fixture()
    reference_index = next(
        index
        for index, item in enumerate(config.process_assumptions)
        if item.scenario is ProcessScenario.REFERENCE
    )
    assumptions = list(config.process_assumptions)
    assumptions[reference_index] = replace(
        assumptions[reference_index],
        cargo_ready_offset=(
            assumptions[reference_index].cargo_ready_offset + timedelta(minutes=1)
        ),
    )
    changed = replace(config, process_assumptions=tuple(assumptions))
    with pytest.raises(ValueError, match="unchanged historical process assumptions"):
        build_terminal_prevention_challenge_selection(
            result.population, changed, target_per_category=1
        )


def test_selection_and_identity_are_deterministic_under_input_permutation():
    result, config = challenge_fixture()
    population = result.population
    permuted = replace(
        population,
        replay_calls=tuple(
            replace(call, updates=tuple(reversed(call.updates)))
            for call in reversed(population.replay_calls)
        ),
        retrospective_calls=tuple(reversed(population.retrospective_calls)),
    )
    first = build_terminal_prevention_challenge_selection(
        population, config, target_per_category=1
    )
    second = build_terminal_prevention_challenge_selection(
        permuted, config, target_per_category=1
    )
    assert first == second
    assert first.ordered_case_ids == second.ordered_case_ids
    assert first.challenge_set_digest == second.challenge_set_digest
    assert first.benchmark.manifest.output_digest == second.benchmark.manifest.output_digest


@pytest.mark.parametrize(
    ("transfer", "slack", "no_itt", "expected"),
    (
        (
            1,
            0,
            1,
            ChallengeCategory.RETROSPECTIVE_PREVENTION_OPPORTUNITY,
        ),
        (1, -1, 0, ChallengeCategory.UNRECOVERABLE_WITH_NO_ITT),
        (1, 0, 0, ChallengeCategory.UNRECOVERABLE_WITH_NO_ITT),
        (1, 0.1, 1.1, ChallengeCategory.FEASIBLE_WITH_ITT),
    ),
)
def test_category_boundaries(transfer, slack, no_itt, expected):
    assert (
        classify_challenge_category(
            transfer_duration=timedelta(hours=transfer),
            retrospective_slack=timedelta(hours=slack),
            retrospective_no_itt_slack=timedelta(hours=no_itt),
        )
        is expected
    )


@pytest.mark.parametrize(
    ("available", "current", "no_itt", "expected"),
    (
        (True, 0.0, 0.1, True),
        (True, -1.0, 0.1, True),
        (True, 0.1, 1.1, False),
        (True, 0.0, 0.0, False),
        (True, -1.0, -0.1, False),
        (False, -1.0, 1.0, False),
    ),
)
def test_causal_prevention_signal_boundaries(
    available, current, no_itt, expected
):
    assert tuple(signature(causal_prevention_signal).parameters) == (
        "assessment_available",
        "current_plan_slack_hours",
        "no_itt_slack_hours",
    )
    assert causal_prevention_signal(
        assessment_available=available,
        current_plan_slack_hours=current,
        no_itt_slack_hours=no_itt,
    ) is expected


def _signal_record(template, *, minute, current, no_itt, available=True):
    assessed_at = template.assessed_at + timedelta(minutes=minute)
    return replace(
        template,
        assessed_at=assessed_at,
        trigger_cursor=ReplayCursor(
            assessed_at, minute + 10_000, f"signal-trigger-{minute}"
        ),
        trigger_source_call_id=f"signal-trigger-{minute}",
        status=(
            AssessmentStatus.AVAILABLE.value
            if available
            else AssessmentStatus.UNAVAILABLE.value
        ),
        severity="AT_RISK" if available and current <= 0 else "SAFE",
        current_plan_slack_h=current if available else None,
        no_itt_slack_h=no_itt if available else None,
    )


def test_first_causal_signal_is_earliest_deterministic_and_future_safe():
    template = evaluation().records[0]
    records = (
        _signal_record(template, minute=1, current=0.1, no_itt=1.1),
        _signal_record(template, minute=2, current=0.0, no_itt=0.0),
        _signal_record(template, minute=3, current=0.0, no_itt=0.5),
        _signal_record(template, minute=4, current=-1.0, no_itt=1.0),
    )
    cutoff = records[2].assessed_at
    first = first_causal_prevention_signal(reversed(records), cutoff=cutoff)
    assert first == records[2]
    assert first_causal_prevention_signal(records[:3], cutoff=cutoff) == first

    future = _signal_record(template, minute=100, current=-9.0, no_itt=9.0)
    assert first_causal_prevention_signal(
        (*records, future), cutoff=cutoff
    ) == first


def test_retrospective_preventability_and_causal_actionability_are_independent():
    retrospective = classify_challenge_category(
        transfer_duration=timedelta(hours=2),
        retrospective_slack=timedelta(minutes=-1),
        retrospective_no_itt_slack=timedelta(minutes=119),
    )
    assert (
        retrospective
        is ChallengeCategory.RETROSPECTIVE_PREVENTION_OPPORTUNITY
    )
    assert not causal_prevention_signal(
        assessment_available=True,
        current_plan_slack_hours=-3.0,
        no_itt_slack_hours=-1.0,
    )
    assert causal_prevention_signal(
        assessment_available=True,
        current_plan_slack_hours=-0.5,
        no_itt_slack_hours=1.5,
    )


def test_causal_actionability_selection_is_permutation_deterministic():
    result, config = challenge_fixture()
    population = result.population
    permuted = replace(
        population,
        replay_calls=tuple(
            replace(call, updates=tuple(reversed(call.updates)))
            for call in reversed(population.replay_calls)
        ),
        retrospective_calls=tuple(reversed(population.retrospective_calls)),
    )
    first = build_causal_actionability_capability_selection(
        population, config, target=1
    )
    second = build_causal_actionability_capability_selection(
        permuted, config, target=1
    )
    assert first == second
    assert first.version == CAUSAL_ACTIONABILITY_CAPABILITY_VERSION
    assert first.curation == CAUSAL_ACTIONABILITY_CURATION_LABEL
    assert first.ordered_case_ids == second.ordered_case_ids
    assert first.capability_set_digest == second.capability_set_digest


def test_selected_cases_satisfy_category_definitions_and_positive_transfer():
    selection = challenge_selection()
    assert tuple(case.category for case in selection.selected_cases) == tuple(
        ChallengeCategory
    )
    for case in selection.selected_cases:
        outcome = case.retrospective_outcome
        assert outcome.transfer_duration > timedelta(0)
        if (
            case.category
            is ChallengeCategory.RETROSPECTIVE_PREVENTION_OPPORTUNITY
        ):
            assert outcome.retrospective_slack <= timedelta(0)
            assert outcome.retrospective_no_itt_slack > timedelta(0)
        elif case.category is ChallengeCategory.UNRECOVERABLE_WITH_NO_ITT:
            assert outcome.retrospective_slack <= timedelta(0)
            assert outcome.retrospective_no_itt_slack <= timedelta(0)
        else:
            assert outcome.retrospective_slack > timedelta(0)


def test_reference_only_is_used_when_reference_has_every_category():
    selection = challenge_selection()
    reference_counts = {
        item.category: item.count
        for item in selection.candidate_counts
        if item.scenario == ProcessScenario.REFERENCE.value
    }
    assert all(reference_counts[category.value] >= 1 for category in ChallengeCategory)
    assert all(
        case.scenario is ProcessScenario.REFERENCE
        for case in selection.selected_cases
    )


def test_retrospective_selection_data_cannot_enter_causal_replay():
    result, config = challenge_fixture()
    selection = build_terminal_prevention_challenge_selection(
        result.population, config, target_per_category=1
    )
    watcher = WatcherConfig(
        FROZEN_PR5_REFERENCE_MARGIN,
        FROZEN_BASELINE_THRESHOLD,
        ProcessScenario.REFERENCE,
    )
    before = replay_watcher_assessments(
        result.population, selection.benchmark, watcher
    )
    changed_retrospective = tuple(
        replace(
            item,
            final_event=replace(
                item.final_event,
                derived_geofence_arrival=(
                    item.final_event.derived_geofence_arrival + timedelta(days=90)
                ),
            ),
        )
        for item in result.population.retrospective_calls
    )
    changed_population = replace(
        result.population, retrospective_calls=changed_retrospective
    )
    after = replay_watcher_assessments(
        changed_population, selection.benchmark, watcher
    )
    assert before.records == after.records
    assert before.diagnostics == after.diagnostics


def test_future_observation_cannot_change_earlier_challenge_assessments():
    result, config = challenge_fixture()
    selection = build_terminal_prevention_challenge_selection(
        result.population, config, target_per_category=1
    )
    watcher = WatcherConfig(
        FROZEN_PR5_REFERENCE_MARGIN,
        FROZEN_BASELINE_THRESHOLD,
        ProcessScenario.REFERENCE,
    )
    before = replay_watcher_assessments(
        result.population, selection.benchmark, watcher
    )
    last_cursor = max(record.trigger_cursor for record in before.records)
    connection = selection.selected_cases[0].connection
    call_id = connection.assignment.inbound_source_call_id
    call_index = next(
        index
        for index, call in enumerate(result.population.replay_calls)
        if call.call_id == call_id
    )
    call = result.population.replay_calls[call_index]
    source = call.updates[-1]
    future_observation = replace(
        source.source_observation,
        observed_at=last_cursor.observed_at + timedelta(days=1),
        source_row_number=last_cursor.source_row_number + 1_000_000,
    )
    future = replace(
        source,
        observed_at=future_observation.observed_at,
        predicted_arrival=source.predicted_arrival + timedelta(days=30),
        source_observation=future_observation,
    )
    calls = list(result.population.replay_calls)
    calls[call_index] = replace(call, updates=(*call.updates, future))
    changed_population = replace(result.population, replay_calls=tuple(calls))
    after = replay_watcher_assessments(
        changed_population, selection.benchmark, watcher
    )
    assert records_through(after.records, last_cursor) == before.records


def test_zero_candidate_shortfall_is_explicit_without_altering_assumptions():
    calls = accepted_calls()[:2]
    population = build_call_population(
        calls, HistoricalPopulationConfig(source_call_limit=2)
    )
    config = historical_synthetic_config(
        dataset_sha256="shortfall-test", connections_per_quota=1
    )
    selection = build_terminal_prevention_challenge_selection(
        population, config, target_per_category=4
    )
    assert all(item.target == 4 for item in selection.category_selections)
    assert all(item.shortfall == 4 - item.selected for item in selection.category_selections)
    assert any(item.shortfall > 0 for item in selection.category_selections)


def test_historical_report_contract_and_protected_files_remain_unchanged():
    assert HISTORICAL_REPORT_VERSION == "historical-watcher-report-v2"
    expected = {
        "src/latch/replay.py": "0d6983e0fe367e64419e062d7eda5b4055b6c0e73d1b4392470cd2d890bf135a",
        "src/latch/synthetic.py": "10aac71945b382f8ae7bed90151a37352289b6dbf78369cb519044a85ff3b6bf",
        "src/latch/watcher.py": "ae12ec12002fd1d0e3414dbe11b06842ba7e8b95a7a510d957cbed9139cf010c",
        "src/latch/historical_eval.py": "919c8714cdd718385711f00e56877d3565ed606e4f6640588d49ee96cfd190fc",
    }
    assert {
        path: sha256((ROOT / path).read_bytes()).hexdigest() for path in expected
    } == expected


@pytest.mark.skipif(
    not HISTORICAL_CSV.is_file() or HISTORICAL_CSV.stat().st_size < 1_000,
    reason="historical AIS file is unavailable or still an LFS pointer",
)
def test_frozen_real_32_connection_benchmark_and_zero_opportunities_remain_unchanged():
    dataset_hash = sha256(HISTORICAL_CSV.read_bytes()).hexdigest()
    config = historical_synthetic_config(dataset_sha256=dataset_hash)
    reference = evaluate_historical_csv(
        HISTORICAL_CSV,
        replay_config=ReplayConfig(boundary=ArrivalBoundary()),
        population_config=HistoricalPopulationConfig(),
        synthetic_config=config,
        watcher_config=WatcherConfig(
            FROZEN_PR5_REFERENCE_MARGIN,
            FROZEN_BASELINE_THRESHOLD,
            ProcessScenario.REFERENCE,
        ),
    )
    assert len(reference.benchmark.connections) == 32
    assert reference.population.population_digest == FROZEN_POPULATION_DIGEST
    assert reference.benchmark.manifest.graph_digest == FROZEN_GRAPH_DIGEST
    assert reference.benchmark.manifest.output_digest == FROZEN_GRAPH_OUTPUT_DIGEST
    infeasible_counts = []
    opportunity_counts = []
    for scenario in ProcessScenario:
        outcomes = build_retrospective_outcomes(reference, scenario=scenario).outcomes
        infeasible_counts.append(sum(item.retrospective_slack <= timedelta(0) for item in outcomes))
        opportunity_counts.append(sum(item.synthetic_terminal_prevention_opportunity for item in outcomes))
    assert infeasible_counts == [7, 9, 9]
    assert opportunity_counts == [0, 0, 0]

    challenge = build_terminal_prevention_challenge_report(
        reference,
        synthetic_config=config,
        dataset_hash=dataset_hash,
    )
    assert len(reference.benchmark.connections) == 32
    assert reference.benchmark.manifest.output_digest == FROZEN_GRAPH_OUTPUT_DIGEST
    retrospective_prevention = challenge.cases[:4]
    assert [
        case.causal_detection.retrospective_prevention_actionability
        for case in retrospective_prevention
    ] == [
        RetrospectivePreventionActionability.CAUSALLY_ACTIONABLE.value,
        RetrospectivePreventionActionability.NO_CAUSAL_ASSESSMENT_BEFORE_CUTOFF.value,
        RetrospectivePreventionActionability.ALERTED_AFTER_PREVENTION_WINDOW_CLOSED.value,
        RetrospectivePreventionActionability.ALERTED_AFTER_PREVENTION_WINDOW_CLOSED.value,
    ]
    capability = challenge.causal_actionability_capability_set
    assert capability.candidate_count == 5_051
    assert capability.selected == 4
    assert capability.shortfall == 0
    assert all(
        case.causal_detection.causal_prevention_signal_before_cutoff
        and case.causal_detection.watcher_state_at_risk_at_first_prevention_signal
        for case in capability.cases
    )
    assert not {
        case.identity.ucid for case in capability.cases
    }.intersection(
        connection.identity.ucid for connection in reference.benchmark.connections
    )


@pytest.mark.parametrize(
    "name",
    (
        "historical-watcher-report-v2.json",
        "watcher-refinement-report-v1.json",
        "README.md",
        "Singapore_ais_dataset_assessment.md",
    ),
)
def test_challenge_writer_rejects_frozen_report_and_evidence_targets(tmp_path, name):
    with pytest.raises(ValueError):
        validate_challenge_output_path(tmp_path / name)


@pytest.mark.parametrize(
    "path",
    (
        ROOT / "src/latch/watcher.py",
        ROOT / "README.md",
        ROOT / "COMPLIANCE.md",
        ROOT / "uv.lock",
        ROOT / "docs/pr6-watcher-refinement.md",
    ),
)
def test_challenge_writer_rejects_non_json_project_files(path):
    with pytest.raises(ValueError, match="end in .json"):
        validate_challenge_output_path(path)


def test_challenge_writer_rejects_unrelated_existing_json(tmp_path):
    path = tmp_path / "unrelated.json"
    path.write_text('{"purpose": "not a report"}', encoding="utf-8")
    with pytest.raises(ValueError, match="unrelated JSON file"):
        validate_challenge_output_path(path)


def test_challenge_writer_is_deterministic(tmp_path):
    result, config = challenge_fixture()
    report = build_terminal_prevention_challenge_report(
        result,
        synthetic_config=config,
        dataset_hash="historical-eval-test-dataset",
        target_per_category=1,
    )
    first = tmp_path / "challenge-1.json"
    second = tmp_path / "challenge-2.json"
    write_terminal_prevention_challenge_report(report, first)
    write_terminal_prevention_challenge_report(report, second)
    assert first.read_bytes() == second.read_bytes()
    assert validate_challenge_output_path(first) == first
    write_terminal_prevention_challenge_report(report, first)
