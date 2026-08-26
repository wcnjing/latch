"""Causal historical evaluation of the PR #3 graph with the PR #4 Watcher.

The benchmark population is retrospectively constructed from PR #2's
reset-confirmed, derived geofence-crossing calls.  That permits repeatable
historical evaluation, but it is not live call discovery.  In particular,
causal connection activation prevents the finished graph from revealing a
future source candidate before both of its first-available real AIS
observations have been replayed.

Retrospective ``DerivedArrivalEvent`` values are retained beside, never inside,
the causal replay state.  This phase records Watcher assessments and the
embedded derived reference-delay baseline; it does not construct outcomes or
send assessments to the agent.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Mapping

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
