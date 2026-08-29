"""Evaluation-only Watcher calibration diagnostics built on the PR #5 replay.

The module deliberately separates a causal diagnostic from its later
retrospective scoring join.  Warning-margin experiments reclassify the causal
slack already recorded by PR #5; they never regenerate the population, graph,
UCIDs, predictions, slack, baseline, or retrospective outcomes.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Mapping

from latch.events import RiskSeverity
from latch.historical_eval import (
    HISTORICAL_REPORT_VERSION,
    HistoricalAssessmentRecord,
    HistoricalEvaluationResult,
    HistoricalRecordsByUcid,
    RetrospectiveConnectionOutcome,
    SyntheticScenarioFeasibility,
    build_retrospective_outcomes,
    records_by_ucid,
    update_cursor,
)
from latch.replay import CausalArrivalUpdate, PredictionStatus
from latch.synthetic import ProcessScenario, canonical_digest, to_primitive
from latch.watcher import AssessmentStatus, WatcherConfig


PR5_PARENT_COMMIT = "2fad0f8be7c6856a03098049d05e1aac5b52d268"
WATCHER_REFINEMENT_REPORT_VERSION = "watcher-refinement-report-v1"
FROZEN_PR5_REFERENCE_MARGIN = timedelta(hours=2)
FROZEN_BASELINE_THRESHOLD = timedelta(minutes=15)
FROZEN_EVALUATION_HORIZONS = (
    timedelta(hours=6),
    timedelta(hours=3),
    timedelta(hours=1),
)
EXPERIMENTAL_WARNING_MARGINS = (
    timedelta(hours=0),
    timedelta(hours=1),
    timedelta(hours=2),
    timedelta(hours=3),
    timedelta(hours=4),
)


class CommonSupportInvariantError(ValueError):
    """Raised when a purported common-support comparison is not comparable."""


class MissReason(StrEnum):
    NO_EITHER_LEG_SUPPORT = "NO_EITHER_LEG_SUPPORT"
    NO_INBOUND_SUPPORT = "NO_INBOUND_SUPPORT"
    NO_OUTBOUND_SUPPORT = "NO_OUTBOUND_SUPPORT"
    ASSESSMENT_NOT_EMITTED_WITH_COMMON_SUPPORT = (
        "ASSESSMENT_NOT_EMITTED_WITH_COMMON_SUPPORT"
    )
    WATCHER_UNAVAILABLE = "WATCHER_UNAVAILABLE"
    POLICY_SAFE_ABOVE_WARNING_MARGIN = "POLICY_SAFE_ABOVE_WARNING_MARGIN"
    POLICY_INCONSISTENT = "POLICY_INCONSISTENT"
    OTHER = "OTHER"


@dataclass(frozen=True, slots=True)
class CausalLegDiagnostic:
    """One leg's causal support and latest-known quality at evaluation time."""

    causal_support_available: bool
    latest_support_timestamp: datetime | None
    latest_support_predicted_arrival: datetime | None
    latest_support_age_at_evaluation_min: float | None
    latest_support_data_quality: str | None
    latest_support_quality_reason_codes: tuple[str, ...]
    latest_known_timestamp: datetime | None
    latest_known_prediction_status: str | None
    latest_known_data_quality: str | None
    latest_known_quality_reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CausalRefinementDiagnostic:
    """A horizon diagnostic containing no final crossing or outcome field."""

    ucid: str
    scenario: str
    warning_margin_hours: float
    evaluation_horizon_hours: float
    evaluation_timestamp: datetime
    inbound_causal_support_available: bool
    outbound_causal_support_available: bool
    watcher_assessment_available: bool
    selected_assessment_timestamp: datetime | None
    selected_inbound_prediction_timestamp: datetime | None
    selected_outbound_prediction_timestamp: datetime | None
    selected_inbound_predicted_arrival: datetime | None
    selected_outbound_predicted_arrival: datetime | None
    inbound_prediction_age_at_assessment_min: float | None
    outbound_prediction_age_at_assessment_min: float | None
    inbound_latest_support_age_at_evaluation_min: float | None
    outbound_latest_support_age_at_evaluation_min: float | None
    current_plan_slack_hours: float | None
    no_itt_slack_hours: float | None
    watcher_state_under_margin: str | None
    watcher_alert_under_margin: bool | None
    baseline_alert: bool | None
    baseline_selected_inbound_prediction_timestamp: datetime | None
    baseline_delay_hours: float | None
    first_watcher_alert_at_or_before_evaluation: datetime | None
    first_baseline_alert_at_or_before_evaluation: datetime | None
    selected_assessment_reason_codes: tuple[str, ...]
    inbound_leg: CausalLegDiagnostic
    outbound_leg: CausalLegDiagnostic
    common_support: bool
    population_digest: str
    graph_output_digest: str


@dataclass(frozen=True, slots=True)
class RefinementDiagnosticRow:
    """A causal diagnostic joined afterward to evaluation-only information."""

    causal: CausalRefinementDiagnostic
    synthetic_cargo_cutoff: datetime
    retrospective_outcome: str
    retrospective_slack_hours: float
    retrospective_no_itt_slack_hours: float
    synthetic_prevention_opportunity: bool
    inbound_retrospective_benchmark_eligible: bool
    outbound_retrospective_benchmark_eligible: bool
    inbound_retrospective_exclusion_reasons: tuple[str, ...]
    outbound_retrospective_exclusion_reasons: tuple[str, ...]
    miss_reason: str | None


@dataclass(frozen=True, slots=True)
class StateTransitionCount:
    from_state: str
    to_state: str
    count: int


@dataclass(frozen=True, slots=True)
class ConnectionAlertChurn:
    ucid: str
    scenario: str
    warning_margin_hours: float
    available_assessments: int
    unavailable_assessments: int
    initial_alert: bool | None
    total_available_state_changes: int
    non_alert_to_alert_entries: int
    repeated_alert_entries: int
    recoveries_to_safe: int
    within_alert_escalations: int
    within_alert_deescalations: int
    transitions: tuple[StateTransitionCount, ...]


@dataclass(frozen=True, slots=True)
class DetectorSummary:
    detector: str
    scenario: str
    warning_margin_hours: float
    evaluation_horizon_hours: float
    end_to_end_support: int
    end_to_end_tp: int
    end_to_end_fp: int
    end_to_end_tn: int
    end_to_end_fn: int
    end_to_end_recall: float | None
    common_support: int
    common_support_tp: int
    common_support_fp: int
    common_support_tn: int
    common_support_fn: int
    common_support_recall: float | None


@dataclass(frozen=True, slots=True)
class MissReasonSummary:
    scenario: str
    warning_margin_hours: float
    evaluation_horizon_hours: float
    retrospectively_infeasible_not_alerted: int
    counts: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class PreventionOpportunitySummary:
    scenario: str
    warning_margin_hours: float
    evaluation_horizon_hours: float
    opportunity_count: int
    alerted_count: int
    recall: float | None
    common_support_opportunity_count: int
    common_support_alerted_count: int
    common_support_recall: float | None
    median_first_alert_lead_time_hours: float | None


@dataclass(frozen=True, slots=True)
class AlertChurnSummary:
    scenario: str
    warning_margin_hours: float
    connections: int
    connections_with_state_changes: int
    connections_with_repeated_alert_entries: int
    total_available_state_changes: int
    total_non_alert_to_alert_entries: int
    total_recoveries_to_safe: int
    total_within_alert_escalations: int
    total_within_alert_deescalations: int
    median_transitions_per_connection: float | None
    p90_transitions_per_connection: float | None
    maximum_transitions_per_connection: int | None


@dataclass(frozen=True, slots=True)
class ParentFreezeMetadata:
    parent_commit: str
    parent_report_version: str
    dataset_hash: str
    population_digest: str
    graph_output_digest: str
    ordered_ucid_digest: str
    outcome_digest: str


@dataclass(frozen=True, slots=True)
class RefinementExperimentDeclaration:
    requested_scenarios: tuple[str, ...]
    warning_margin_hours: tuple[float, ...]
    evaluation_horizon_hours: tuple[float, ...]
    baseline_threshold_minutes: float
    frozen_pr5_reference_margin_hours: float
    interpretation: str


@dataclass(frozen=True, slots=True)
class WatcherRefinementReport:
    report_version: str
    parent: ParentFreezeMetadata
    experiment: RefinementExperimentDeclaration
    diagnostics: tuple[RefinementDiagnosticRow, ...]
    detector_summaries: tuple[DetectorSummary, ...]
    miss_reason_summaries: tuple[MissReasonSummary, ...]
    prevention_opportunity_summaries: tuple[PreventionOpportunitySummary, ...]
    connection_alert_churn: tuple[ConnectionAlertChurn, ...]
    alert_churn_summaries: tuple[AlertChurnSummary, ...]
    invariant_warnings: tuple[str, ...]
    provenance: tuple[str, ...]
    limitations: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        payload = to_primitive(self)
        assert isinstance(payload, dict)
        return payload

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(
            self.as_dict(), ensure_ascii=False, indent=indent, sort_keys=True
        )


def _hours(value: timedelta) -> float:
    return value.total_seconds() / 3600.0


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _quantile(values: Iterable[float], probability: float) -> float | None:
    ordered = sorted(values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 12)


def _validate_margins(values: Iterable[timedelta]) -> tuple[timedelta, ...]:
    materialized = tuple(values)
    if not materialized:
        raise ValueError("at least one warning margin is required")
    if any(value < timedelta(0) for value in materialized):
        raise ValueError("warning margins must not be negative")
    if len(set(materialized)) != len(materialized):
        raise ValueError("warning margins must be unique")
    return materialized


def _validate_horizons(values: Iterable[timedelta]) -> tuple[timedelta, ...]:
    materialized = tuple(values)
    if not materialized:
        raise ValueError("at least one evaluation horizon is required")
    if any(value <= timedelta(0) for value in materialized):
        raise ValueError("evaluation horizons must be positive")
    if len(set(materialized)) != len(materialized):
        raise ValueError("evaluation horizons must be unique")
    return materialized


def _assert_frozen_replay_configuration(
    result: HistoricalEvaluationResult, scenario: ProcessScenario
) -> None:
    expected = canonical_digest(
        WatcherConfig(
            warning_margin=FROZEN_PR5_REFERENCE_MARGIN,
            reference_delay_threshold=FROZEN_BASELINE_THRESHOLD,
            process_scenario=scenario,
        )
    )
    unexpected = {
        record.watcher_config_digest
        for record in result.records
        if record.watcher_config_digest != expected
    }
    if unexpected:
        raise ValueError(
            "refinement input does not use the frozen PR #5 Watcher/baseline configuration"
        )


def classify_watcher_state(
    current_plan_slack_hours: float | None,
    warning_margin: timedelta,
) -> str | None:
    """Reclassify one already-causal slack value under an experimental margin."""

    if warning_margin < timedelta(0):
        raise ValueError("warning margin must not be negative")
    if current_plan_slack_hours is None:
        return None
    if current_plan_slack_hours <= 0:
        return RiskSeverity.AT_RISK.value
    if current_plan_slack_hours <= _hours(warning_margin):
        return RiskSeverity.WATCH.value
    return RiskSeverity.SAFE.value


def _state_alert(state: str | None) -> bool | None:
    if state is None:
        return None
    return state in (RiskSeverity.WATCH.value, RiskSeverity.AT_RISK.value)


def _assessment_key(
    record: HistoricalAssessmentRecord,
) -> tuple[datetime, object, str]:
    return record.assessed_at, record.trigger_cursor, record.trigger_source_call_id


def _selected_assessment(
    records: Iterable[HistoricalAssessmentRecord], evaluation_timestamp: datetime
) -> HistoricalAssessmentRecord | None:
    eligible = sorted(
        (record for record in records if record.assessed_at <= evaluation_timestamp),
        key=_assessment_key,
    )
    if not eligible:
        return None
    selected = eligible[-1]
    key = _assessment_key(selected)
    if any(_assessment_key(item) == key and item != selected for item in eligible):
        raise ValueError("conflicting historical assessments share a selection key")
    return selected


def _latest_known(
    updates: Iterable[CausalArrivalUpdate], evaluation_timestamp: datetime
) -> CausalArrivalUpdate | None:
    eligible = sorted(
        (item for item in updates if item.observed_at <= evaluation_timestamp),
        key=update_cursor,
    )
    if not eligible:
        return None
    selected = eligible[-1]
    key = update_cursor(selected)
    if any(update_cursor(item) == key and item != selected for item in eligible):
        raise ValueError("conflicting causal updates share a replay cursor")
    return selected


def _latest_support(
    updates: Iterable[CausalArrivalUpdate], evaluation_timestamp: datetime
) -> CausalArrivalUpdate | None:
    eligible = sorted(
        (
            item
            for item in updates
            if item.observed_at <= evaluation_timestamp
            and item.prediction_status is PredictionStatus.AVAILABLE
            and item.predicted_arrival is not None
            and item.reference_arrival is not None
        ),
        key=update_cursor,
    )
    return eligible[-1] if eligible else None


def _leg_diagnostic(
    updates: Iterable[CausalArrivalUpdate], evaluation_timestamp: datetime
) -> CausalLegDiagnostic:
    materialized = tuple(updates)
    support = _latest_support(materialized, evaluation_timestamp)
    known = _latest_known(materialized, evaluation_timestamp)
    return CausalLegDiagnostic(
        causal_support_available=support is not None,
        latest_support_timestamp=(support.observed_at if support is not None else None),
        latest_support_predicted_arrival=(
            support.predicted_arrival if support is not None else None
        ),
        latest_support_age_at_evaluation_min=(
            (evaluation_timestamp - support.observed_at).total_seconds() / 60.0
            if support is not None
            else None
        ),
        latest_support_data_quality=(
            support.data_quality.value if support is not None else None
        ),
        latest_support_quality_reason_codes=(
            support.quality_reason_codes if support is not None else ()
        ),
        latest_known_timestamp=(known.observed_at if known is not None else None),
        latest_known_prediction_status=(
            known.prediction_status.value if known is not None else None
        ),
        latest_known_data_quality=(
            known.data_quality.value if known is not None else None
        ),
        latest_known_quality_reason_codes=(
            known.quality_reason_codes if known is not None else ()
        ),
    )


def _first_alert(
    records: Iterable[HistoricalAssessmentRecord],
    evaluation_timestamp: datetime,
    *,
    warning_margin: timedelta | None,
) -> datetime | None:
    for record in sorted(records, key=_assessment_key):
        if record.assessed_at > evaluation_timestamp:
            break
        if warning_margin is None:
            alert = record.baseline_alert if record.baseline_available else None
        elif record.status != AssessmentStatus.AVAILABLE.value:
            alert = None
        else:
            alert = _state_alert(
                classify_watcher_state(record.current_plan_slack_h, warning_margin)
            )
        if alert is True:
            return record.assessed_at
    return None


def _assert_common_support_baseline(record: HistoricalAssessmentRecord) -> None:
    if not record.baseline_available:
        raise CommonSupportInvariantError(
            "common-support Watcher assessment has no baseline result"
        )
    if (
        record.baseline_prediction_observed_at
        != record.inbound_prediction_observed_at
    ):
        raise CommonSupportInvariantError(
            "baseline and Watcher selected different inbound predictions"
        )


def build_causal_refinement_diagnostic(
    result: HistoricalEvaluationResult,
    *,
    ucid: str,
    scenario: ProcessScenario,
    warning_margin: timedelta,
    evaluation_horizon: timedelta,
    evaluation_timestamp: datetime,
    record_index: HistoricalRecordsByUcid | None = None,
) -> CausalRefinementDiagnostic:
    """Build one causal row using only replay updates known by the horizon."""

    if evaluation_timestamp.tzinfo is None or evaluation_timestamp.utcoffset() is None:
        raise ValueError("evaluation_timestamp must be timezone-aware")
    if warning_margin < timedelta(0):
        raise ValueError("warning margin must not be negative")
    if evaluation_horizon <= timedelta(0):
        raise ValueError("evaluation horizon must be positive")
    connections = {
        connection.identity.ucid: connection
        for connection in result.benchmark.connections
    }
    if ucid not in connections:
        raise ValueError(f"unknown benchmark UCID: {ucid}")
    connection = connections[ucid]
    assignment = connection.assignment
    calls = {call.call_id: call for call in result.population.replay_calls}
    inbound_call = calls[assignment.inbound_source_call_id]
    outbound_call = calls[assignment.outbound_source_call_id]
    inbound_leg = _leg_diagnostic(inbound_call.updates, evaluation_timestamp)
    outbound_leg = _leg_diagnostic(outbound_call.updates, evaluation_timestamp)
    index = record_index if record_index is not None else records_by_ucid(result.records)
    ucid_records = index.get(ucid, ())
    selected = _selected_assessment(ucid_records, evaluation_timestamp)
    available = (
        selected is not None
        and selected.status == AssessmentStatus.AVAILABLE.value
    )
    slack = selected.current_plan_slack_h if available else None
    state = classify_watcher_state(slack, warning_margin) if available else None
    alert = _state_alert(state) if available else None
    common_support = (
        inbound_leg.causal_support_available
        and outbound_leg.causal_support_available
        and available
    )
    if common_support:
        assert selected is not None
        _assert_common_support_baseline(selected)
    return CausalRefinementDiagnostic(
        ucid=ucid,
        scenario=scenario.value,
        warning_margin_hours=_hours(warning_margin),
        evaluation_horizon_hours=_hours(evaluation_horizon),
        evaluation_timestamp=evaluation_timestamp,
        inbound_causal_support_available=inbound_leg.causal_support_available,
        outbound_causal_support_available=outbound_leg.causal_support_available,
        watcher_assessment_available=available,
        selected_assessment_timestamp=(
            selected.assessed_at if selected is not None else None
        ),
        selected_inbound_prediction_timestamp=(
            selected.inbound_prediction_observed_at if selected is not None else None
        ),
        selected_outbound_prediction_timestamp=(
            selected.outbound_prediction_observed_at if selected is not None else None
        ),
        selected_inbound_predicted_arrival=(
            selected.inbound_predicted_arrival if selected is not None else None
        ),
        selected_outbound_predicted_arrival=(
            selected.outbound_predicted_arrival if selected is not None else None
        ),
        inbound_prediction_age_at_assessment_min=(
            selected.inbound_prediction_age_min if selected is not None else None
        ),
        outbound_prediction_age_at_assessment_min=(
            selected.outbound_prediction_age_min if selected is not None else None
        ),
        inbound_latest_support_age_at_evaluation_min=(
            inbound_leg.latest_support_age_at_evaluation_min
        ),
        outbound_latest_support_age_at_evaluation_min=(
            outbound_leg.latest_support_age_at_evaluation_min
        ),
        current_plan_slack_hours=(
            selected.current_plan_slack_h if selected is not None else None
        ),
        no_itt_slack_hours=(
            selected.no_itt_slack_h if selected is not None else None
        ),
        watcher_state_under_margin=state,
        watcher_alert_under_margin=alert,
        baseline_alert=(
            selected.baseline_alert
            if selected is not None and selected.baseline_available
            else None
        ),
        baseline_selected_inbound_prediction_timestamp=(
            selected.baseline_prediction_observed_at if selected is not None else None
        ),
        baseline_delay_hours=(
            selected.baseline_delay_h if selected is not None else None
        ),
        first_watcher_alert_at_or_before_evaluation=_first_alert(
            ucid_records,
            evaluation_timestamp,
            warning_margin=warning_margin,
        ),
        first_baseline_alert_at_or_before_evaluation=_first_alert(
            ucid_records,
            evaluation_timestamp,
            warning_margin=None,
        ),
        selected_assessment_reason_codes=(
            selected.reason_codes if selected is not None else ()
        ),
        inbound_leg=inbound_leg,
        outbound_leg=outbound_leg,
        common_support=common_support,
        population_digest=result.population.population_digest,
        graph_output_digest=result.benchmark.manifest.output_digest,
    )


def synthetic_prevention_opportunity(
    outcome: RetrospectiveConnectionOutcome,
) -> bool:
    """Evaluation-only synthetic no-ITT counterfactual; never a real rescue."""

    expected = (
        outcome.transfer_duration > timedelta(0)
        and outcome.retrospective_slack <= timedelta(0)
        and outcome.retrospective_no_itt_slack > timedelta(0)
    )
    if expected != outcome.synthetic_terminal_prevention_opportunity:
        raise ValueError("retrospective prevention-opportunity label is inconsistent")
    return expected


def classify_miss_reason(
    causal: CausalRefinementDiagnostic,
    outcome: RetrospectiveConnectionOutcome,
) -> MissReason | None:
    """Assign one ordered primary reason to an infeasible non-alerted case."""

    if outcome.feasibility is not SyntheticScenarioFeasibility.INFEASIBLE:
        return None
    if causal.watcher_alert_under_margin is True:
        return None
    inbound = causal.inbound_causal_support_available
    outbound = causal.outbound_causal_support_available
    if not inbound and not outbound:
        return MissReason.NO_EITHER_LEG_SUPPORT
    if not inbound:
        return MissReason.NO_INBOUND_SUPPORT
    if not outbound:
        return MissReason.NO_OUTBOUND_SUPPORT
    if causal.selected_assessment_timestamp is None:
        return MissReason.ASSESSMENT_NOT_EMITTED_WITH_COMMON_SUPPORT
    if not causal.watcher_assessment_available:
        return MissReason.WATCHER_UNAVAILABLE
    slack = causal.current_plan_slack_hours
    expected_state = classify_watcher_state(
        slack, timedelta(hours=causal.warning_margin_hours)
    )
    expected_alert = _state_alert(expected_state)
    if (
        causal.watcher_state_under_margin != expected_state
        or causal.watcher_alert_under_margin != expected_alert
    ):
        return MissReason.POLICY_INCONSISTENT
    if (
        slack is not None
        and slack > causal.warning_margin_hours
        and causal.watcher_state_under_margin == RiskSeverity.SAFE.value
    ):
        return MissReason.POLICY_SAFE_ABOVE_WARNING_MARGIN
    if slack is None or expected_state is None or expected_alert is None:
        return MissReason.POLICY_INCONSISTENT
    if slack <= causal.warning_margin_hours:
        return MissReason.POLICY_INCONSISTENT
    return MissReason.OTHER


def join_retrospective_evaluation(
    causal: CausalRefinementDiagnostic,
    outcome: RetrospectiveConnectionOutcome,
    *,
    result: HistoricalEvaluationResult,
) -> RefinementDiagnosticRow:
    """Join final-crossing information only after the causal row is complete."""

    if causal.ucid != outcome.ucid or not outcome.process_assumption_id.endswith(
        f":{causal.scenario}"
    ):
        raise ValueError("causal diagnostic and retrospective outcome do not match")
    retrospective = {
        call.call_id: call.final_event
        for call in result.population.retrospective_calls
    }
    inbound = retrospective[outcome.inbound_source_call_id]
    outbound = retrospective[outcome.outbound_source_call_id]
    reason = classify_miss_reason(causal, outcome)
    return RefinementDiagnosticRow(
        causal=causal,
        synthetic_cargo_cutoff=outcome.retrospective_outbound_cutoff,
        retrospective_outcome=outcome.feasibility.value,
        retrospective_slack_hours=outcome.retrospective_slack_h,
        retrospective_no_itt_slack_hours=outcome.retrospective_no_itt_slack_h,
        synthetic_prevention_opportunity=synthetic_prevention_opportunity(outcome),
        inbound_retrospective_benchmark_eligible=inbound.benchmark_eligible,
        outbound_retrospective_benchmark_eligible=outbound.benchmark_eligible,
        inbound_retrospective_exclusion_reasons=inbound.exclusion_reasons,
        outbound_retrospective_exclusion_reasons=outbound.exclusion_reasons,
        miss_reason=reason.value if reason is not None else None,
    )


def build_refinement_diagnostics(
    result: HistoricalEvaluationResult,
    *,
    scenario: ProcessScenario,
    warning_margins: Iterable[timedelta] = EXPERIMENTAL_WARNING_MARGINS,
    evaluation_horizons: Iterable[timedelta] = FROZEN_EVALUATION_HORIZONS,
) -> tuple[RefinementDiagnosticRow, ...]:
    """Build scenario × margin × horizon × UCID rows in declaration order."""

    margins = _validate_margins(warning_margins)
    horizons = _validate_horizons(evaluation_horizons)
    if any(record.process_scenario != scenario.value for record in result.records):
        raise ValueError("assessment records do not match the requested scenario")
    _assert_frozen_replay_configuration(result, scenario)
    outcome_set = build_retrospective_outcomes(result, scenario=scenario)
    outcome_by_ucid = {item.ucid: item for item in outcome_set.outcomes}
    ordered_ucids = tuple(
        connection.identity.ucid for connection in result.benchmark.connections
    )
    if set(outcome_by_ucid) != set(ordered_ucids):
        raise ValueError(
            "refinement diagnostics require a retrospective outcome for every UCID"
        )
    index = records_by_ucid(result.records)
    rows: list[RefinementDiagnosticRow] = []
    for margin in margins:
        for horizon in horizons:
            for ucid in ordered_ucids:
                outcome = outcome_by_ucid[ucid]
                evaluation_timestamp = (
                    outcome.retrospective_outbound_cutoff - horizon
                )
                causal = build_causal_refinement_diagnostic(
                    result,
                    ucid=ucid,
                    scenario=scenario,
                    warning_margin=margin,
                    evaluation_horizon=horizon,
                    evaluation_timestamp=evaluation_timestamp,
                    record_index=index,
                )
                rows.append(
                    join_retrospective_evaluation(causal, outcome, result=result)
                )
    return tuple(rows)


_TRANSITION_ORDER = (
    (RiskSeverity.SAFE.value, RiskSeverity.WATCH.value),
    (RiskSeverity.WATCH.value, RiskSeverity.SAFE.value),
    (RiskSeverity.WATCH.value, RiskSeverity.AT_RISK.value),
    (RiskSeverity.AT_RISK.value, RiskSeverity.WATCH.value),
    (RiskSeverity.AT_RISK.value, RiskSeverity.SAFE.value),
    (RiskSeverity.SAFE.value, RiskSeverity.AT_RISK.value),
)


def calculate_connection_alert_churn(
    records: Iterable[HistoricalAssessmentRecord],
    *,
    ucid: str,
    scenario: ProcessScenario,
    warning_margin: timedelta,
    cutoff: datetime,
) -> ConnectionAlertChurn:
    """Measure state changes across AVAILABLE rows; unavailable is never SAFE."""

    ordered = tuple(
        sorted(
            (
                record
                for record in records
                if record.ucid == ucid and record.assessed_at <= cutoff
            ),
            key=_assessment_key,
        )
    )
    unavailable = sum(
        record.status != AssessmentStatus.AVAILABLE.value for record in ordered
    )
    states = tuple(
        classify_watcher_state(record.current_plan_slack_h, warning_margin)
        for record in ordered
        if record.status == AssessmentStatus.AVAILABLE.value
    )
    if any(state is None for state in states):
        raise ValueError("available assessment is missing causal slack")
    transitions = Counter(zip(states, states[1:]))
    initial_alert = _state_alert(states[0]) if states else None
    changes = sum(before != after for before, after in transitions.elements())
    entries = sum(
        count
        for (before, after), count in transitions.items()
        if _state_alert(before) is False and _state_alert(after) is True
    )
    recoveries = sum(
        count
        for (before, after), count in transitions.items()
        if _state_alert(before) is True and after == RiskSeverity.SAFE.value
    )
    return ConnectionAlertChurn(
        ucid=ucid,
        scenario=scenario.value,
        warning_margin_hours=_hours(warning_margin),
        available_assessments=len(states),
        unavailable_assessments=unavailable,
        initial_alert=initial_alert,
        total_available_state_changes=changes,
        non_alert_to_alert_entries=entries,
        repeated_alert_entries=max(entries - (0 if initial_alert else 1), 0),
        recoveries_to_safe=recoveries,
        within_alert_escalations=transitions[
            (RiskSeverity.WATCH.value, RiskSeverity.AT_RISK.value)
        ],
        within_alert_deescalations=transitions[
            (RiskSeverity.AT_RISK.value, RiskSeverity.WATCH.value)
        ],
        transitions=tuple(
            StateTransitionCount(before, after, transitions[(before, after)])
            for before, after in _TRANSITION_ORDER
        ),
    )


def build_alert_churn(
    result: HistoricalEvaluationResult,
    *,
    scenario: ProcessScenario,
    warning_margins: Iterable[timedelta] = EXPERIMENTAL_WARNING_MARGINS,
) -> tuple[ConnectionAlertChurn, ...]:
    margins = _validate_margins(warning_margins)
    outcomes = build_retrospective_outcomes(result, scenario=scenario).outcomes
    outcome_by_ucid = {item.ucid: item for item in outcomes}
    return tuple(
        calculate_connection_alert_churn(
            result.records,
            ucid=connection.identity.ucid,
            scenario=scenario,
            warning_margin=margin,
            cutoff=outcome_by_ucid[
                connection.identity.ucid
            ].retrospective_outbound_cutoff,
        )
        for margin in margins
        for connection in result.benchmark.connections
    )


def _group_rows(
    rows: Iterable[RefinementDiagnosticRow],
) -> Mapping[tuple[str, float, float], tuple[RefinementDiagnosticRow, ...]]:
    grouped: dict[tuple[str, float, float], list[RefinementDiagnosticRow]] = {}
    for row in rows:
        causal = row.causal
        key = (
            causal.scenario,
            causal.warning_margin_hours,
            causal.evaluation_horizon_hours,
        )
        grouped.setdefault(key, []).append(row)
    return MappingProxyType({key: tuple(value) for key, value in grouped.items()})


def _detector_summary(
    key: tuple[str, float, float],
    rows: tuple[RefinementDiagnosticRow, ...],
    *,
    detector: str,
) -> DetectorSummary:
    if detector not in ("watcher", "reference_delay_baseline"):
        raise ValueError(f"unknown detector: {detector}")

    def alert_for(row: RefinementDiagnosticRow) -> bool:
        if detector == "watcher":
            return row.causal.watcher_alert_under_margin is True
        return row.causal.baseline_alert is True

    def counts(values: Iterable[RefinementDiagnosticRow]) -> tuple[int, int, int, int]:
        tp = fp = tn = fn = 0
        for row in values:
            actual = row.retrospective_outcome == SyntheticScenarioFeasibility.INFEASIBLE.value
            alert = alert_for(row)
            if actual and alert:
                tp += 1
            elif actual:
                fn += 1
            elif alert:
                fp += 1
            else:
                tn += 1
        return tp, fp, tn, fn

    end = counts(rows)
    common_rows = tuple(row for row in rows if row.causal.common_support)
    common = counts(common_rows)
    return DetectorSummary(
        detector=detector,
        scenario=key[0],
        warning_margin_hours=key[1],
        evaluation_horizon_hours=key[2],
        end_to_end_support=len(rows),
        end_to_end_tp=end[0],
        end_to_end_fp=end[1],
        end_to_end_tn=end[2],
        end_to_end_fn=end[3],
        end_to_end_recall=_ratio(end[0], end[0] + end[3]),
        common_support=len(common_rows),
        common_support_tp=common[0],
        common_support_fp=common[1],
        common_support_tn=common[2],
        common_support_fn=common[3],
        common_support_recall=_ratio(common[0], common[0] + common[3]),
    )


def _miss_summary(
    key: tuple[str, float, float], rows: tuple[RefinementDiagnosticRow, ...]
) -> MissReasonSummary:
    reasons = Counter(row.miss_reason for row in rows if row.miss_reason is not None)
    return MissReasonSummary(
        scenario=key[0],
        warning_margin_hours=key[1],
        evaluation_horizon_hours=key[2],
        retrospectively_infeasible_not_alerted=sum(reasons.values()),
        counts=tuple(
            (reason.value, reasons.get(reason.value, 0)) for reason in MissReason
        ),
    )


def _prevention_summary(
    key: tuple[str, float, float], rows: tuple[RefinementDiagnosticRow, ...]
) -> PreventionOpportunitySummary:
    opportunities = tuple(row for row in rows if row.synthetic_prevention_opportunity)
    caught = tuple(
        row for row in opportunities if row.causal.watcher_alert_under_margin is True
    )
    common = tuple(row for row in opportunities if row.causal.common_support)
    common_caught = tuple(
        row for row in common if row.causal.watcher_alert_under_margin is True
    )
    lead_times = (
        (
            row.synthetic_cargo_cutoff
            - row.causal.first_watcher_alert_at_or_before_evaluation
        ).total_seconds()
        / 3600.0
        for row in caught
        if row.causal.first_watcher_alert_at_or_before_evaluation is not None
    )
    return PreventionOpportunitySummary(
        scenario=key[0],
        warning_margin_hours=key[1],
        evaluation_horizon_hours=key[2],
        opportunity_count=len(opportunities),
        alerted_count=len(caught),
        recall=_ratio(len(caught), len(opportunities)),
        common_support_opportunity_count=len(common),
        common_support_alerted_count=len(common_caught),
        common_support_recall=_ratio(len(common_caught), len(common)),
        median_first_alert_lead_time_hours=_quantile(lead_times, 0.5),
    )


def _churn_summary(
    scenario: str,
    margin: float,
    values: tuple[ConnectionAlertChurn, ...],
) -> AlertChurnSummary:
    transition_counts = tuple(
        item.total_available_state_changes for item in values
    )
    return AlertChurnSummary(
        scenario=scenario,
        warning_margin_hours=margin,
        connections=len(values),
        connections_with_state_changes=sum(
            item.total_available_state_changes > 0 for item in values
        ),
        connections_with_repeated_alert_entries=sum(
            item.repeated_alert_entries > 0 for item in values
        ),
        total_available_state_changes=sum(
            item.total_available_state_changes for item in values
        ),
        total_non_alert_to_alert_entries=sum(
            item.non_alert_to_alert_entries for item in values
        ),
        total_recoveries_to_safe=sum(item.recoveries_to_safe for item in values),
        total_within_alert_escalations=sum(
            item.within_alert_escalations for item in values
        ),
        total_within_alert_deescalations=sum(
            item.within_alert_deescalations for item in values
        ),
        median_transitions_per_connection=_quantile(transition_counts, 0.5),
        p90_transitions_per_connection=_quantile(transition_counts, 0.9),
        maximum_transitions_per_connection=max(transition_counts, default=None),
    )


def build_watcher_refinement_report(
    scenario_results: Iterable[HistoricalEvaluationResult],
    *,
    dataset_hash: str,
    warning_margins: Iterable[timedelta] = EXPERIMENTAL_WARNING_MARGINS,
    evaluation_horizons: Iterable[timedelta] = FROZEN_EVALUATION_HORIZONS,
) -> WatcherRefinementReport:
    """Build the deterministic Phase 1 model without writing an artifact."""

    results = tuple(scenario_results)
    if not results:
        raise ValueError("at least one scenario result is required")
    margins = _validate_margins(warning_margins)
    horizons = _validate_horizons(evaluation_horizons)
    first = results[0]
    if any(
        result.population != first.population or result.benchmark != first.benchmark
        for result in results[1:]
    ):
        raise ValueError("refinement scenarios must share one population and graph")
    scenario_pairs: list[tuple[ProcessScenario, HistoricalEvaluationResult]] = []
    seen: set[ProcessScenario] = set()
    for result in results:
        names = {record.process_scenario for record in result.records}
        if len(names) != 1:
            raise ValueError("each replay result must contain exactly one scenario")
        scenario = ProcessScenario(next(iter(names)))
        if scenario in seen:
            raise ValueError(f"duplicate scenario result: {scenario.value}")
        seen.add(scenario)
        scenario_pairs.append((scenario, result))
    diagnostics = tuple(
        row
        for scenario, result in scenario_pairs
        for row in build_refinement_diagnostics(
            result,
            scenario=scenario,
            warning_margins=margins,
            evaluation_horizons=horizons,
        )
    )
    churn = tuple(
        row
        for scenario, result in scenario_pairs
        for row in build_alert_churn(
            result, scenario=scenario, warning_margins=margins
        )
    )
    groups = _group_rows(diagnostics)
    group_order = tuple(
        (scenario.value, _hours(margin), _hours(horizon))
        for scenario, _ in scenario_pairs
        for margin in margins
        for horizon in horizons
    )
    churn_by_policy: dict[tuple[str, float], list[ConnectionAlertChurn]] = {}
    for item in churn:
        churn_by_policy.setdefault(
            (item.scenario, item.warning_margin_hours), []
        ).append(item)
    ordered_ucids = tuple(
        connection.identity.ucid for connection in first.benchmark.connections
    )
    outcome_payload = tuple(
        build_retrospective_outcomes(result, scenario=scenario).outcomes
        for scenario, result in scenario_pairs
    )
    return WatcherRefinementReport(
        report_version=WATCHER_REFINEMENT_REPORT_VERSION,
        parent=ParentFreezeMetadata(
            parent_commit=PR5_PARENT_COMMIT,
            parent_report_version=HISTORICAL_REPORT_VERSION,
            dataset_hash=dataset_hash,
            population_digest=first.population.population_digest,
            graph_output_digest=first.benchmark.manifest.output_digest,
            ordered_ucid_digest=canonical_digest(ordered_ucids),
            outcome_digest=canonical_digest(outcome_payload),
        ),
        experiment=RefinementExperimentDeclaration(
            requested_scenarios=tuple(
                scenario.value for scenario, _ in scenario_pairs
            ),
            warning_margin_hours=tuple(map(_hours, margins)),
            evaluation_horizon_hours=tuple(map(_hours, horizons)),
            baseline_threshold_minutes=(
                FROZEN_BASELINE_THRESHOLD.total_seconds() / 60.0
            ),
            frozen_pr5_reference_margin_hours=_hours(
                FROZEN_PR5_REFERENCE_MARGIN
            ),
            interpretation=(
                "Predeclared experimental sensitivity values; not PSA or industry thresholds."
            ),
        ),
        diagnostics=diagnostics,
        detector_summaries=tuple(
            _detector_summary(key, groups[key], detector=detector)
            for key in group_order
            for detector in ("watcher", "reference_delay_baseline")
        ),
        miss_reason_summaries=tuple(
            _miss_summary(key, groups[key]) for key in group_order
        ),
        prevention_opportunity_summaries=tuple(
            _prevention_summary(key, groups[key]) for key in group_order
        ),
        connection_alert_churn=churn,
        alert_churn_summaries=tuple(
            _churn_summary(
                scenario.value,
                _hours(margin),
                tuple(churn_by_policy[(scenario.value, _hours(margin))]),
            )
            for scenario, _ in scenario_pairs
            for margin in margins
        ),
        invariant_warnings=tuple(
            f"{row.causal.scenario}:{row.causal.warning_margin_hours:g}h:"
            f"{row.causal.evaluation_horizon_hours:g}h:{row.causal.ucid}:"
            f"{row.miss_reason}"
            for row in diagnostics
            if row.miss_reason
            in (
                MissReason.ASSESSMENT_NOT_EMITTED_WITH_COMMON_SUPPORT.value,
                MissReason.POLICY_INCONSISTENT.value,
            )
        ),
        provenance=(
            f"PR #5 experiment reference commit: {PR5_PARENT_COMMIT}.",
            "Causal diagnostics use only updates observed by the evaluation timestamp.",
            "Retrospective outcomes and prevention labels are joined only after causal diagnostics exist.",
            "All margins reuse one immutable source population, graph, UCID order, causal slack stream, and baseline.",
        ),
        limitations=(
            "Warning margins are experimental sensitivity values, not PSA or industry thresholds.",
            "Synthetic prevention opportunities are counterfactual benchmark labels, not real rescued containers or saved connections.",
            "No preferred, winning, recommended, or optimal margin is selected.",
        ),
    )


def validate_refinement_output_path(path: str | Path) -> Path:
    target = Path(path)
    if target.suffix.lower() != ".json":
        raise ValueError("watcher refinement output must end in .json")
    lowered = target.name.lower()
    if "historical-watcher-report" in lowered or HISTORICAL_REPORT_VERSION in lowered:
        raise ValueError("PR #6 output must not target a PR #5 report path")
    normalized = target.as_posix().lower()
    if lowered == "readme.md" or normalized.endswith(
        "data inspection/singapore_ais_dataset_assessment.md"
    ):
        raise ValueError("PR #6 output must not target PR #5 evidence")
    if "/fixtures/synthetic/" in f"/{normalized}":
        raise ValueError("PR #6 output must not target PR #3 fixtures")
    if target.exists():
        if not target.is_file():
            raise ValueError("watcher refinement output must be a JSON file")
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ValueError(
                "watcher refinement output will not overwrite an unrelated file"
            ) from None
        required = {
            "report_version",
            "parent",
            "experiment",
            "diagnostics",
            "detector_summaries",
            "connection_alert_churn",
            "alert_churn_summaries",
            "provenance",
            "limitations",
        }
        if not isinstance(payload, dict) or not required <= payload.keys():
            raise ValueError(
                "watcher refinement output will not overwrite an unrelated JSON file"
            )
        if payload.get("report_version") != WATCHER_REFINEMENT_REPORT_VERSION:
            raise ValueError(
                "watcher refinement output will not overwrite another report contract"
            )
    return target


def write_watcher_refinement_report(
    report: WatcherRefinementReport, path: str | Path
) -> None:
    """Write only to an explicit non-PR-#5 target; no directory is implied."""

    target = validate_refinement_output_path(path)
    target.write_text(report.to_json(indent=2) + "\n", encoding="utf-8")
