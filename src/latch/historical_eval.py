"""Causal historical evaluation of the PR #3 graph with the PR #4 Watcher.

The benchmark population is retrospectively constructed from PR #2's
reset-confirmed, derived geofence-crossing calls.  That permits repeatable
historical evaluation, but it is not live call discovery.  In particular,
causal connection activation prevents the finished graph from revealing a
future source candidate before both of its first-available real AIS
observations have been replayed.

Retrospective ``DerivedArrivalEvent`` values are retained beside, never inside,
the causal replay state.  Only after replay completes are their final derived
crossings used to construct synthetic process-scenario outcomes for evaluation.
Those outcomes score the recorded Watcher assessments and their embedded
derived reference-delay baseline; they are never Watcher inputs and are never
sent to the agent.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Mapping

from latch.events import RiskSeverity
from latch.models import Terminal
from latch.replay import (
    CausalArrivalUpdate,
    DerivedArrivalEvent,
    ReplayConfig,
    derive_arrival_calls,
)
from latch.synthetic import (
    TOPOLOGY_VERSION,
    BenchmarkQuota,
    DifficultyThresholds,
    ImpactBand,
    ProcessAssumptions,
    ProcessScenario,
    SyntheticBenchmark,
    SyntheticBenchmarkConfig,
    SyntheticConnection,
    TransferMode,
    approved_assumption_register,
    canonical_digest,
    to_primitive,
    generate_synthetic_benchmark,
)
from latch.watcher import (
    AssessmentStatus,
    ConnectionRiskAssessment,
    WatcherConfig,
    assess_connection,
)


HISTORICAL_POPULATION_VERSION = "historical-watcher-bounded-population-v1"
HISTORICAL_CONFIG_VERSION = "historical-watcher-synthetic-config-v1"
DEFAULT_SOURCE_CALL_LIMIT = 256
MAX_SOURCE_CALL_LIMIT = 256
DEFAULT_CONNECTIONS_PER_QUOTA = 8
RETROSPECTIVE_OUTCOME_VERSION = "retrospective-synthetic-outcome-v1"
HISTORICAL_REPORT_VERSION = "historical-watcher-report-v2"
DEFAULT_EVALUATION_HORIZONS = (
    timedelta(hours=6),
    timedelta(hours=3),
    timedelta(hours=1),
)
DEFAULT_CHURN_DIAGNOSTIC_THRESHOLD = 4


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True, slots=True, order=True)
class ReplayCursor:
    """Exact deterministic replay position, including source-row tie breaks."""

    observed_at: datetime
    source_row_number: int
    call_id: str

    def __post_init__(self) -> None:
        _require_aware(self.observed_at, "observed_at")
        if self.source_row_number < 1:
            raise ValueError("source_row_number must be positive")
        if not self.call_id:
            raise ValueError("call_id must not be empty")


def update_cursor(update: CausalArrivalUpdate) -> ReplayCursor:
    return ReplayCursor(
        update.observed_at,
        update.source_observation.source_row_number,
        update.call_id,
    )


@dataclass(frozen=True, slots=True)
class CausalReplayCall:
    """Live-side values for one retrospectively segmented PR #2 call."""

    call_id: str
    vessel_id: str
    updates: tuple[CausalArrivalUpdate, ...]

    def __post_init__(self) -> None:
        if not self.updates:
            raise ValueError("causal replay calls must contain at least one update")
        if any(update.call_id != self.call_id for update in self.updates):
            raise ValueError("causal replay call contains a different source call ID")
        if any(update.vessel_id != self.vessel_id for update in self.updates):
            raise ValueError("causal replay call contains a different vessel ID")


@dataclass(frozen=True, slots=True)
class RetrospectiveCallData:
    """Evaluation-only final event, structurally outside the live replay call."""

    call_id: str
    final_event: DerivedArrivalEvent

    def __post_init__(self) -> None:
        if self.final_event.call_id != self.call_id:
            raise ValueError("retrospective event does not match its source call ID")


@dataclass(frozen=True, slots=True)
class HistoricalPopulationConfig:
    """Explicit deterministic bound around quadratic PR #3 pair generation."""

    source_call_limit: int = DEFAULT_SOURCE_CALL_LIMIT
    population_version: str = HISTORICAL_POPULATION_VERSION

    def __post_init__(self) -> None:
        if self.source_call_limit < 2:
            raise ValueError("source_call_limit must be at least two")
        if self.source_call_limit > MAX_SOURCE_CALL_LIMIT:
            raise ValueError(
                "source_call_limit exceeds the explicit quadratic-generator "
                f"safety bound of {MAX_SOURCE_CALL_LIMIT}"
            )
        if not self.population_version.strip():
            raise ValueError("population_version must not be empty")


@dataclass(frozen=True, slots=True)
class HistoricalCallPopulation:
    """Separate live and evaluation-only views of the bounded call population."""

    config: HistoricalPopulationConfig
    accepted_call_count: int
    replay_calls: tuple[CausalReplayCall, ...]
    retrospective_calls: tuple[RetrospectiveCallData, ...]
    population_digest: str

    @property
    def selected_call_ids(self) -> tuple[str, ...]:
        return tuple(call.call_id for call in self.replay_calls)


def _causal_call(event: DerivedArrivalEvent) -> CausalReplayCall | None:
    if not event.arrival_updates:
        return None
    updates = tuple(sorted(event.arrival_updates, key=update_cursor))
    return CausalReplayCall(event.call_id, event.vessel_id, updates)


def build_call_population(
    calls: Iterable[DerivedArrivalEvent],
    config: HistoricalPopulationConfig = HistoricalPopulationConfig(),
) -> HistoricalCallPopulation:
    """Select a declared prefix using causal update order, never outcome quality.

    All inputs must already be PR #2 accepted/reset-confirmed calls.  The bound
    is applied after sorting by each call's first chronological update.  Final
    crossing time, benchmark eligibility, exclusions, and call-level quality
    do not select or order the live population.
    """

    materialized = tuple(calls)
    replay_by_id: dict[str, CausalReplayCall] = {}
    event_by_id: dict[str, DerivedArrivalEvent] = {}
    for event in materialized:
        if event.call_id in event_by_id:
            raise ValueError(f"duplicate accepted source call ID: {event.call_id}")
        event_by_id[event.call_id] = event
        replay_call = _causal_call(event)
        if replay_call is not None:
            replay_by_id[event.call_id] = replay_call

    ordered = sorted(
        replay_by_id.values(),
        key=lambda call: (update_cursor(call.updates[0]), call.call_id),
    )
    selected = tuple(ordered[: config.source_call_limit])
    retrospective = tuple(
        RetrospectiveCallData(call.call_id, event_by_id[call.call_id])
        for call in selected
    )
    population_digest = canonical_digest(
        {
            "population_version": config.population_version,
            "source_call_limit": config.source_call_limit,
            "selected_call_ids": tuple(call.call_id for call in selected),
            "causal_update_digest": canonical_digest(
                tuple(update for call in selected for update in call.updates)
            ),
        }
    )
    return HistoricalCallPopulation(
        config=config,
        accepted_call_count=len(materialized),
        replay_calls=selected,
        retrospective_calls=retrospective,
        population_digest=population_digest,
    )


def historical_synthetic_config(
    *,
    dataset_sha256: str,
    connections_per_quota: int = DEFAULT_CONNECTIONS_PER_QUOTA,
) -> SyntheticBenchmarkConfig:
    """Frozen historical configuration, distinct from PR #3's tiny fixture.

    The four broad quota cells and process values are synthetic process
    assumptions for a bounded benchmark.  They are not prevalence estimates,
    PSA operating rules, official schedules, or terminal outcomes.
    """

    if connections_per_quota < 1:
        raise ValueError("connections_per_quota must be positive")
    quotas = (
        BenchmarkQuota(
            Terminal.TUAS,
            Terminal.TUAS,
            TransferMode.NONE,
            ImpactBand.SMALL,
            connections_per_quota,
        ),
        BenchmarkQuota(
            Terminal.PASIR_PANJANG,
            Terminal.PASIR_PANJANG,
            TransferMode.NONE,
            ImpactBand.MEDIUM,
            connections_per_quota,
        ),
        BenchmarkQuota(
            Terminal.TUAS,
            Terminal.PASIR_PANJANG,
            TransferMode.ROAD,
            ImpactBand.MEDIUM,
            connections_per_quota,
        ),
        BenchmarkQuota(
            Terminal.PASIR_PANJANG,
            Terminal.TUAS,
            TransferMode.SEA,
            ImpactBand.LARGE,
            connections_per_quota,
        ),
    )
    assumptions = (
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
    )
    return SyntheticBenchmarkConfig(
        seed=HISTORICAL_CONFIG_VERSION,
        topology_version=TOPOLOGY_VERSION,
        dataset_sha256=dataset_sha256,
        quotas=quotas,
        process_assumptions=assumptions,
        difficulty_thresholds=DifficultyThresholds(
            tight_upper_bound=timedelta(hours=2),
            standard_upper_bound=timedelta(hours=6),
        ),
        evidence=approved_assumption_register(),
    )


@dataclass(frozen=True, slots=True)
class ConnectionActivation:
    """Point when both retrospectively paired candidates have been observed."""

    ucid: str
    active_at: datetime
    active_cursor: ReplayCursor


def connection_activation(connection: SyntheticConnection) -> ConnectionActivation:
    assignment = connection.assignment
    inbound = ReplayCursor(
        assignment.inbound_candidate.reference_observed_at,
        assignment.inbound_candidate.source_row_number,
        assignment.inbound_source_call_id,
    )
    outbound = ReplayCursor(
        assignment.outbound_candidate.reference_observed_at,
        assignment.outbound_candidate.source_row_number,
        assignment.outbound_source_call_id,
    )
    cursor = max(inbound, outbound)
    return ConnectionActivation(connection.identity.ucid, cursor.observed_at, cursor)


@dataclass(frozen=True, slots=True)
class SyntheticGraphLookup:
    """Source-call graph index and causal activation metadata."""

    connections_by_source_call: Mapping[str, tuple[SyntheticConnection, ...]]
    activations_by_ucid: Mapping[str, ConnectionActivation]

    @classmethod
    def build(
        cls,
        benchmark: SyntheticBenchmark,
        source_call_ids: Iterable[str],
    ) -> "SyntheticGraphLookup":
        allowed = frozenset(source_call_ids)
        connections_by_call: dict[str, list[SyntheticConnection]] = {}
        activations = {
            connection.identity.ucid: connection_activation(connection)
            for connection in benchmark.connections
        }
        for connection in benchmark.connections:
            assignment = connection.assignment
            for call_id in {
                assignment.inbound_source_call_id,
                assignment.outbound_source_call_id,
            }:
                if call_id not in allowed:
                    raise ValueError(
                        "synthetic connection references unknown source call "
                        f"{call_id}"
                    )
                connections_by_call.setdefault(call_id, []).append(connection)
        frozen_connections = {
            call_id: tuple(sorted(items, key=lambda item: item.identity.ucid))
            for call_id, items in connections_by_call.items()
        }
        return cls(
            MappingProxyType(frozen_connections),
            MappingProxyType(activations),
        )

    def connections_for(
        self, source_call_id: str
    ) -> tuple[SyntheticConnection, ...]:
        return self.connections_by_source_call.get(source_call_id, ())


@dataclass(slots=True)
class CausalReplayState:
    """Only chronological PR #2 updates seen through the current cursor."""

    histories: dict[str, list[CausalArrivalUpdate]] = field(default_factory=dict)
    current_cursor: ReplayCursor | None = None

    def observe(self, update: CausalArrivalUpdate) -> ReplayCursor:
        cursor = update_cursor(update)
        if self.current_cursor is not None and cursor < self.current_cursor:
            raise ValueError("causal replay updates must be observed chronologically")
        self.histories.setdefault(update.call_id, []).append(update)
        self.current_cursor = cursor
        return cursor

    def connection_prefix(
        self, connection: SyntheticConnection
    ) -> tuple[CausalArrivalUpdate, ...]:
        assignment = connection.assignment
        updates = (
            *self.histories.get(assignment.inbound_source_call_id, ()),
            *self.histories.get(assignment.outbound_source_call_id, ()),
        )
        return tuple(sorted(updates, key=update_cursor))


@dataclass(frozen=True, slots=True)
class HistoricalAssessmentRecord:
    """Evaluation record, deliberately smaller than the live domain model."""

    ucid: str
    assessed_at: datetime
    trigger_cursor: ReplayCursor
    trigger_source_call_id: str
    inbound_source_call_id: str
    outbound_source_call_id: str
    status: str
    severity: str | None
    current_plan_slack_h: float | None
    no_itt_slack_h: float | None
    reason_codes: tuple[str, ...]
    inbound_prediction_observed_at: datetime | None
    outbound_prediction_observed_at: datetime | None
    inbound_predicted_arrival: datetime | None
    outbound_predicted_arrival: datetime | None
    inbound_prediction_age_min: float | None
    outbound_prediction_age_min: float | None
    baseline_available: bool
    baseline_alert: bool | None
    baseline_delay_h: float | None
    baseline_prediction_observed_at: datetime | None
    process_scenario: str
    transfer_mode: str
    topology_version: str
    population_version: str
    population_digest: str
    graph_output_digest: str
    watcher_config_digest: str


def _assessment_record(
    assessment: ConnectionRiskAssessment,
    *,
    trigger_cursor: ReplayCursor,
    trigger_source_call_id: str,
    population: HistoricalCallPopulation,
    benchmark: SyntheticBenchmark,
    watcher_config_digest: str,
) -> HistoricalAssessmentRecord:
    inbound = assessment.inbound_prediction
    outbound = assessment.outbound_prediction
    slack = assessment.slack
    baseline = assessment.baseline
    return HistoricalAssessmentRecord(
        ucid=assessment.ucid,
        assessed_at=assessment.assessed_at,
        trigger_cursor=trigger_cursor,
        trigger_source_call_id=trigger_source_call_id,
        inbound_source_call_id=assessment.assignment.inbound_source_call_id,
        outbound_source_call_id=assessment.assignment.outbound_source_call_id,
        status=assessment.status.value,
        severity=(
            assessment.severity.value if assessment.severity is not None else None
        ),
        current_plan_slack_h=(
            slack.current_plan_slack_h if slack is not None else None
        ),
        no_itt_slack_h=(slack.no_itt_slack_h if slack is not None else None),
        reason_codes=tuple(code.value for code in assessment.reason_codes),
        inbound_prediction_observed_at=(
            inbound.observed_at if inbound is not None else None
        ),
        outbound_prediction_observed_at=(
            outbound.observed_at if outbound is not None else None
        ),
        inbound_predicted_arrival=(
            inbound.predicted_arrival if inbound is not None else None
        ),
        outbound_predicted_arrival=(
            outbound.predicted_arrival if outbound is not None else None
        ),
        inbound_prediction_age_min=assessment.inbound_prediction_age_min,
        outbound_prediction_age_min=assessment.outbound_prediction_age_min,
        baseline_available=baseline.delay is not None,
        baseline_alert=baseline.alert,
        baseline_delay_h=(
            baseline.delay.total_seconds() / 3600
            if baseline.delay is not None
            else None
        ),
        baseline_prediction_observed_at=(
            inbound.observed_at
            if baseline.delay is not None and inbound is not None
            else None
        ),
        process_scenario=assessment.process_scenario.value,
        transfer_mode=assessment.transfer_mode.value,
        topology_version=assessment.topology_version,
        population_version=population.config.population_version,
        population_digest=population.population_digest,
        graph_output_digest=benchmark.manifest.output_digest,
        watcher_config_digest=watcher_config_digest,
    )


@dataclass(frozen=True, slots=True)
class HistoricalEvaluationDiagnostics:
    accepted_call_count: int
    bounded_population_call_count: int
    source_candidate_count: int
    generated_connection_count: int
    causally_activated_connection_count: int
    assessment_count: int
    unavailable_assessment_count: int
    unavailable_assessment_fraction: float
    severity_distribution: tuple[tuple[str, int], ...]
    baseline_alert_count: int


@dataclass(frozen=True, slots=True)
class HistoricalEvaluationResult:
    population: HistoricalCallPopulation
    benchmark: SyntheticBenchmark
    activations: tuple[ConnectionActivation, ...]
    records: tuple[HistoricalAssessmentRecord, ...]
    diagnostics: HistoricalEvaluationDiagnostics


def summarise_diagnostics(
    population: HistoricalCallPopulation,
    benchmark: SyntheticBenchmark,
    records: Iterable[HistoricalAssessmentRecord],
    activated_ucids: Iterable[str],
) -> HistoricalEvaluationDiagnostics:
    """Compute diagnostic counts separately from causal replay orchestration."""

    materialized = tuple(records)
    severity_counts = Counter(
        record.severity for record in materialized if record.severity is not None
    )
    unavailable = sum(
        record.status == AssessmentStatus.UNAVAILABLE.value
        for record in materialized
    )
    return HistoricalEvaluationDiagnostics(
        accepted_call_count=population.accepted_call_count,
        bounded_population_call_count=len(population.replay_calls),
        source_candidate_count=benchmark.manifest.source_candidate_count,
        generated_connection_count=len(benchmark.connections),
        causally_activated_connection_count=len(frozenset(activated_ucids)),
        assessment_count=len(materialized),
        unavailable_assessment_count=unavailable,
        unavailable_assessment_fraction=(
            unavailable / len(materialized) if materialized else 0.0
        ),
        severity_distribution=tuple(sorted(severity_counts.items())),
        baseline_alert_count=sum(
            record.baseline_alert is True for record in materialized
        ),
    )


def replay_watcher_assessments(
    population: HistoricalCallPopulation,
    benchmark: SyntheticBenchmark,
    watcher_config: WatcherConfig,
) -> HistoricalEvaluationResult:
    """Replay causal prefixes and record PR #4 Watcher/baseline assessments."""

    graph = SyntheticGraphLookup.build(
        benchmark, (call.call_id for call in population.replay_calls)
    )

    replay_updates = sorted(
        (update for call in population.replay_calls for update in call.updates),
        key=update_cursor,
    )
    state = CausalReplayState()
    records: list[HistoricalAssessmentRecord] = []
    activated_ucids: set[str] = set()
    watcher_digest = canonical_digest(watcher_config)
    for update in replay_updates:
        cursor = state.observe(update)
        for connection in graph.connections_for(update.call_id):
            activation = graph.activations_by_ucid[connection.identity.ucid]
            if cursor < activation.active_cursor:
                continue
            activated_ucids.add(connection.identity.ucid)
            assessment = assess_connection(
                connection,
                state.connection_prefix(connection),
                assessed_at=update.observed_at,
                config=watcher_config,
            )
            records.append(
                _assessment_record(
                    assessment,
                    trigger_cursor=cursor,
                    trigger_source_call_id=update.call_id,
                    population=population,
                    benchmark=benchmark,
                    watcher_config_digest=watcher_digest,
                )
            )

    diagnostics = summarise_diagnostics(
        population, benchmark, records, activated_ucids
    )
    return HistoricalEvaluationResult(
        population=population,
        benchmark=benchmark,
        activations=tuple(
            graph.activations_by_ucid[ucid]
            for ucid in sorted(graph.activations_by_ucid)
        ),
        records=tuple(records),
        diagnostics=diagnostics,
    )


def records_through(
    records: Iterable[HistoricalAssessmentRecord],
    cursor: ReplayCursor,
) -> tuple[HistoricalAssessmentRecord, ...]:
    """Return only records created no later than an exact evaluation cursor."""

    return tuple(record for record in records if record.trigger_cursor <= cursor)


def file_sha256(path: str | Path) -> str:
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def evaluate_historical_csv(
    csv_path: str | Path,
    *,
    replay_config: ReplayConfig,
    population_config: HistoricalPopulationConfig,
    synthetic_config: SyntheticBenchmarkConfig,
    watcher_config: WatcherConfig,
) -> HistoricalEvaluationResult:
    """Compose PR #2 calls, PR #3 graph, and PR #4 causal assessments."""

    calls = derive_arrival_calls(csv_path, replay_config)
    population = build_call_population(calls, population_config)
    updates = tuple(
        update for call in population.replay_calls for update in call.updates
    )
    benchmark = generate_synthetic_benchmark(updates, synthetic_config)
    return replay_watcher_assessments(population, benchmark, watcher_config)


# --- PR #5 Phase 3 evaluation-only retrospective scoring -----------------


class SyntheticScenarioFeasibility(StrEnum):
    """Feasibility under a synthetic process scenario, not an actual outcome."""

    FEASIBLE = "FEASIBLE"
    INFEASIBLE = "INFEASIBLE"


@dataclass(frozen=True, slots=True)
class RetrospectiveConnectionOutcome:
    """Evaluation-only result built from final crossings after causal replay.

    This type deliberately contains no causal prediction or Watcher field.  It
    describes whether one synthetic connection is feasible under one frozen
    process scenario; it is not an observed missed connection, cargo outcome,
    actual UCID outcome, or PSA ground truth.
    """

    outcome_version: str
    ucid: str
    inbound_source_call_id: str
    outbound_source_call_id: str
    process_assumption_id: str
    final_inbound_derived_crossing: datetime
    final_outbound_derived_crossing: datetime
    cargo_ready_offset: timedelta
    cargo_cutoff_lead: timedelta
    transfer_duration: timedelta
    retrospective_inbound_ready: datetime
    retrospective_outbound_cutoff: datetime
    retrospective_slack: timedelta
    feasibility: SyntheticScenarioFeasibility
    retrospective_no_itt_slack: timedelta
    synthetic_terminal_prevention_opportunity: bool

    def __post_init__(self) -> None:
        _require_aware(
            self.final_inbound_derived_crossing,
            "final_inbound_derived_crossing",
        )
        _require_aware(
            self.final_outbound_derived_crossing,
            "final_outbound_derived_crossing",
        )
        _require_aware(
            self.retrospective_inbound_ready,
            "retrospective_inbound_ready",
        )
        _require_aware(
            self.retrospective_outbound_cutoff,
            "retrospective_outbound_cutoff",
        )
        expected_ready = (
            self.final_inbound_derived_crossing
            + self.cargo_ready_offset
            + self.transfer_duration
        )
        expected_cutoff = (
            self.final_outbound_derived_crossing - self.cargo_cutoff_lead
        )
        expected_slack = expected_cutoff - expected_ready
        expected_no_itt = expected_cutoff - (
            self.final_inbound_derived_crossing + self.cargo_ready_offset
        )
        expected_feasibility = (
            SyntheticScenarioFeasibility.INFEASIBLE
            if expected_slack <= timedelta(0)
            else SyntheticScenarioFeasibility.FEASIBLE
        )
        expected_opportunity = (
            self.transfer_duration > timedelta(0)
            and expected_slack <= timedelta(0)
            and expected_no_itt > timedelta(0)
        )
        if self.retrospective_inbound_ready != expected_ready:
            raise ValueError("retrospective inbound-ready arithmetic is inconsistent")
        if self.retrospective_outbound_cutoff != expected_cutoff:
            raise ValueError("retrospective outbound cut-off arithmetic is inconsistent")
        if self.retrospective_slack != expected_slack:
            raise ValueError("retrospective slack arithmetic is inconsistent")
        if self.retrospective_no_itt_slack != expected_no_itt:
            raise ValueError("retrospective no-ITT slack arithmetic is inconsistent")
        if self.feasibility is not expected_feasibility:
            raise ValueError("retrospective feasibility label is inconsistent")
        if self.synthetic_terminal_prevention_opportunity != expected_opportunity:
            raise ValueError("synthetic terminal-prevention label is inconsistent")

    @property
    def retrospective_slack_h(self) -> float:
        return self.retrospective_slack.total_seconds() / 3600.0

    @property
    def retrospective_no_itt_slack_h(self) -> float:
        return self.retrospective_no_itt_slack.total_seconds() / 3600.0


@dataclass(frozen=True, slots=True)
class OutcomeExclusion:
    ucid: str
    reason: str


@dataclass(frozen=True, slots=True)
class RetrospectiveOutcomeSet:
    process_scenario: str
    outcomes: tuple[RetrospectiveConnectionOutcome, ...]
    exclusions: tuple[OutcomeExclusion, ...]


def _projection_for_scenario(
    connection: SyntheticConnection,
    scenario: ProcessScenario,
):
    matches = tuple(
        projection
        for projection in connection.process_projections
        if projection.scenario is scenario
    )
    if len(matches) != 1:
        raise ValueError(
            f"connection {connection.identity.ucid} must have one "
            f"{scenario.value} projection"
        )
    return matches[0]


def retrospective_connection_outcome(
    connection: SyntheticConnection,
    *,
    inbound: RetrospectiveCallData,
    outbound: RetrospectiveCallData,
    scenario: ProcessScenario,
) -> RetrospectiveConnectionOutcome:
    """Build one synthetic scenario outcome from final PR #2 crossings."""

    assignment = connection.assignment
    if inbound.call_id != assignment.inbound_source_call_id:
        raise ValueError("inbound retrospective call does not match the assignment")
    if outbound.call_id != assignment.outbound_source_call_id:
        raise ValueError("outbound retrospective call does not match the assignment")
    projection = _projection_for_scenario(connection, scenario)
    inbound_crossing = inbound.final_event.derived_geofence_arrival
    outbound_crossing = outbound.final_event.derived_geofence_arrival
    ready = (
        inbound_crossing
        + projection.cargo_ready_offset
        + projection.transfer_duration
    )
    cutoff = outbound_crossing - projection.cargo_cutoff_lead
    slack = cutoff - ready
    no_itt_slack = cutoff - (
        inbound_crossing + projection.cargo_ready_offset
    )
    feasibility = (
        SyntheticScenarioFeasibility.INFEASIBLE
        if slack <= timedelta(0)
        else SyntheticScenarioFeasibility.FEASIBLE
    )
    terminal_opportunity = (
        projection.transfer_duration > timedelta(0)
        and slack <= timedelta(0)
        and no_itt_slack > timedelta(0)
    )
    return RetrospectiveConnectionOutcome(
        outcome_version=RETROSPECTIVE_OUTCOME_VERSION,
        ucid=connection.identity.ucid,
        inbound_source_call_id=assignment.inbound_source_call_id,
        outbound_source_call_id=assignment.outbound_source_call_id,
        process_assumption_id=(
            f"{HISTORICAL_CONFIG_VERSION}:{projection.scenario.value}"
        ),
        final_inbound_derived_crossing=inbound_crossing,
        final_outbound_derived_crossing=outbound_crossing,
        cargo_ready_offset=projection.cargo_ready_offset,
        cargo_cutoff_lead=projection.cargo_cutoff_lead,
        transfer_duration=projection.transfer_duration,
        retrospective_inbound_ready=ready,
        retrospective_outbound_cutoff=cutoff,
        retrospective_slack=slack,
        feasibility=feasibility,
        retrospective_no_itt_slack=no_itt_slack,
        synthetic_terminal_prevention_opportunity=terminal_opportunity,
    )


def build_retrospective_outcomes(
    replay_result: HistoricalEvaluationResult,
    *,
    scenario: ProcessScenario,
) -> RetrospectiveOutcomeSet:
    """Construct outcomes only from a completed causal replay result."""

    retrospective_by_call = {
        call.call_id: call for call in replay_result.population.retrospective_calls
    }
    outcomes: list[RetrospectiveConnectionOutcome] = []
    exclusions: list[OutcomeExclusion] = []
    for connection in sorted(
        replay_result.benchmark.connections,
        key=lambda item: item.identity.ucid,
    ):
        assignment = connection.assignment
        inbound = retrospective_by_call.get(assignment.inbound_source_call_id)
        outbound = retrospective_by_call.get(assignment.outbound_source_call_id)
        missing = []
        if inbound is None:
            missing.append("inbound_final_derived_crossing_unavailable")
        if outbound is None:
            missing.append("outbound_final_derived_crossing_unavailable")
        if missing:
            exclusions.append(
                OutcomeExclusion(connection.identity.ucid, "+".join(missing))
            )
            continue
        outcomes.append(
            retrospective_connection_outcome(
                connection,
                inbound=inbound,
                outbound=outbound,
                scenario=scenario,
            )
        )
    return RetrospectiveOutcomeSet(
        process_scenario=scenario.value,
        outcomes=tuple(outcomes),
        exclusions=tuple(exclusions),
    )


def _horizon_key(horizon: timedelta) -> str:
    seconds = horizon.total_seconds()
    if seconds <= 0:
        raise ValueError("evaluation horizons must be positive")
    if seconds % 3600 == 0:
        return f"T-{int(seconds // 3600)}h"
    if seconds % 60 == 0:
        return f"T-{int(seconds // 60)}m"
    return f"T-{seconds:g}s"


def normalize_horizons(
    horizons: Iterable[timedelta],
) -> tuple[timedelta, ...]:
    materialized = tuple(horizons)
    if not materialized:
        raise ValueError("at least one evaluation horizon is required")
    if any(item <= timedelta(0) for item in materialized):
        raise ValueError("evaluation horizons must be positive")
    if len(set(materialized)) != len(materialized):
        raise ValueError("evaluation horizons must be unique")
    return tuple(sorted(materialized, reverse=True))


def select_assessment_at_horizon(
    records: Iterable[HistoricalAssessmentRecord],
    outcome: RetrospectiveConnectionOutcome,
    horizon: timedelta,
) -> HistoricalAssessmentRecord | None:
    """Select the latest causal assessment at or before cut-off minus horizon."""

    evaluation_time = outcome.retrospective_outbound_cutoff - horizon
    eligible = [
        record
        for record in records
        if record.ucid == outcome.ucid and record.assessed_at <= evaluation_time
    ]
    if not eligible:
        return None
    eligible.sort(
        key=lambda record: (
            record.assessed_at,
            record.trigger_cursor,
            record.trigger_source_call_id,
        )
    )
    selected = eligible[-1]
    selected_key = (
        selected.assessed_at,
        selected.trigger_cursor,
        selected.trigger_source_call_id,
    )
    conflicts = [
        record
        for record in eligible
        if (
            record.assessed_at,
            record.trigger_cursor,
            record.trigger_source_call_id,
        )
        == selected_key
        and record != selected
    ]
    if conflicts:
        raise ValueError("conflicting historical assessments share a selection key")
    return selected


def watcher_alert(record: HistoricalAssessmentRecord | None) -> bool | None:
    """Primary Watcher detector: WATCH or AT_RISK is alert-positive."""

    if record is None or record.status != AssessmentStatus.AVAILABLE.value:
        return None
    if record.severity is None:
        return None
    return record.severity in (RiskSeverity.WATCH.value, RiskSeverity.AT_RISK.value)


def baseline_alert(record: HistoricalAssessmentRecord | None) -> bool | None:
    """Read the embedded reference-delay baseline from the same assessment."""

    if record is None or not record.baseline_available:
        return None
    return record.baseline_alert


@dataclass(frozen=True, slots=True)
class BinaryCounts:
    tp: int
    fp: int
    tn: int
    fn: int

    @property
    def support(self) -> int:
        return self.tp + self.fp + self.tn + self.fn


@dataclass(frozen=True, slots=True)
class DetectorConfusionMatrix:
    tp: int
    fp: int
    tn: int
    fn: int
    unavailable: int

    @property
    def available_support(self) -> int:
        return self.tp + self.fp + self.tn + self.fn


@dataclass(frozen=True, slots=True)
class BinaryRates:
    recall: float | None
    precision: float | None
    false_alarm_rate: float | None
    specificity: float | None
    f1: float | None


@dataclass(frozen=True, slots=True)
class BinaryRateDenominators:
    """The exact denominator behind every reported binary rate."""

    recall_actual_positive: int
    precision_alert_positive: int
    false_alarm_actual_negative: int
    specificity_actual_negative: int
    f1: int


def _safe_ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def binary_rates(counts: BinaryCounts) -> BinaryRates:
    recall = _safe_ratio(counts.tp, counts.tp + counts.fn)
    precision = _safe_ratio(counts.tp, counts.tp + counts.fp)
    false_alarm = _safe_ratio(counts.fp, counts.fp + counts.tn)
    specificity = _safe_ratio(counts.tn, counts.tn + counts.fp)
    f1_denominator = 2 * counts.tp + counts.fp + counts.fn
    return BinaryRates(
        recall=recall,
        precision=precision,
        false_alarm_rate=false_alarm,
        specificity=specificity,
        f1=_safe_ratio(2 * counts.tp, f1_denominator),
    )


@dataclass(frozen=True, slots=True)
class ScoredBinaryView:
    support: int
    actual_positive_support: int
    actual_negative_support: int
    counts: BinaryCounts
    rate_denominators: BinaryRateDenominators
    rates: BinaryRates


@dataclass(frozen=True, slots=True)
class AvailableSupportView:
    """Detector metrics where a detector result actually exists."""

    available_support: int
    total_connections: int
    actual_positive_support: int
    actual_negative_support: int
    counts: DetectorConfusionMatrix
    rate_denominators: BinaryRateDenominators
    rates: BinaryRates


@dataclass(frozen=True, slots=True)
class EndToEndEffectiveView:
    """Effective metrics after treating detector unavailability as no alert."""

    support: int
    actual_positive_support: int
    actual_negative_support: int
    counts: BinaryCounts
    unavailable_infeasible_as_fn: int
    unavailable_feasible_as_tn: int
    rate_denominators: BinaryRateDenominators
    rates: BinaryRates


@dataclass(frozen=True, slots=True)
class DetectorHorizonMetrics:
    available_support: AvailableSupportView
    end_to_end_effective: EndToEndEffectiveView
    common_support: ScoredBinaryView


@dataclass(frozen=True, slots=True)
class PairedAlertCounts:
    both_alert: int
    watcher_only: int
    baseline_only: int
    neither: int


@dataclass(frozen=True, slots=True)
class PairedComparison:
    retrospectively_infeasible: PairedAlertCounts
    retrospectively_feasible: PairedAlertCounts
    unavailable_for_pairing: int


@dataclass(frozen=True, slots=True)
class AvailabilityAtHorizon:
    horizon: str
    horizon_hours: float
    total_benchmark_connections: int
    assessment_available: int
    assessment_unavailable: int
    availability_percentage: float | None
    watcher_available: int
    baseline_available: int
    unavailable_reasons: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class HorizonEvaluation:
    horizon: str
    horizon_hours: float
    availability: AvailabilityAtHorizon
    watcher: DetectorHorizonMetrics
    reference_delay_baseline: DetectorHorizonMetrics
    paired_comparison: PairedComparison


def _counts_for(
    cases: Iterable[tuple[bool, bool | None]],
) -> DetectorConfusionMatrix:
    tp = fp = tn = fn = unavailable = 0
    for actual_infeasible, alert in cases:
        if alert is None:
            unavailable += 1
        elif actual_infeasible and alert:
            tp += 1
        elif actual_infeasible:
            fn += 1
        elif alert:
            fp += 1
        else:
            tn += 1
    return DetectorConfusionMatrix(tp, fp, tn, fn, unavailable)


def _binary(counts: DetectorConfusionMatrix) -> BinaryCounts:
    return BinaryCounts(counts.tp, counts.fp, counts.tn, counts.fn)


def _end_to_end_counts(
    cases: Iterable[tuple[bool, bool | None]],
) -> tuple[BinaryCounts, int, int]:
    materialized = tuple(cases)
    counts = _counts_for(
        (actual, False if alert is None else alert)
        for actual, alert in materialized
    )
    unavailable_infeasible = sum(
        actual and alert is None for actual, alert in materialized
    )
    unavailable_feasible = sum(
        not actual and alert is None for actual, alert in materialized
    )
    return _binary(counts), unavailable_infeasible, unavailable_feasible


def _rate_denominators(counts: BinaryCounts) -> BinaryRateDenominators:
    return BinaryRateDenominators(
        recall_actual_positive=counts.tp + counts.fn,
        precision_alert_positive=counts.tp + counts.fp,
        false_alarm_actual_negative=counts.fp + counts.tn,
        specificity_actual_negative=counts.tn + counts.fp,
        f1=2 * counts.tp + counts.fp + counts.fn,
    )


def _view(counts: BinaryCounts) -> ScoredBinaryView:
    return ScoredBinaryView(
        support=counts.support,
        actual_positive_support=counts.tp + counts.fn,
        actual_negative_support=counts.fp + counts.tn,
        counts=counts,
        rate_denominators=_rate_denominators(counts),
        rates=binary_rates(counts),
    )


def _detector_metrics(
    cases: tuple[tuple[bool, bool | None], ...],
    common_indices: frozenset[int],
) -> DetectorHorizonMetrics:
    raw = _counts_for(cases)
    available_counts = _binary(raw)
    end_counts, unavailable_infeasible, unavailable_feasible = (
        _end_to_end_counts(cases)
    )
    common = _counts_for(
        cases[index] for index in sorted(common_indices)
    )
    return DetectorHorizonMetrics(
        available_support=AvailableSupportView(
            available_support=raw.available_support,
            total_connections=raw.available_support + raw.unavailable,
            actual_positive_support=available_counts.tp + available_counts.fn,
            actual_negative_support=available_counts.fp + available_counts.tn,
            counts=raw,
            rate_denominators=_rate_denominators(available_counts),
            rates=binary_rates(available_counts),
        ),
        end_to_end_effective=EndToEndEffectiveView(
            support=end_counts.support,
            actual_positive_support=end_counts.tp + end_counts.fn,
            actual_negative_support=end_counts.fp + end_counts.tn,
            counts=end_counts,
            unavailable_infeasible_as_fn=unavailable_infeasible,
            unavailable_feasible_as_tn=unavailable_feasible,
            rate_denominators=_rate_denominators(end_counts),
            rates=binary_rates(end_counts),
        ),
        common_support=_view(_binary(common)),
    )


def _paired_counts(
    triples: Iterable[tuple[bool, bool, bool]],
    *,
    infeasible: bool,
) -> PairedAlertCounts:
    both = watcher_only = baseline_only = neither = 0
    for actual, watcher_value, baseline_value in triples:
        if actual is not infeasible:
            continue
        if watcher_value and baseline_value:
            both += 1
        elif watcher_value:
            watcher_only += 1
        elif baseline_value:
            baseline_only += 1
        else:
            neither += 1
    return PairedAlertCounts(both, watcher_only, baseline_only, neither)


def evaluate_fixed_horizon(
    records: Iterable[HistoricalAssessmentRecord],
    outcomes: Iterable[RetrospectiveConnectionOutcome],
    horizon: timedelta,
) -> HorizonEvaluation:
    """Score one connection-level horizon without looking forward."""

    materialized_records = tuple(records)
    materialized_outcomes = tuple(sorted(outcomes, key=lambda item: item.ucid))
    watcher_cases: list[tuple[bool, bool | None]] = []
    baseline_cases: list[tuple[bool, bool | None]] = []
    selected_records: list[HistoricalAssessmentRecord | None] = []
    reasons: Counter[str] = Counter()
    for outcome in materialized_outcomes:
        selected = select_assessment_at_horizon(
            materialized_records, outcome, horizon
        )
        selected_records.append(selected)
        actual = outcome.feasibility is SyntheticScenarioFeasibility.INFEASIBLE
        watcher_value = watcher_alert(selected)
        baseline_value = baseline_alert(selected)
        watcher_cases.append((actual, watcher_value))
        baseline_cases.append((actual, baseline_value))
        if selected is None:
            reasons["no_assessment_at_or_before_horizon"] += 1
        elif selected.status != AssessmentStatus.AVAILABLE.value:
            if selected.reason_codes:
                for code in selected.reason_codes:
                    reasons[f"selected_assessment:{code}"] += 1
            else:
                reasons["selected_assessment_unavailable"] += 1

    watcher_tuple = tuple(watcher_cases)
    baseline_tuple = tuple(baseline_cases)
    common_indices = frozenset(
        index
        for index, (watcher_case, baseline_case) in enumerate(
            zip(watcher_tuple, baseline_tuple, strict=True)
        )
        if watcher_case[1] is not None and baseline_case[1] is not None
    )
    paired = tuple(
        (
            watcher_tuple[index][0],
            bool(watcher_tuple[index][1]),
            bool(baseline_tuple[index][1]),
        )
        for index in sorted(common_indices)
    )
    watcher_available = sum(value is not None for _, value in watcher_tuple)
    baseline_available = sum(value is not None for _, value in baseline_tuple)
    assessment_available = sum(
        selected is not None
        and selected.status == AssessmentStatus.AVAILABLE.value
        for selected in selected_records
    )
    total = len(materialized_outcomes)
    horizon_name = _horizon_key(horizon)
    availability = AvailabilityAtHorizon(
        horizon=horizon_name,
        horizon_hours=horizon.total_seconds() / 3600.0,
        total_benchmark_connections=total,
        assessment_available=assessment_available,
        assessment_unavailable=total - assessment_available,
        availability_percentage=_safe_ratio(assessment_available, total),
        watcher_available=watcher_available,
        baseline_available=baseline_available,
        unavailable_reasons=tuple(sorted(reasons.items())),
    )
    return HorizonEvaluation(
        horizon=horizon_name,
        horizon_hours=horizon.total_seconds() / 3600.0,
        availability=availability,
        watcher=_detector_metrics(watcher_tuple, common_indices),
        reference_delay_baseline=_detector_metrics(
            baseline_tuple, common_indices
        ),
        paired_comparison=PairedComparison(
            retrospectively_infeasible=_paired_counts(
                paired, infeasible=True
            ),
            retrospectively_feasible=_paired_counts(
                paired, infeasible=False
            ),
            unavailable_for_pairing=total - len(common_indices),
        ),
    )


def _quantile(values: tuple[float, ...], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return round(
        ordered[lower] * (1 - weight) + ordered[upper] * weight,
        12,
    )


@dataclass(frozen=True, slots=True)
class LeadTimeStatistics:
    infeasible_connections: int
    caught_infeasible_connections: int
    missed_infeasible_connections: int
    median_lead_time_h: float | None
    p25_lead_time_h: float | None
    p75_lead_time_h: float | None
    minimum_lead_time_h: float | None
    maximum_lead_time_h: float | None


@dataclass(frozen=True, slots=True)
class FirstAlertLeadTimeReport:
    watcher: LeadTimeStatistics
    reference_delay_baseline: LeadTimeStatistics


def _lead_statistics(
    outcomes: tuple[RetrospectiveConnectionOutcome, ...],
    records: tuple[HistoricalAssessmentRecord, ...],
    alert_selector,
) -> LeadTimeStatistics:
    infeasible = tuple(
        outcome
        for outcome in outcomes
        if outcome.feasibility is SyntheticScenarioFeasibility.INFEASIBLE
    )
    leads: list[float] = []
    for outcome in infeasible:
        eligible = sorted(
            (
                record
                for record in records
                if record.ucid == outcome.ucid
                and record.assessed_at <= outcome.retrospective_outbound_cutoff
            ),
            key=lambda record: (
                record.assessed_at,
                record.trigger_cursor,
                record.trigger_source_call_id,
            ),
        )
        first = next(
            (record for record in eligible if alert_selector(record) is True),
            None,
        )
        if first is not None:
            leads.append(
                (
                    outcome.retrospective_outbound_cutoff - first.assessed_at
                ).total_seconds()
                / 3600.0
            )
    materialized = tuple(leads)
    return LeadTimeStatistics(
        infeasible_connections=len(infeasible),
        caught_infeasible_connections=len(materialized),
        missed_infeasible_connections=len(infeasible) - len(materialized),
        median_lead_time_h=_quantile(materialized, 0.5),
        p25_lead_time_h=_quantile(materialized, 0.25),
        p75_lead_time_h=_quantile(materialized, 0.75),
        minimum_lead_time_h=min(materialized) if materialized else None,
        maximum_lead_time_h=max(materialized) if materialized else None,
    )


def first_alert_lead_times(
    records: Iterable[HistoricalAssessmentRecord],
    outcomes: Iterable[RetrospectiveConnectionOutcome],
) -> FirstAlertLeadTimeReport:
    materialized_records = tuple(records)
    materialized_outcomes = tuple(outcomes)
    return FirstAlertLeadTimeReport(
        watcher=_lead_statistics(
            materialized_outcomes, materialized_records, watcher_alert
        ),
        reference_delay_baseline=_lead_statistics(
            materialized_outcomes, materialized_records, baseline_alert
        ),
    )


@dataclass(frozen=True, slots=True)
class AlertChurnStatistics:
    connections: int
    median_transitions_per_connection: float | None
    p90_transitions_per_connection: float | None
    zero_transition_connections: int
    zero_transition_share: float | None
    diagnostic_threshold: int
    above_threshold_connections: int
    above_threshold_share: float | None


def alert_churn_statistics(
    records: Iterable[HistoricalAssessmentRecord],
    outcomes: Iterable[RetrospectiveConnectionOutcome],
    *,
    diagnostic_threshold: int = DEFAULT_CHURN_DIAGNOSTIC_THRESHOLD,
) -> AlertChurnStatistics:
    """Describe Watcher severity transitions before each synthetic cut-off."""

    if diagnostic_threshold < 0:
        raise ValueError("churn diagnostic threshold must not be negative")
    materialized_records = tuple(records)
    materialized_outcomes = tuple(sorted(outcomes, key=lambda item: item.ucid))
    transitions: list[int] = []
    for outcome in materialized_outcomes:
        ordered = sorted(
            (
                record
                for record in materialized_records
                if record.ucid == outcome.ucid
                and record.assessed_at <= outcome.retrospective_outbound_cutoff
                and record.status == AssessmentStatus.AVAILABLE.value
                and record.severity is not None
            ),
            key=lambda record: (
                record.assessed_at,
                record.trigger_cursor,
                record.trigger_source_call_id,
            ),
        )
        states = [record.severity for record in ordered]
        transitions.append(
            sum(before != after for before, after in zip(states, states[1:]))
        )
    values = tuple(float(value) for value in transitions)
    zero = sum(value == 0 for value in transitions)
    above = sum(value > diagnostic_threshold for value in transitions)
    total = len(transitions)
    return AlertChurnStatistics(
        connections=total,
        median_transitions_per_connection=_quantile(values, 0.5),
        p90_transitions_per_connection=_quantile(values, 0.9),
        zero_transition_connections=zero,
        zero_transition_share=_safe_ratio(zero, total),
        diagnostic_threshold=diagnostic_threshold,
        above_threshold_connections=above,
        above_threshold_share=_safe_ratio(above, total),
    )


@dataclass(frozen=True, slots=True)
class BenchmarkQuotaReport:
    origin_terminal: str
    destination_terminal: str
    transfer_mode: str
    impact_band: str
    count: int


@dataclass(frozen=True, slots=True)
class WatcherConfigurationReport:
    warning_margin_h: float
    reference_delay_threshold_min: float
    selected_process_scenario: str
    primary_alert_threshold: str


@dataclass(frozen=True, slots=True)
class ProcessAssumptionReport:
    scenario: str
    cargo_ready_offset_h: float
    cargo_cutoff_lead_h: float
    road_transfer_duration_h: float
    sea_transfer_duration_h: float


@dataclass(frozen=True, slots=True)
class BenchmarkConfigurationReport:
    population_version: str
    source_call_limit: int
    population_digest: str
    synthetic_seed: str
    quota_configuration: tuple[BenchmarkQuotaReport, ...]
    watcher_configuration: WatcherConfigurationReport
    horizon_definitions: tuple[str, ...]
    process_assumption_version: str
    process_assumptions: tuple[ProcessAssumptionReport, ...]
    scored_scenarios: tuple[str, ...]
    dataset_sha256: str
    graph_output_digest: str


@dataclass(frozen=True, slots=True)
class BenchmarkComposition:
    accepted_pr2_calls: int
    bounded_replay_calls: int
    pr3_candidate_calls: int
    synthetic_connections: int
    connections_with_valid_retrospective_outcome: int
    feasible_synthetic_scenarios: int
    infeasible_synthetic_scenarios: int
    same_terminal_connections: int
    inter_terminal_connections: int
    transfer_mode_breakdown: tuple[tuple[str, int], ...]
    process_assumption_id: str
    scoring_exclusions: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class TerminalPreventionOpportunityReport:
    infeasible_with_transfer_feasible_without_transfer: int
    share_of_infeasible_scenarios: float | None
    interpretation: str


@dataclass(frozen=True, slots=True)
class ScenarioEvaluationReport:
    process_scenario: str
    process_assumption_id: str
    composition: BenchmarkComposition
    horizons: tuple[HorizonEvaluation, ...]
    first_alert_lead_time: FirstAlertLeadTimeReport
    watcher_alert_churn: AlertChurnStatistics
    terminal_prevention_opportunity: TerminalPreventionOpportunityReport


@dataclass(frozen=True, slots=True)
class HistoricalBenchmarkReport:
    report_version: str
    benchmark_label: str
    configuration: BenchmarkConfigurationReport
    phase2_diagnostics: HistoricalEvaluationDiagnostics
    scenarios: tuple[ScenarioEvaluationReport, ...]
    provenance: tuple[str, ...]
    limitations: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        payload = to_primitive(self)
        assert isinstance(payload, dict)
        return payload

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(
            self.as_dict(),
            ensure_ascii=False,
            indent=indent,
            sort_keys=True,
        )


def _composition(
    result: HistoricalEvaluationResult,
    outcome_set: RetrospectiveOutcomeSet,
) -> BenchmarkComposition:
    outcomes = outcome_set.outcomes
    feasible = sum(
        outcome.feasibility is SyntheticScenarioFeasibility.FEASIBLE
        for outcome in outcomes
    )
    same_terminal = sum(
        connection.origin.terminal == connection.destination.terminal
        for connection in result.benchmark.connections
    )
    transfer_modes = Counter(
        _projection_for_scenario(
            connection, ProcessScenario(outcome_set.process_scenario)
        ).transfer_mode.value
        for connection in result.benchmark.connections
    )
    exclusion_counts = Counter(item.reason for item in outcome_set.exclusions)
    process_id = (
        outcomes[0].process_assumption_id
        if outcomes
        else f"{HISTORICAL_CONFIG_VERSION}:{outcome_set.process_scenario}"
    )
    return BenchmarkComposition(
        accepted_pr2_calls=result.population.accepted_call_count,
        bounded_replay_calls=len(result.population.replay_calls),
        pr3_candidate_calls=result.benchmark.manifest.source_candidate_count,
        synthetic_connections=len(result.benchmark.connections),
        connections_with_valid_retrospective_outcome=len(outcomes),
        feasible_synthetic_scenarios=feasible,
        infeasible_synthetic_scenarios=len(outcomes) - feasible,
        same_terminal_connections=same_terminal,
        inter_terminal_connections=(
            len(result.benchmark.connections) - same_terminal
        ),
        transfer_mode_breakdown=tuple(sorted(transfer_modes.items())),
        process_assumption_id=process_id,
        scoring_exclusions=tuple(sorted(exclusion_counts.items())),
    )


def scenario_evaluation_report(
    result: HistoricalEvaluationResult,
    *,
    scenario: ProcessScenario,
    horizons: Iterable[timedelta] = DEFAULT_EVALUATION_HORIZONS,
    churn_diagnostic_threshold: int = DEFAULT_CHURN_DIAGNOSTIC_THRESHOLD,
) -> ScenarioEvaluationReport:
    if any(
        record.process_scenario != scenario.value for record in result.records
    ):
        raise ValueError("assessment records do not match the scored scenario")
    normalized_horizons = normalize_horizons(horizons)
    outcome_set = build_retrospective_outcomes(result, scenario=scenario)
    outcomes = outcome_set.outcomes
    composition = _composition(result, outcome_set)
    infeasible = composition.infeasible_synthetic_scenarios
    opportunities = sum(
        item.synthetic_terminal_prevention_opportunity for item in outcomes
    )
    process_id = composition.process_assumption_id
    return ScenarioEvaluationReport(
        process_scenario=scenario.value,
        process_assumption_id=process_id,
        composition=composition,
        horizons=tuple(
            evaluate_fixed_horizon(result.records, outcomes, horizon)
            for horizon in normalized_horizons
        ),
        first_alert_lead_time=first_alert_lead_times(result.records, outcomes),
        watcher_alert_churn=alert_churn_statistics(
            result.records,
            outcomes,
            diagnostic_threshold=churn_diagnostic_threshold,
        ),
        terminal_prevention_opportunity=TerminalPreventionOpportunityReport(
            infeasible_with_transfer_feasible_without_transfer=opportunities,
            share_of_infeasible_scenarios=_safe_ratio(opportunities, infeasible),
            interpretation="synthetic terminal-prevention opportunity only",
        ),
    )


def build_historical_benchmark_report(
    scenario_results: Iterable[HistoricalEvaluationResult],
    *,
    synthetic_config: SyntheticBenchmarkConfig,
    watcher_config: WatcherConfig,
    horizons: Iterable[timedelta] = DEFAULT_EVALUATION_HORIZONS,
    churn_diagnostic_threshold: int = DEFAULT_CHURN_DIAGNOSTIC_THRESHOLD,
) -> HistoricalBenchmarkReport:
    """Build a deterministic, versioned machine-readable Phase 3 report."""

    materialized = tuple(scenario_results)
    if not materialized:
        raise ValueError("at least one scenario replay result is required")
    first = materialized[0]
    if any(
        result.population != first.population
        or result.benchmark != first.benchmark
        for result in materialized[1:]
    ):
        raise ValueError("scenario sensitivity must use one fixed population and graph")
    by_scenario: dict[ProcessScenario, HistoricalEvaluationResult] = {}
    for result in materialized:
        scenarios = {record.process_scenario for record in result.records}
        if len(scenarios) != 1:
            raise ValueError("each replay result must contain exactly one scenario")
        scenario = ProcessScenario(next(iter(scenarios)))
        if scenario in by_scenario:
            raise ValueError(f"duplicate replay result for {scenario.value}")
        by_scenario[scenario] = result
    ordered_scenarios = tuple(
        scenario for scenario in ProcessScenario if scenario in by_scenario
    )
    normalized_horizons = normalize_horizons(horizons)
    quotas = tuple(
        BenchmarkQuotaReport(
            quota.origin_terminal.value,
            quota.destination_terminal.value,
            quota.transfer_mode.value,
            quota.impact_band.value,
            quota.count,
        )
        for quota in synthetic_config.quotas
    )
    configuration = BenchmarkConfigurationReport(
        population_version=first.population.config.population_version,
        source_call_limit=first.population.config.source_call_limit,
        population_digest=first.population.population_digest,
        synthetic_seed=synthetic_config.seed,
        quota_configuration=quotas,
        watcher_configuration=WatcherConfigurationReport(
            warning_margin_h=watcher_config.warning_margin.total_seconds()
            / 3600.0,
            reference_delay_threshold_min=(
                watcher_config.reference_delay_threshold.total_seconds() / 60.0
            ),
            selected_process_scenario=watcher_config.process_scenario.value,
            primary_alert_threshold="WATCH_or_AT_RISK",
        ),
        horizon_definitions=tuple(map(_horizon_key, normalized_horizons)),
        process_assumption_version=HISTORICAL_CONFIG_VERSION,
        process_assumptions=tuple(
            ProcessAssumptionReport(
                scenario=item.scenario.value,
                cargo_ready_offset_h=(
                    item.cargo_ready_offset.total_seconds() / 3600.0
                ),
                cargo_cutoff_lead_h=(
                    item.cargo_cutoff_lead.total_seconds() / 3600.0
                ),
                road_transfer_duration_h=(
                    item.road_transfer_duration.total_seconds() / 3600.0
                ),
                sea_transfer_duration_h=(
                    item.sea_transfer_duration.total_seconds() / 3600.0
                ),
            )
            for item in sorted(
                synthetic_config.process_assumptions,
                key=lambda value: list(ProcessScenario).index(value.scenario),
            )
        ),
        scored_scenarios=tuple(item.value for item in ordered_scenarios),
        dataset_sha256=synthetic_config.dataset_sha256,
        graph_output_digest=first.benchmark.manifest.output_digest,
    )
    return HistoricalBenchmarkReport(
        report_version=HISTORICAL_REPORT_VERSION,
        benchmark_label="retrospective synthetic connection benchmark",
        configuration=configuration,
        phase2_diagnostics=first.diagnostics,
        scenarios=tuple(
            scenario_evaluation_report(
                by_scenario[scenario],
                scenario=scenario,
                horizons=normalized_horizons,
                churn_diagnostic_threshold=churn_diagnostic_threshold,
            )
            for scenario in ordered_scenarios
        ),
        provenance=(
            "AIS observations are real October 2023 source data.",
            "Causal arrival predictions and final geofence crossings are derived.",
            "UCIDs, connection assignments, terminals, transfer modes, cut-offs, and process assumptions are synthetic.",
            "Retrospective outcomes are created only after causal replay and never enter assess_connection().",
        ),
        limitations=(
            "Feasibility means connection infeasible under a synthetic process scenario; it is not an observed missed PSA connection or actual cargo/UCID outcome.",
            "The bounded population is conditioned on retrospectively segmented reset-confirmed calls and is not a live discovery or prevalence sample.",
            "Available-support rates exclude unavailable detector results. End-to-end effective confusion treats unavailable INFEASIBLE as FN and unavailable FEASIBLE as TN; common support excludes cases where either detector is unavailable.",
            "Lead time is synthetic decision time before the scenario cut-off and does not prove operational rescue.",
            "Churn is descriptive operational-stability evidence; the diagnostic threshold is not a PSA alert-fatigue target.",
            "The reference-delay baseline is the PR #4 embedded derived baseline, not eval_detection.py's calibrated detector.",
        ),
    )


def write_historical_benchmark_report(
    report: HistoricalBenchmarkReport, path: str | Path
) -> None:
    """Write deterministic JSON; no run timestamp is introduced."""

    Path(path).write_text(report.to_json(indent=2) + "\n", encoding="utf-8")
