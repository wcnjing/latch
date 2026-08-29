"""Deterministic curated terminal-prevention capability challenge.

This module is deliberately separate from the frozen PR #5 historical graph.
Retrospective crossings are used only to curate labelled challenge cases.  The
selected immutable connections are then replayed through the existing causal
Watcher with no retrospective value in its input stream.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Iterable, Mapping

from latch.events import RiskSeverity
from latch.historical_eval import (
    DEFAULT_CONNECTIONS_PER_QUOTA,
    HISTORICAL_REPORT_VERSION,
    HistoricalCallPopulation,
    HistoricalAssessmentRecord,
    HistoricalEvaluationResult,
    RetrospectiveCallData,
    RetrospectiveConnectionOutcome,
    connection_activation,
    historical_synthetic_config,
    replay_watcher_assessments,
    retrospective_connection_outcome,
    update_cursor,
)
from latch.models import Terminal
from latch.replay import PredictionStatus
from latch.synthetic import (
    SMDG_TCL_VERSION,
    BenchmarkEvidence,
    GenerationManifest,
    ImpactBand,
    ProcessAssumptions,
    ProcessScenario,
    ReferenceArrivalWindow,
    SyntheticBenchmark,
    SyntheticBenchmarkConfig,
    SyntheticCallCandidate,
    SyntheticConnection,
    TransferMode,
    UCIDAssignment,
    canonical_digest,
    make_ucid_identity,
    project_process,
    to_primitive,
    CORE_TERMINALS,
)
from latch.watcher import AssessmentStatus, WatcherConfig
from latch.watcher_refinement_eval import (
    FROZEN_BASELINE_THRESHOLD,
    FROZEN_PR5_REFERENCE_MARGIN,
    PR5_PARENT_COMMIT,
)


TERMINAL_PREVENTION_CHALLENGE_VERSION = "terminal-prevention-challenge-v1"
CHALLENGE_SELECTION_RULE_VERSION = "terminal-prevention-curated-selection-v1"
CHALLENGE_TOPOLOGY_VERSION = "terminal-prevention-challenge-topology-v1"
CHALLENGE_TARGET_PER_CATEGORY = 4
CHALLENGE_CURATION_LABEL = (
    "DELIBERATELY CURATED / DETERMINISTIC SYNTHETIC CHALLENGE SELECTION"
)
CAUSAL_ACTIONABILITY_CAPABILITY_VERSION = "causal-actionability-capability-v1"
CAUSAL_ACTIONABILITY_TOPOLOGY_VERSION = "causal-actionability-capability-topology-v1"
CAUSAL_ACTIONABILITY_TARGET = 4
CAUSAL_ACTIONABILITY_CURATION_LABEL = (
    "DELIBERATELY CURATED CAUSAL-ACTIONABILITY CAPABILITY SET"
)


class ChallengeCategory(StrEnum):
    RETROSPECTIVE_PREVENTION_OPPORTUNITY = (
        "RETROSPECTIVE_PREVENTION_OPPORTUNITY"
    )
    UNRECOVERABLE_WITH_NO_ITT = "UNRECOVERABLE_WITH_NO_ITT"
    FEASIBLE_WITH_ITT = "FEASIBLE_WITH_ITT"


class RetrospectivePreventionActionability(StrEnum):
    CAUSALLY_ACTIONABLE = "CAUSALLY_ACTIONABLE"
    ALERTED_AFTER_PREVENTION_WINDOW_CLOSED = (
        "ALERTED_AFTER_PREVENTION_WINDOW_CLOSED"
    )
    NO_CAUSAL_ASSESSMENT_BEFORE_CUTOFF = (
        "NO_CAUSAL_ASSESSMENT_BEFORE_CUTOFF"
    )
    NO_CAUSAL_PREVENTION_SIGNAL_BEFORE_CUTOFF = (
        "NO_CAUSAL_PREVENTION_SIGNAL_BEFORE_CUTOFF"
    )


@dataclass(frozen=True, slots=True)
class ChallengeSourceCandidate:
    candidate: SyntheticCallCandidate
    candidate_id: str
    source_call_id: str
    vessel_id: str
    final_crossing: datetime


@dataclass(frozen=True, slots=True)
class ChallengeAlternative:
    scenario: ProcessScenario
    category: ChallengeCategory
    inbound: ChallengeSourceCandidate
    outbound: ChallengeSourceCandidate
    origin_terminal: Terminal
    destination_terminal: Terminal
    transfer_mode: TransferMode
    impact_band: ImpactBand
    retrospective_slack: timedelta
    retrospective_no_itt_slack: timedelta
    transfer_duration: timedelta
    selection_rank: str

    @property
    def descriptor_key(self) -> tuple[str, str, str]:
        return (
            self.inbound.source_call_id,
            self.outbound.source_call_id,
            self.transfer_mode.value,
        )


@dataclass(frozen=True, slots=True)
class ChallengeCandidateCount:
    scenario: str
    category: str
    count: int


@dataclass(frozen=True, slots=True)
class ChallengeCategorySelection:
    category: str
    target: int
    selected: int
    shortfall: int


@dataclass(frozen=True, slots=True)
class SelectedChallengeCase:
    challenge_case_id: str
    category: ChallengeCategory
    scenario: ProcessScenario
    selection_rank: str
    connection: SyntheticConnection
    retrospective_outcome: RetrospectiveConnectionOutcome


@dataclass(frozen=True, slots=True)
class TerminalPreventionChallengeSelection:
    source_candidate_count: int
    candidate_input_digest: str
    candidate_counts: tuple[ChallengeCandidateCount, ...]
    category_selections: tuple[ChallengeCategorySelection, ...]
    selected_cases: tuple[SelectedChallengeCase, ...]
    benchmark: SyntheticBenchmark
    ordered_case_ids: tuple[str, ...]
    challenge_set_digest: str


@dataclass(frozen=True, slots=True)
class ChallengeCaseIdentity:
    challenge_case_id: str
    ucid: str
    category: str
    scenario: str
    inbound_call_id: str
    outbound_call_id: str
    origin_terminal: str
    destination_terminal: str
    transfer_mode: str
    selection_rank: str


@dataclass(frozen=True, slots=True)
class RetrospectiveChallengeDefinition:
    retrospective_category: str
    retrospective_prevention_opportunity: bool
    retrospective_current_plan_slack_hours: float
    retrospective_no_itt_slack_hours: float
    transfer_duration_hours: float
    recovered_margin_from_removing_itt_hours: float


@dataclass(frozen=True, slots=True)
class CausalChallengeDetection:
    first_watcher_assessment_available: datetime | None
    first_watch_or_at_risk_timestamp: datetime | None
    synthetic_cutoff: datetime
    first_alert_lead_time_hours: float | None
    causal_current_plan_slack_hours_at_first_alert: float | None
    causal_no_itt_slack_hours_at_first_alert: float | None
    causal_prevention_signal_before_cutoff: bool
    first_causal_prevention_signal_timestamp: datetime | None
    first_causal_prevention_signal_lead_time_hours: float | None
    causal_current_plan_slack_hours_at_first_prevention_signal: float | None
    causal_no_itt_slack_hours_at_first_prevention_signal: float | None
    recovered_slack_from_removing_itt_hours_at_first_prevention_signal: float | None
    watcher_state_at_risk_at_first_prevention_signal: bool | None
    retrospective_prevention_actionability: str | None
    first_category_consistent_signal_timestamp: datetime | None
    category_behaviour_observed: bool


@dataclass(frozen=True, slots=True)
class CausalPreventionSignalObservation:
    assessed_at: datetime
    current_plan_slack_hours: float
    no_itt_slack_hours: float
    watcher_state: str


@dataclass(frozen=True, slots=True)
class TerminalPreventionChallengeCaseResult:
    identity: ChallengeCaseIdentity
    retrospective_challenge_definition: RetrospectiveChallengeDefinition
    causal_detection: CausalChallengeDetection
    interpretation: str


@dataclass(frozen=True, slots=True)
class SelectedCausalActionabilityCase:
    capability_case_id: str
    selection_rank: str
    connection: SyntheticConnection
    retrospective_category: ChallengeCategory
    retrospective_outcome: RetrospectiveConnectionOutcome


@dataclass(frozen=True, slots=True)
class CausalActionabilityCapabilitySelection:
    version: str
    curation: str
    scenario: str
    candidate_count: int
    target: int
    selected: int
    shortfall: int
    ordered_case_ids: tuple[str, ...]
    graph_digest: str
    capability_set_digest: str
    benchmark: SyntheticBenchmark
    selected_cases: tuple[SelectedCausalActionabilityCase, ...]


@dataclass(frozen=True, slots=True)
class CausalActionabilityCapabilityReport:
    version: str
    curation: str
    purpose: str
    scenario: str
    candidate_count: int
    target: int
    selected: int
    shortfall: int
    ordered_case_ids: tuple[str, ...]
    graph_digest: str
    capability_set_digest: str
    cases: tuple[TerminalPreventionChallengeCaseResult, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TerminalPreventionChallengeReport:
    report_version: str
    challenge_set_version: str
    selection_rule_version: str
    curation: str
    parent_commit: str
    parent_report_version: str
    dataset_hash: str
    input_population_digest: str
    input_candidate_digest: str
    frozen_historical_graph_digest: str
    frozen_historical_graph_output_digest: str
    challenge_graph_digest: str
    challenge_set_digest: str
    source_candidate_count: int
    target_per_category: int
    candidate_counts: tuple[ChallengeCandidateCount, ...]
    category_selections: tuple[ChallengeCategorySelection, ...]
    ordered_case_ids: tuple[str, ...]
    cases: tuple[TerminalPreventionChallengeCaseResult, ...]
    causal_actionability_capability_set: CausalActionabilityCapabilityReport
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


_SCENARIO_ORDER = (
    ProcessScenario.REFERENCE,
    ProcessScenario.LOW,
    ProcessScenario.CONSERVATIVE,
)
_CATEGORY_ORDER = tuple(ChallengeCategory)
_INTER_TERMINAL_PATTERNS = (
    (Terminal.TUAS, Terminal.PASIR_PANJANG, TransferMode.ROAD, ImpactBand.MEDIUM),
    (Terminal.PASIR_PANJANG, Terminal.TUAS, TransferMode.SEA, ImpactBand.LARGE),
)


def _hours(value: timedelta) -> float:
    return value.total_seconds() / 3600.0


def _selection_category_token(category: ChallengeCategory) -> str:
    """Keep the already-reviewed deterministic three-category ordering stable."""

    if category is ChallengeCategory.RETROSPECTIVE_PREVENTION_OPPORTUNITY:
        return "PREVENTION_OPPORTUNITY"
    return category.value


def classify_challenge_category(
    *,
    transfer_duration: timedelta,
    retrospective_slack: timedelta,
    retrospective_no_itt_slack: timedelta,
) -> ChallengeCategory:
    """Classify one positive-transfer retrospective challenge candidate."""

    if transfer_duration <= timedelta(0):
        raise ValueError("terminal-prevention challenge cases require positive transfer")
    if retrospective_slack > timedelta(0):
        return ChallengeCategory.FEASIBLE_WITH_ITT
    if retrospective_no_itt_slack > timedelta(0):
        return ChallengeCategory.RETROSPECTIVE_PREVENTION_OPPORTUNITY
    return ChallengeCategory.UNRECOVERABLE_WITH_NO_ITT


def _candidate_payload(candidate: SyntheticCallCandidate) -> dict[str, object]:
    return {
        "reference_observed_at": candidate.reference_observed_at,
        "reference_arrival": candidate.reference_arrival,
        "source_row_number": candidate.source_row_number,
        "boundary_version": candidate.boundary_version,
        "source_type": candidate.source_type,
    }


def build_challenge_source_candidates(
    population: HistoricalCallPopulation,
) -> tuple[ChallengeSourceCandidate, ...]:
    """Project first causal support plus separate retrospective selection data."""

    retrospective = {
        item.call_id: item.final_event.derived_geofence_arrival
        for item in population.retrospective_calls
    }
    projected: list[ChallengeSourceCandidate] = []
    for call in population.replay_calls:
        available = sorted(
            (
                update
                for update in call.updates
                if update.prediction_status is PredictionStatus.AVAILABLE
                and update.predicted_arrival is not None
                and update.reference_arrival is not None
            ),
            key=lambda update: (
                update.observed_at,
                update.source_observation.source_row_number,
            ),
        )
        if not available:
            continue
        first = available[0]
        if first.predicted_arrival != first.reference_arrival:
            raise ValueError("first AVAILABLE prediction must establish the reference")
        candidate = SyntheticCallCandidate(
            reference_observed_at=first.observed_at,
            reference_arrival=first.reference_arrival,
            source_row_number=first.source_observation.source_row_number,
            boundary_version=first.boundary_version,
            source_type=first.source_type,
        )
        candidate_id = f"candidate_{canonical_digest(_candidate_payload(candidate))[:20]}"
        projected.append(
            ChallengeSourceCandidate(
                candidate=candidate,
                candidate_id=candidate_id,
                source_call_id=call.call_id,
                vessel_id=call.vessel_id,
                final_crossing=retrospective[call.call_id],
            )
        )
    projected.sort(
        key=lambda item: (
            item.candidate.reference_observed_at,
            item.candidate.source_row_number,
            item.candidate.reference_arrival,
            item.candidate_id,
            item.source_call_id,
        )
    )
    if len({item.candidate_id for item in projected}) != len(projected):
        raise ValueError("challenge source candidates contain duplicate candidate IDs")
    return tuple(projected)


def _process_assumptions(
    config: SyntheticBenchmarkConfig, scenario: ProcessScenario
) -> ProcessAssumptions:
    matches = tuple(
        item for item in config.process_assumptions if item.scenario is scenario
    )
    if len(matches) != 1:
        raise ValueError(f"exactly one {scenario.value} process assumption is required")
    return matches[0]


def _assert_frozen_process_configuration(config: SyntheticBenchmarkConfig) -> None:
    expected = historical_synthetic_config(
        dataset_sha256=config.dataset_sha256,
        connections_per_quota=DEFAULT_CONNECTIONS_PER_QUOTA,
    )
    if (
        config.process_assumptions != expected.process_assumptions
        or config.difficulty_thresholds != expected.difficulty_thresholds
        or config.evidence != expected.evidence
    ):
        raise ValueError(
            "challenge selection requires the unchanged historical process assumptions"
        )


def _retrospective_values(
    inbound: ChallengeSourceCandidate,
    outbound: ChallengeSourceCandidate,
    *,
    scenario: ProcessScenario,
    transfer_mode: TransferMode,
    config: SyntheticBenchmarkConfig,
) -> tuple[timedelta, timedelta, timedelta]:
    assumptions = _process_assumptions(config, scenario)
    transfer = assumptions.transfer_duration(transfer_mode)
    cutoff = outbound.final_crossing - assumptions.cargo_cutoff_lead
    no_itt = cutoff - (inbound.final_crossing + assumptions.cargo_ready_offset)
    return no_itt - transfer, no_itt, transfer


def discover_challenge_alternatives(
    population: HistoricalCallPopulation,
    config: SyntheticBenchmarkConfig,
) -> tuple[tuple[ChallengeAlternative, ...], str, int]:
    """Enumerate the broader valid pair population, independent of input order."""

    sources = build_challenge_source_candidates(population)
    input_digest = canonical_digest(
        tuple(
            {
                "candidate": item.candidate,
                "candidate_id": item.candidate_id,
                "source_call_id": item.source_call_id,
                "vessel_id": item.vessel_id,
                "final_crossing": item.final_crossing,
            }
            for item in sources
        )
    )
    alternatives: list[ChallengeAlternative] = []
    for inbound in sources:
        for outbound in sources:
            if inbound.candidate_id == outbound.candidate_id:
                continue
            if inbound.vessel_id == outbound.vessel_id:
                continue
            if outbound.candidate.reference_arrival <= inbound.candidate.reference_arrival:
                continue
            for origin, destination, mode, impact in _INTER_TERMINAL_PATTERNS:
                for scenario in _SCENARIO_ORDER:
                    slack, no_itt, transfer = _retrospective_values(
                        inbound,
                        outbound,
                        scenario=scenario,
                        transfer_mode=mode,
                        config=config,
                    )
                    category = classify_challenge_category(
                        transfer_duration=transfer,
                        retrospective_slack=slack,
                        retrospective_no_itt_slack=no_itt,
                    )
                    rank = canonical_digest(
                        {
                            "selection_rule_version": CHALLENGE_SELECTION_RULE_VERSION,
                            "scenario": scenario,
                            "category": _selection_category_token(category),
                            "inbound_candidate_id": inbound.candidate_id,
                            "outbound_candidate_id": outbound.candidate_id,
                            "origin_terminal": origin,
                            "destination_terminal": destination,
                            "transfer_mode": mode,
                        }
                    )
                    alternatives.append(
                        ChallengeAlternative(
                            scenario=scenario,
                            category=category,
                            inbound=inbound,
                            outbound=outbound,
                            origin_terminal=origin,
                            destination_terminal=destination,
                            transfer_mode=mode,
                            impact_band=impact,
                            retrospective_slack=slack,
                            retrospective_no_itt_slack=no_itt,
                            transfer_duration=transfer,
                            selection_rank=rank,
                        )
                    )
    alternatives.sort(
        key=lambda item: (
            _SCENARIO_ORDER.index(item.scenario),
            _CATEGORY_ORDER.index(item.category),
            item.selection_rank,
            item.descriptor_key,
        )
    )
    return tuple(alternatives), input_digest, len(sources)


def _connection(
    alternative: ChallengeAlternative,
    *,
    sequence: int,
    config: SyntheticBenchmarkConfig,
    topology_version: str = CHALLENGE_TOPOLOGY_VERSION,
) -> SyntheticConnection:
    window = ReferenceArrivalWindow(
        alternative.inbound.candidate.reference_arrival,
        alternative.outbound.candidate.reference_arrival,
    )
    identity = make_ucid_identity(
        origin_terminal=alternative.origin_terminal,
        destination_terminal=alternative.destination_terminal,
        reference_arrival_window=window,
        topology_version=topology_version,
        sequence=sequence,
    )
    assignment = UCIDAssignment(
        identity=identity,
        inbound_candidate=alternative.inbound.candidate,
        outbound_candidate=alternative.outbound.candidate,
        inbound_candidate_id=alternative.inbound.candidate_id,
        outbound_candidate_id=alternative.outbound.candidate_id,
        inbound_source_call_id=alternative.inbound.source_call_id,
        outbound_source_call_id=alternative.outbound.source_call_id,
        inbound_vessel_id=alternative.inbound.vessel_id,
        outbound_vessel_id=alternative.outbound.vessel_id,
    )
    projections = tuple(
        project_process(
            window,
            alternative.transfer_mode,
            assumptions,
            config.difficulty_thresholds,
        )
        for scenario in ProcessScenario
        for assumptions in config.process_assumptions
        if assumptions.scenario is scenario
    )
    evidence: tuple[BenchmarkEvidence, ...] = tuple(
        sorted(config.evidence, key=lambda item: item.field_name)
    )
    return SyntheticConnection(
        identity=identity,
        assignment=assignment,
        origin=CORE_TERMINALS[alternative.origin_terminal],
        destination=CORE_TERMINALS[alternative.destination_terminal],
        impact_band=alternative.impact_band,
        box_count=None,
        process_projections=projections,
        evidence=evidence,
    )


def _selected_alternatives(
    alternatives: tuple[ChallengeAlternative, ...],
    *,
    target_per_category: int,
) -> tuple[ChallengeAlternative, ...]:
    if target_per_category < 1:
        raise ValueError("target_per_category must be positive")
    reference_sufficient = all(
        sum(
            item.scenario is ProcessScenario.REFERENCE and item.category is category
            for item in alternatives
        )
        >= target_per_category
        for category in _CATEGORY_ORDER
    )
    selected: list[ChallengeAlternative] = []
    for category in _CATEGORY_ORDER:
        if reference_sufficient:
            pool = tuple(
                item
                for item in alternatives
                if item.scenario is ProcessScenario.REFERENCE
                and item.category is category
            )
            selected.extend(pool[:target_per_category])
            continue
        seen_descriptors: set[tuple[str, str, str]] = set()
        for scenario in _SCENARIO_ORDER:
            for item in alternatives:
                if item.scenario is not scenario or item.category is not category:
                    continue
                if item.descriptor_key in seen_descriptors:
                    continue
                selected.append(item)
                seen_descriptors.add(item.descriptor_key)
                if len(seen_descriptors) == target_per_category:
                    break
            if len(seen_descriptors) == target_per_category:
                break
    return tuple(selected)


def _retrospective_call(
    population: HistoricalCallPopulation, call_id: str
) -> RetrospectiveCallData:
    matches = tuple(item for item in population.retrospective_calls if item.call_id == call_id)
    if len(matches) != 1:
        raise ValueError(f"one retrospective call is required for {call_id}")
    return matches[0]


def build_terminal_prevention_challenge_selection(
    population: HistoricalCallPopulation,
    config: SyntheticBenchmarkConfig,
    *,
    target_per_category: int = CHALLENGE_TARGET_PER_CATEGORY,
) -> TerminalPreventionChallengeSelection:
    """Curate outcome-labelled cases without mutating the source population."""

    _assert_frozen_process_configuration(config)
    alternatives, input_digest, source_count = discover_challenge_alternatives(
        population, config
    )
    selected_alternatives = _selected_alternatives(
        alternatives, target_per_category=target_per_category
    )
    selected_cases: list[SelectedChallengeCase] = []
    for sequence, alternative in enumerate(selected_alternatives, start=1):
        connection = _connection(alternative, sequence=sequence, config=config)
        outcome = retrospective_connection_outcome(
            connection,
            inbound=_retrospective_call(population, alternative.inbound.source_call_id),
            outbound=_retrospective_call(population, alternative.outbound.source_call_id),
            scenario=alternative.scenario,
        )
        observed_category = classify_challenge_category(
            transfer_duration=outcome.transfer_duration,
            retrospective_slack=outcome.retrospective_slack,
            retrospective_no_itt_slack=outcome.retrospective_no_itt_slack,
        )
        if observed_category is not alternative.category:
            raise ValueError("challenge category changed while building selected case")
        case_digest = canonical_digest(
            {
                "version": TERMINAL_PREVENTION_CHALLENGE_VERSION,
                "sequence": sequence,
                "category": _selection_category_token(alternative.category),
                "scenario": alternative.scenario,
                "identity": connection.identity,
                "assignment": connection.assignment,
            }
        )
        selected_cases.append(
            SelectedChallengeCase(
                challenge_case_id=f"TPC-V1-{sequence:02d}-{case_digest[:12].upper()}",
                category=alternative.category,
                scenario=alternative.scenario,
                selection_rank=alternative.selection_rank,
                connection=connection,
                retrospective_outcome=outcome,
            )
        )

    selected_tuple = tuple(selected_cases)
    graph_payload = tuple(item.connection.identity for item in selected_tuple)
    graph_digest = canonical_digest(graph_payload)
    candidate_counts = tuple(
        ChallengeCandidateCount(
            scenario=scenario.value,
            category=category.value,
            count=sum(
                item.scenario is scenario and item.category is category
                for item in alternatives
            ),
        )
        for scenario in _SCENARIO_ORDER
        for category in _CATEGORY_ORDER
    )
    category_selections = tuple(
        ChallengeCategorySelection(
            category=category.value,
            target=target_per_category,
            selected=sum(item.category is category for item in selected_tuple),
            shortfall=max(
                target_per_category
                - sum(item.category is category for item in selected_tuple),
                0,
            ),
        )
        for category in _CATEGORY_ORDER
    )
    ordered_ids = tuple(item.challenge_case_id for item in selected_tuple)
    challenge_set_digest = canonical_digest(
        tuple(
            {
                "challenge_case_id": item.challenge_case_id,
                "category": item.category,
                "scenario": item.scenario,
                "selection_rank": item.selection_rank,
                "connection": item.connection,
                "retrospective_outcome": item.retrospective_outcome,
            }
            for item in selected_tuple
        )
    )
    manifest_base = {
        "generator_version": CHALLENGE_SELECTION_RULE_VERSION,
        "topology_version": CHALLENGE_TOPOLOGY_VERSION,
        "seed": CHALLENGE_SELECTION_RULE_VERSION,
        "input_digest": input_digest,
        "config_digest": canonical_digest(
            {
                "process_assumptions": config.process_assumptions,
                "difficulty_thresholds": config.difficulty_thresholds,
                "evidence": config.evidence,
            }
        ),
        "quota_digest": canonical_digest(
            {
                "curated_categories": _CATEGORY_ORDER,
                "target_per_category": target_per_category,
                "inter_terminal_patterns": _INTER_TERMINAL_PATTERNS,
            }
        ),
        "graph_digest": graph_digest,
        "source_candidate_count": source_count,
        "requested_connection_count": target_per_category * len(_CATEGORY_ORDER),
        "generated_connection_count": len(selected_tuple),
        "dataset_sha256": config.dataset_sha256,
        "boundary_versions": tuple(
            sorted(
                {
                    candidate.boundary_version
                    for item in selected_tuple
                    for candidate in (
                        item.connection.assignment.inbound_candidate,
                        item.connection.assignment.outbound_candidate,
                    )
                }
            )
        ),
        "terminal_code_list_version": SMDG_TCL_VERSION,
    }
    manifest = GenerationManifest(
        **manifest_base,
        output_digest=canonical_digest(
            {
                "challenge_set_version": TERMINAL_PREVENTION_CHALLENGE_VERSION,
                "challenge_set_digest": challenge_set_digest,
                "connections": tuple(item.connection for item in selected_tuple),
                "manifest": manifest_base,
            }
        ),
    )
    return TerminalPreventionChallengeSelection(
        source_candidate_count=source_count,
        candidate_input_digest=input_digest,
        candidate_counts=candidate_counts,
        category_selections=category_selections,
        selected_cases=selected_tuple,
        benchmark=SyntheticBenchmark(
            connections=tuple(item.connection for item in selected_tuple),
            manifest=manifest,
        ),
        ordered_case_ids=ordered_ids,
        challenge_set_digest=challenge_set_digest,
    )


def causal_prevention_signal(
    *,
    assessment_available: bool,
    current_plan_slack_hours: float | None,
    no_itt_slack_hours: float | None,
) -> bool:
    """Return the operational counterfactual using causal values only."""

    return (
        assessment_available
        and current_plan_slack_hours is not None
        and no_itt_slack_hours is not None
        and current_plan_slack_hours <= 0
        and no_itt_slack_hours > 0
    )


def first_causal_prevention_signal(
    records: Iterable[HistoricalAssessmentRecord],
    *,
    cutoff: datetime,
) -> HistoricalAssessmentRecord | None:
    """Select the earliest qualifying causal record no later than cutoff."""

    ordered = sorted(
        (record for record in records if record.assessed_at <= cutoff),
        key=lambda record: (
            record.assessed_at,
            record.trigger_cursor,
            record.trigger_source_call_id,
        ),
    )
    return next(
        (
            record
            for record in ordered
            if causal_prevention_signal(
                assessment_available=(
                    record.status == AssessmentStatus.AVAILABLE.value
                ),
                current_plan_slack_hours=record.current_plan_slack_h,
                no_itt_slack_hours=record.no_itt_slack_h,
            )
        ),
        None,
    )


def _first_signal_observation_for_connection(
    connection: SyntheticConnection,
    *,
    replay_calls: Mapping[str, tuple],
    scenario: ProcessScenario,
    cutoff: datetime,
) -> CausalPreventionSignalObservation | None:
    assignment = connection.assignment
    updates = tuple(
        sorted(
            (
                *replay_calls[assignment.inbound_source_call_id],
                *replay_calls[assignment.outbound_source_call_id],
            ),
            key=update_cursor,
        )
    )
    activation = connection_activation(connection).active_cursor
    projection = next(
        item
        for item in connection.process_projections
        if item.scenario is scenario
    )
    latest_available = {}
    for update in updates:
        if update.observed_at > cutoff:
            break
        if (
            update.prediction_status is PredictionStatus.AVAILABLE
            and update.predicted_arrival is not None
            and update.reference_arrival is not None
        ):
            latest_available[update.call_id] = update
        if update_cursor(update) < activation:
            continue
        inbound = latest_available.get(assignment.inbound_source_call_id)
        outbound = latest_available.get(assignment.outbound_source_call_id)
        if inbound is None or outbound is None:
            continue
        assert inbound.predicted_arrival is not None
        assert outbound.predicted_arrival is not None
        no_itt = (
            outbound.predicted_arrival
            - projection.cargo_cutoff_lead
            - (inbound.predicted_arrival + projection.cargo_ready_offset)
        )
        current = no_itt - projection.transfer_duration
        if causal_prevention_signal(
            assessment_available=True,
            current_plan_slack_hours=_hours(current),
            no_itt_slack_hours=_hours(no_itt),
        ):
            return CausalPreventionSignalObservation(
                assessed_at=update.observed_at,
                current_plan_slack_hours=_hours(current),
                no_itt_slack_hours=_hours(no_itt),
                watcher_state=RiskSeverity.AT_RISK.value,
            )
    return None


def _causal_actionability_rank(alternative: ChallengeAlternative) -> str:
    return canonical_digest(
        {
            "version": CAUSAL_ACTIONABILITY_CAPABILITY_VERSION,
            "scenario": alternative.scenario,
            "inbound_candidate_id": alternative.inbound.candidate_id,
            "outbound_candidate_id": alternative.outbound.candidate_id,
            "origin_terminal": alternative.origin_terminal,
            "destination_terminal": alternative.destination_terminal,
            "transfer_mode": alternative.transfer_mode,
        }
    )


def _alternative_cutoff(
    alternative: ChallengeAlternative, config: SyntheticBenchmarkConfig
) -> datetime:
    assumptions = _process_assumptions(config, alternative.scenario)
    return alternative.outbound.final_crossing - assumptions.cargo_cutoff_lead


def build_causal_actionability_capability_selection(
    population: HistoricalCallPopulation,
    config: SyntheticBenchmarkConfig,
    *,
    target: int = CAUSAL_ACTIONABILITY_TARGET,
) -> CausalActionabilityCapabilitySelection:
    """Select deterministic REFERENCE cases that contain a causal signal."""

    if target < 1:
        raise ValueError("causal-actionability target must be positive")
    _assert_frozen_process_configuration(config)
    alternatives, _, source_count = discover_challenge_alternatives(
        population, config
    )
    ranked = tuple(
        sorted(
            (
                (_causal_actionability_rank(item), item)
                for item in alternatives
                if item.scenario is ProcessScenario.REFERENCE
            ),
            key=lambda pair: (pair[0], pair[1].descriptor_key),
        )
    )
    replay_calls = {
        call.call_id: call.updates for call in population.replay_calls
    }
    qualifying: list[
        tuple[str, ChallengeAlternative, CausalPreventionSignalObservation]
    ] = []
    for sequence, (rank, alternative) in enumerate(ranked, start=1):
        provisional = _connection(
            alternative,
            sequence=sequence,
            config=config,
            topology_version=CAUSAL_ACTIONABILITY_TOPOLOGY_VERSION,
        )
        signal = _first_signal_observation_for_connection(
            provisional,
            replay_calls=replay_calls,
            scenario=ProcessScenario.REFERENCE,
            cutoff=_alternative_cutoff(alternative, config),
        )
        if signal is not None:
            qualifying.append((rank, alternative, signal))

    chosen = tuple(qualifying[:target])
    selected_cases: list[SelectedCausalActionabilityCase] = []
    for sequence, (rank, alternative, _) in enumerate(chosen, start=1):
        connection = _connection(
            alternative,
            sequence=sequence,
            config=config,
            topology_version=CAUSAL_ACTIONABILITY_TOPOLOGY_VERSION,
        )
        signal = _first_signal_observation_for_connection(
            connection,
            replay_calls=replay_calls,
            scenario=ProcessScenario.REFERENCE,
            cutoff=_alternative_cutoff(alternative, config),
        )
        if signal is None:
            raise AssertionError("selected causal-actionability signal disappeared")
        outcome = retrospective_connection_outcome(
            connection,
            inbound=_retrospective_call(population, alternative.inbound.source_call_id),
            outbound=_retrospective_call(population, alternative.outbound.source_call_id),
            scenario=ProcessScenario.REFERENCE,
        )
        case_digest = canonical_digest(
            {
                "version": CAUSAL_ACTIONABILITY_CAPABILITY_VERSION,
                "sequence": sequence,
                "selection_rank": rank,
                "identity": connection.identity,
                "assignment": connection.assignment,
            }
        )
        selected_cases.append(
            SelectedCausalActionabilityCase(
                capability_case_id=(
                    f"CAP-V1-{sequence:02d}-{case_digest[:12].upper()}"
                ),
                selection_rank=rank,
                connection=connection,
                retrospective_category=classify_challenge_category(
                    transfer_duration=outcome.transfer_duration,
                    retrospective_slack=outcome.retrospective_slack,
                    retrospective_no_itt_slack=outcome.retrospective_no_itt_slack,
                ),
                retrospective_outcome=outcome,
            )
        )

    selected_tuple = tuple(selected_cases)
    graph_digest = canonical_digest(
        tuple(item.connection.identity for item in selected_tuple)
    )
    ordered_ids = tuple(item.capability_case_id for item in selected_tuple)
    capability_set_digest = canonical_digest(
        tuple(
            {
                "capability_case_id": item.capability_case_id,
                "selection_rank": item.selection_rank,
                "connection": item.connection,
                "retrospective_category": item.retrospective_category,
                "retrospective_outcome": item.retrospective_outcome,
            }
            for item in selected_tuple
        )
    )
    manifest_base = {
        "generator_version": CAUSAL_ACTIONABILITY_CAPABILITY_VERSION,
        "topology_version": CAUSAL_ACTIONABILITY_TOPOLOGY_VERSION,
        "seed": CAUSAL_ACTIONABILITY_CAPABILITY_VERSION,
        "input_digest": canonical_digest(
            tuple(
                {
                    "selection_rank": rank,
                    "descriptor": alternative.descriptor_key,
                    "first_signal": signal,
                }
                for rank, alternative, signal in qualifying
            )
        ),
        "config_digest": canonical_digest(
            {
                "process_assumptions": config.process_assumptions,
                "difficulty_thresholds": config.difficulty_thresholds,
                "evidence": config.evidence,
            }
        ),
        "quota_digest": canonical_digest(
            {
                "category": "CAUSALLY_ACTIONABLE_PREVENTION",
                "target": target,
                "scenario": ProcessScenario.REFERENCE,
            }
        ),
        "graph_digest": graph_digest,
        "source_candidate_count": source_count,
        "requested_connection_count": target,
        "generated_connection_count": len(selected_tuple),
        "dataset_sha256": config.dataset_sha256,
        "boundary_versions": tuple(
            sorted(
                {
                    candidate.boundary_version
                    for item in selected_tuple
                    for candidate in (
                        item.connection.assignment.inbound_candidate,
                        item.connection.assignment.outbound_candidate,
                    )
                }
            )
        ),
        "terminal_code_list_version": SMDG_TCL_VERSION,
    }
    manifest = GenerationManifest(
        **manifest_base,
        output_digest=canonical_digest(
            {
                "version": CAUSAL_ACTIONABILITY_CAPABILITY_VERSION,
                "capability_set_digest": capability_set_digest,
                "connections": tuple(item.connection for item in selected_tuple),
                "manifest": manifest_base,
            }
        ),
    )
    return CausalActionabilityCapabilitySelection(
        version=CAUSAL_ACTIONABILITY_CAPABILITY_VERSION,
        curation=CAUSAL_ACTIONABILITY_CURATION_LABEL,
        scenario=ProcessScenario.REFERENCE.value,
        candidate_count=len(qualifying),
        target=target,
        selected=len(selected_tuple),
        shortfall=max(target - len(selected_tuple), 0),
        ordered_case_ids=ordered_ids,
        graph_digest=graph_digest,
        capability_set_digest=capability_set_digest,
        benchmark=SyntheticBenchmark(
            connections=tuple(item.connection for item in selected_tuple),
            manifest=manifest,
        ),
        selected_cases=selected_tuple,
    )


def _case_detection(
    case: SelectedChallengeCase,
    result: HistoricalEvaluationResult,
) -> CausalChallengeDetection:
    cutoff = case.retrospective_outcome.retrospective_outbound_cutoff
    records = tuple(
        sorted(
            (
                record
                for record in result.records
                if record.ucid == case.connection.identity.ucid
                and record.assessed_at <= cutoff
            ),
            key=lambda record: (
                record.assessed_at,
                record.trigger_cursor,
                record.trigger_source_call_id,
            ),
        )
    )
    available = tuple(
        record
        for record in records
        if record.status == AssessmentStatus.AVAILABLE.value
    )
    alerts = tuple(
        record
        for record in available
        if record.severity in (RiskSeverity.WATCH.value, RiskSeverity.AT_RISK.value)
    )
    first_alert = alerts[0] if alerts else None
    first_prevention_signal = first_causal_prevention_signal(
        records, cutoff=cutoff
    )
    if case.category is ChallengeCategory.RETROSPECTIVE_PREVENTION_OPPORTUNITY:
        consistent = (
            (first_prevention_signal,) if first_prevention_signal is not None else ()
        )
    elif case.category is ChallengeCategory.UNRECOVERABLE_WITH_NO_ITT:
        consistent = tuple(
            record
            for record in alerts
            if record.no_itt_slack_h is not None and record.no_itt_slack_h <= 0
        )
    else:
        consistent = () if first_prevention_signal is not None else available[:1]
    first_consistent = consistent[0] if consistent else None
    behaviour = (
        first_consistent is not None
        if case.category is not ChallengeCategory.FEASIBLE_WITH_ITT
        else bool(available)
        and first_prevention_signal is None
    )
    retrospective_actionability = None
    if case.category is ChallengeCategory.RETROSPECTIVE_PREVENTION_OPPORTUNITY:
        if first_prevention_signal is not None:
            retrospective_actionability = (
                RetrospectivePreventionActionability.CAUSALLY_ACTIONABLE.value
            )
        elif not available:
            retrospective_actionability = (
                RetrospectivePreventionActionability.NO_CAUSAL_ASSESSMENT_BEFORE_CUTOFF.value
            )
        elif (
            first_alert is not None
            and first_alert.no_itt_slack_h is not None
            and first_alert.no_itt_slack_h <= 0
        ):
            retrospective_actionability = (
                RetrospectivePreventionActionability.ALERTED_AFTER_PREVENTION_WINDOW_CLOSED.value
            )
        else:
            retrospective_actionability = (
                RetrospectivePreventionActionability.NO_CAUSAL_PREVENTION_SIGNAL_BEFORE_CUTOFF.value
            )
    return CausalChallengeDetection(
        first_watcher_assessment_available=(
            available[0].assessed_at if available else None
        ),
        first_watch_or_at_risk_timestamp=(
            first_alert.assessed_at if first_alert is not None else None
        ),
        synthetic_cutoff=cutoff,
        first_alert_lead_time_hours=(
            _hours(cutoff - first_alert.assessed_at)
            if first_alert is not None
            else None
        ),
        causal_current_plan_slack_hours_at_first_alert=(
            first_alert.current_plan_slack_h if first_alert is not None else None
        ),
        causal_no_itt_slack_hours_at_first_alert=(
            first_alert.no_itt_slack_h if first_alert is not None else None
        ),
        causal_prevention_signal_before_cutoff=(
            first_prevention_signal is not None
        ),
        first_causal_prevention_signal_timestamp=(
            first_prevention_signal.assessed_at
            if first_prevention_signal is not None
            else None
        ),
        first_causal_prevention_signal_lead_time_hours=(
            _hours(cutoff - first_prevention_signal.assessed_at)
            if first_prevention_signal is not None
            else None
        ),
        causal_current_plan_slack_hours_at_first_prevention_signal=(
            first_prevention_signal.current_plan_slack_h
            if first_prevention_signal is not None
            else None
        ),
        causal_no_itt_slack_hours_at_first_prevention_signal=(
            first_prevention_signal.no_itt_slack_h
            if first_prevention_signal is not None
            else None
        ),
        recovered_slack_from_removing_itt_hours_at_first_prevention_signal=(
            first_prevention_signal.no_itt_slack_h
            - first_prevention_signal.current_plan_slack_h
            if first_prevention_signal is not None
            and first_prevention_signal.no_itt_slack_h is not None
            and first_prevention_signal.current_plan_slack_h is not None
            else None
        ),
        watcher_state_at_risk_at_first_prevention_signal=(
            first_prevention_signal.severity == RiskSeverity.AT_RISK.value
            if first_prevention_signal is not None
            else None
        ),
        retrospective_prevention_actionability=retrospective_actionability,
        first_category_consistent_signal_timestamp=(
            first_consistent.assessed_at if first_consistent is not None else None
        ),
        category_behaviour_observed=behaviour,
    )


def _interpretation(
    case: SelectedChallengeCase, detection: CausalChallengeDetection
) -> str:
    observed = detection.category_behaviour_observed
    if case.category is ChallengeCategory.RETROSPECTIVE_PREVENTION_OPPORTUNITY:
        if detection.retrospective_prevention_actionability == (
            RetrospectivePreventionActionability.ALERTED_AFTER_PREVENTION_WINDOW_CLOSED.value
        ):
            return (
                "Retrospectively preventable, but the Watcher alert arrived after "
                "causal no-ITT slack was no longer positive."
            )
        if detection.retrospective_prevention_actionability == (
            RetrospectivePreventionActionability.NO_CAUSAL_ASSESSMENT_BEFORE_CUTOFF.value
        ):
            return (
                "Retrospectively preventable, but no causal Watcher assessment "
                "was available before cutoff."
            )
        statement = "reached" if observed else "did not reach"
        return (
            f"Watcher {statement} the causal current-plan-infeasible / "
            "no-ITT-feasible prevention state before cutoff."
        )
    if case.category is ChallengeCategory.UNRECOVERABLE_WITH_NO_ITT:
        statement = "showed" if observed else "did not show"
        return (
            f"Watcher {statement} before cutoff that removing ITT was insufficient "
            "once risk was causally observable."
        )
    if detection.first_watcher_assessment_available is None:
        return (
            "No causal Watcher assessment was available before cutoff, so this "
            "case did not demonstrate feasible-case discrimination."
        )
    statement = "avoided" if observed else "did not avoid"
    return (
        f"Watcher {statement} a causal terminal-prevention signal before cutoff "
        "for this retrospectively feasible curated case."
    )


def _retrospective_definition(
    category: ChallengeCategory,
    outcome: RetrospectiveConnectionOutcome,
) -> RetrospectiveChallengeDefinition:
    return RetrospectiveChallengeDefinition(
        retrospective_category=category.value,
        retrospective_prevention_opportunity=(
            category
            is ChallengeCategory.RETROSPECTIVE_PREVENTION_OPPORTUNITY
        ),
        retrospective_current_plan_slack_hours=outcome.retrospective_slack_h,
        retrospective_no_itt_slack_hours=outcome.retrospective_no_itt_slack_h,
        transfer_duration_hours=_hours(outcome.transfer_duration),
        recovered_margin_from_removing_itt_hours=_hours(
            outcome.retrospective_no_itt_slack - outcome.retrospective_slack
        ),
    )


def build_terminal_prevention_challenge_report(
    frozen_reference_result: HistoricalEvaluationResult,
    *,
    synthetic_config: SyntheticBenchmarkConfig,
    dataset_hash: str,
    target_per_category: int = CHALLENGE_TARGET_PER_CATEGORY,
) -> TerminalPreventionChallengeReport:
    """Select retrospectively, then evaluate selected cases with causal replay."""

    if dataset_hash != synthetic_config.dataset_sha256:
        raise ValueError("dataset hash does not match the challenge configuration")
    population_before = frozen_reference_result.population
    benchmark_before = frozen_reference_result.benchmark
    selection = build_terminal_prevention_challenge_selection(
        population_before,
        synthetic_config,
        target_per_category=target_per_category,
    )
    causal_actionability = build_causal_actionability_capability_selection(
        population_before,
        synthetic_config,
        target=CAUSAL_ACTIONABILITY_TARGET,
    )
    selected_scenarios = tuple(
        scenario
        for scenario in _SCENARIO_ORDER
        if any(item.scenario is scenario for item in selection.selected_cases)
    )
    scenario_results = {
        scenario: replay_watcher_assessments(
            population_before,
            selection.benchmark,
            WatcherConfig(
                warning_margin=FROZEN_PR5_REFERENCE_MARGIN,
                reference_delay_threshold=FROZEN_BASELINE_THRESHOLD,
                process_scenario=scenario,
            ),
        )
        for scenario in selected_scenarios
    }
    if (
        frozen_reference_result.population != population_before
        or frozen_reference_result.benchmark != benchmark_before
    ):
        raise AssertionError("challenge construction mutated the frozen benchmark")
    case_results: list[TerminalPreventionChallengeCaseResult] = []
    for case in selection.selected_cases:
        outcome = case.retrospective_outcome
        detection = _case_detection(case, scenario_results[case.scenario])
        case_results.append(
            TerminalPreventionChallengeCaseResult(
                identity=ChallengeCaseIdentity(
                    challenge_case_id=case.challenge_case_id,
                    ucid=case.connection.identity.ucid,
                    category=case.category.value,
                    scenario=case.scenario.value,
                    inbound_call_id=case.connection.assignment.inbound_source_call_id,
                    outbound_call_id=case.connection.assignment.outbound_source_call_id,
                    origin_terminal=case.connection.origin.terminal.value,
                    destination_terminal=case.connection.destination.terminal.value,
                    transfer_mode=case.connection.reference_projection.transfer_mode.value,
                    selection_rank=case.selection_rank,
                ),
                retrospective_challenge_definition=_retrospective_definition(
                    case.category, outcome
                ),
                causal_detection=detection,
                interpretation=_interpretation(case, detection),
            )
        )
    capability_replay = replay_watcher_assessments(
        population_before,
        causal_actionability.benchmark,
        WatcherConfig(
            warning_margin=FROZEN_PR5_REFERENCE_MARGIN,
            reference_delay_threshold=FROZEN_BASELINE_THRESHOLD,
            process_scenario=ProcessScenario.REFERENCE,
        ),
    )
    capability_case_results: list[TerminalPreventionChallengeCaseResult] = []
    for selected in causal_actionability.selected_cases:
        evaluation_case = SelectedChallengeCase(
            challenge_case_id=selected.capability_case_id,
            category=selected.retrospective_category,
            scenario=ProcessScenario.REFERENCE,
            selection_rank=selected.selection_rank,
            connection=selected.connection,
            retrospective_outcome=selected.retrospective_outcome,
        )
        detection = _case_detection(evaluation_case, capability_replay)
        if not detection.causal_prevention_signal_before_cutoff:
            raise AssertionError(
                "causal-actionability case lost its qualifying causal signal"
            )
        detection = replace(
            detection,
            first_category_consistent_signal_timestamp=(
                detection.first_causal_prevention_signal_timestamp
            ),
            category_behaviour_observed=True,
        )
        capability_case_results.append(
            TerminalPreventionChallengeCaseResult(
                identity=ChallengeCaseIdentity(
                    challenge_case_id=selected.capability_case_id,
                    ucid=selected.connection.identity.ucid,
                    category="CAUSALLY_ACTIONABLE_PREVENTION",
                    scenario=ProcessScenario.REFERENCE.value,
                    inbound_call_id=(
                        selected.connection.assignment.inbound_source_call_id
                    ),
                    outbound_call_id=(
                        selected.connection.assignment.outbound_source_call_id
                    ),
                    origin_terminal=selected.connection.origin.terminal.value,
                    destination_terminal=(
                        selected.connection.destination.terminal.value
                    ),
                    transfer_mode=(
                        selected.connection.reference_projection.transfer_mode.value
                    ),
                    selection_rank=selected.selection_rank,
                ),
                retrospective_challenge_definition=_retrospective_definition(
                    selected.retrospective_category,
                    selected.retrospective_outcome,
                ),
                causal_detection=detection,
                interpretation=(
                    "This deliberately curated capability case reached the causal "
                    "current-plan-infeasible / no-ITT-feasible state before cutoff."
                ),
            )
        )
    return TerminalPreventionChallengeReport(
        report_version=TERMINAL_PREVENTION_CHALLENGE_VERSION,
        challenge_set_version=TERMINAL_PREVENTION_CHALLENGE_VERSION,
        selection_rule_version=CHALLENGE_SELECTION_RULE_VERSION,
        curation=CHALLENGE_CURATION_LABEL,
        parent_commit=PR5_PARENT_COMMIT,
        parent_report_version=HISTORICAL_REPORT_VERSION,
        dataset_hash=dataset_hash,
        input_population_digest=population_before.population_digest,
        input_candidate_digest=selection.candidate_input_digest,
        frozen_historical_graph_digest=benchmark_before.manifest.graph_digest,
        frozen_historical_graph_output_digest=benchmark_before.manifest.output_digest,
        challenge_graph_digest=selection.benchmark.manifest.graph_digest,
        challenge_set_digest=selection.challenge_set_digest,
        source_candidate_count=selection.source_candidate_count,
        target_per_category=target_per_category,
        candidate_counts=selection.candidate_counts,
        category_selections=selection.category_selections,
        ordered_case_ids=selection.ordered_case_ids,
        cases=tuple(case_results),
        causal_actionability_capability_set=(
            CausalActionabilityCapabilityReport(
                version=causal_actionability.version,
                curation=causal_actionability.curation,
                purpose=(
                    "When the causal current-plan-infeasible / no-ITT-feasible "
                    "state exists, can LATCH represent the terminal-prevention signal?"
                ),
                scenario=causal_actionability.scenario,
                candidate_count=causal_actionability.candidate_count,
                target=causal_actionability.target,
                selected=causal_actionability.selected,
                shortfall=causal_actionability.shortfall,
                ordered_case_ids=causal_actionability.ordered_case_ids,
                graph_digest=causal_actionability.graph_digest,
                capability_set_digest=(
                    causal_actionability.capability_set_digest
                ),
                cases=tuple(capability_case_results),
                limitations=(
                    "The set is deliberately curated from causal state existence, not an unbiased sample.",
                    "It does not estimate prevalence, operational recall or precision, PSA effectiveness, or recoverable historical share.",
                ),
            )
        ),
        provenance=(
            "Vessel timing comes from the frozen AIS-derived historical call population.",
            "Retrospective final crossings curate cases; they never enter causal Watcher replay.",
            "Causal prevention signals use only available causal slack values at each replay assessment.",
            "Inter-terminal patterns and process projections reuse unchanged documented synthetic assumptions.",
            "The frozen 32-connection graph remains a separate experiment and population.",
        ),
        limitations=(
            "Curated challenge cases are a behavioural capability test, not a prevalence estimate or unbiased historical sample.",
            "Counts are denominated only by curated challenge cases and are not PSA operational effectiveness metrics.",
            "A synthetic prevention opportunity is not a real rescued container or actual saved connection.",
        ),
    )


def validate_challenge_output_path(path: str | Path) -> Path:
    target = Path(path)
    if target.suffix.lower() != ".json":
        raise ValueError("terminal prevention challenge output must end in .json")
    normalized = target.as_posix().lower()
    forbidden = (
        "historical-watcher-report",
        "watcher-refinement-report",
        "readme.md",
        "singapore_ais_dataset_assessment.md",
    )
    if any(token in normalized for token in forbidden):
        raise ValueError("challenge output must not target frozen evidence or reports")
    if "/artifacts/historical/" in f"/{normalized}":
        raise ValueError("challenge output must not enter the historical artifact population")
    if "/fixtures/synthetic/" in f"/{normalized}":
        raise ValueError("challenge output must not target PR #3 fixtures")
    if target.exists():
        if not target.is_file():
            raise ValueError("terminal prevention challenge output must be a JSON file")
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ValueError(
                "challenge writer will not overwrite an unrelated file"
            ) from None
        required = {
            "report_version",
            "challenge_set_version",
            "selection_rule_version",
            "curation",
            "cases",
            "causal_actionability_capability_set",
            "provenance",
            "limitations",
        }
        if not isinstance(payload, dict) or not required <= payload.keys():
            raise ValueError(
                "challenge writer will not overwrite an unrelated JSON file"
            )
        if payload.get("report_version") != TERMINAL_PREVENTION_CHALLENGE_VERSION:
            raise ValueError("challenge writer will not overwrite another report contract")
    return target


def write_terminal_prevention_challenge_report(
    report: TerminalPreventionChallengeReport, path: str | Path
) -> None:
    target = validate_challenge_output_path(path)
    target.write_text(report.to_json(indent=2) + "\n", encoding="utf-8")
