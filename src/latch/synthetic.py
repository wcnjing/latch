"""Deterministic synthetic transshipment connections over causal AIS updates.

The source population is still retrospectively segmented into accepted PR #2
calls: PR #2 does not expose a completely live call-population primitive.  A
source ``call_id`` is used only to locate the first ``AVAILABLE`` update for a
call.  That update is projected immediately into ``SyntheticCallCandidate``;
crossing metadata, retrospective eligibility, exclusions, and later
predictions are not generator inputs.

The generator is pure.  It performs no file I/O, reads no clock, mutates no
input, and uses canonical SHA-256 ranking rather than runtime PRNG state.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, fields, is_dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum, StrEnum
from types import MappingProxyType
from typing import Iterable, Mapping

from latch.models import Terminal, TerminalResolution
from latch.replay import CausalArrivalUpdate, PredictionStatus


UNECE_TRANSSHIPMENT_WHITE_PAPER = (
    "https://unece.org/trade/documents/2025/11/"
    "white-paper-transshipment-potential-closer-integration-between-actors"
)
MPA_PSA_AIGF_EOI = (
    "https://www.mpa.gov.sg/docs/mpalibraries/mpa-documents-files/ittd/"
    "mpa-psa-expression-of-interest-to-design-and-develop-aigf.pdf"
    "?Status=Master&sfvrsn=c6cde904_7"
)
MPA_PSA_AIGF_CLARIFICATIONS = (
    "https://www.mpa.gov.sg/api/media/e39c5ffe-8693-4605-b724-e3e5b062f34c/"
    "MPA-PSA-aIGF-EOI-Clarifications.pdf"
)
SMDG_TCL_V20260609 = (
    "https://smdg.org/documents/smdg-code-lists/smdg-terminal-code-list/"
)
EXPERIMENT_CONFIG_REFERENCE = "latch://synthetic-ucid/pr3-experiment-config"

TOPOLOGY_VERSION = "synthetic-connection-topology-v1"
GENERATOR_VERSION = "synthetic-ucid-generator-v1"
SMDG_TCL_VERSION = "v20260609"
PORT_UN_LOCODE = "SGSIN"


class ValueOrigin(StrEnum):
    REAL = "real"
    DERIVED = "derived"
    SYNTHETIC = "synthetic"


class AssumptionBasis(StrEnum):
    PUBLIC_ANCHOR = "public_anchor"
    EXPERIMENTAL = "experimental"
    NOT_APPLICABLE = "not_applicable"


class TransferMode(StrEnum):
    NONE = "none"
    ROAD = "road"
    SEA = "sea"


class ProcessScenario(StrEnum):
    LOW = "low"
    REFERENCE = "reference"
    CONSERVATIVE = "conservative"


class ImpactBand(StrEnum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


class DifficultyBand(StrEnum):
    COMFORTABLE = "comfortable"
    STANDARD = "standard"
    TIGHT = "tight"
    INFEASIBLE = "infeasible"


class ImpossibleQuotaError(ValueError):
    """Raised instead of returning a partial benchmark."""


class DuplicateCandidateError(ValueError):
    """Raised when causal candidate content cannot identify distinct records."""


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class BenchmarkEvidence:
    field_name: str
    value_origin: ValueOrigin
    assumption_basis: AssumptionBasis
    source_reference: str
    note: str

    def __post_init__(self) -> None:
        if not self.field_name.strip():
            raise ValueError("evidence field_name must not be empty")
        if not self.source_reference.strip():
            raise ValueError("evidence source_reference must not be empty")
        if self.value_origin is ValueOrigin.SYNTHETIC and (
            self.assumption_basis is not AssumptionBasis.EXPERIMENTAL
        ):
            raise ValueError("synthetic values must have an experimental basis")


@dataclass(frozen=True, slots=True)
class BenchmarkTerminal:
    terminal: Terminal
    port_un_locode: str
    smdg_terminal_code: str
    terminal_resolution: TerminalResolution
    tcl_version: str

    def __post_init__(self) -> None:
        if self.terminal not in (Terminal.TUAS, Terminal.PASIR_PANJANG):
            raise ValueError("core benchmark terminals are Tuas and Pasir Panjang only")
        if self.port_un_locode != PORT_UN_LOCODE:
            raise ValueError(f"core benchmark port must be {PORT_UN_LOCODE}")
        if self.terminal_resolution is not TerminalResolution.SIMULATED:
            raise ValueError("synthetic terminal assignments must be simulated")


TUAS_TERMINAL = BenchmarkTerminal(
    terminal=Terminal.TUAS,
    port_un_locode=PORT_UN_LOCODE,
    smdg_terminal_code="PSATUA",
    terminal_resolution=TerminalResolution.SIMULATED,
    tcl_version=SMDG_TCL_VERSION,
)
PASIR_PANJANG_TERMINAL = BenchmarkTerminal(
    terminal=Terminal.PASIR_PANJANG,
    port_un_locode=PORT_UN_LOCODE,
    smdg_terminal_code="PSAPPT",
    terminal_resolution=TerminalResolution.SIMULATED,
    tcl_version=SMDG_TCL_VERSION,
)
CORE_TERMINALS: Mapping[Terminal, BenchmarkTerminal] = MappingProxyType(
    {
        Terminal.TUAS: TUAS_TERMINAL,
        Terminal.PASIR_PANJANG: PASIR_PANJANG_TERMINAL,
    }
)


@dataclass(frozen=True, slots=True)
class SyntheticCallCandidate:
    """Outcome-free projection of one call's first AVAILABLE update.

    Candidate, source-call, and vessel identifiers deliberately do not live in
    this value.  They are retained only by ``UCIDAssignment`` for audit lineage.
    """

    reference_observed_at: datetime
    reference_arrival: datetime
    source_row_number: int
    boundary_version: str
    source_type: str

    def __post_init__(self) -> None:
        _require_aware(self.reference_observed_at, "reference_observed_at")
        _require_aware(self.reference_arrival, "reference_arrival")
        if self.reference_arrival < self.reference_observed_at:
            raise ValueError("reference_arrival must not precede its observation")
        if self.source_row_number < 1:
            raise ValueError("source_row_number must be positive")
        if not self.boundary_version.strip() or not self.source_type.strip():
            raise ValueError("candidate provenance strings must not be empty")


@dataclass(frozen=True, slots=True)
class ReferenceArrivalWindow:
    """Immutable synthetic connection interval from causal reference arrivals.

    This is the interval between the inbound and outbound first-AVAILABLE
    causal reference arrivals used to identify a synthetic benchmark
    connection.  It is not an official vessel schedule, berth window, cargo
    cutoff window, PSA service window, or process-scenario result.
    """

    inbound_reference_arrival: datetime
    outbound_reference_arrival: datetime

    def __post_init__(self) -> None:
        _require_aware(self.inbound_reference_arrival, "inbound_reference_arrival")
        _require_aware(self.outbound_reference_arrival, "outbound_reference_arrival")
        if self.outbound_reference_arrival <= self.inbound_reference_arrival:
            raise ValueError("outbound reference arrival must follow inbound reference arrival")


@dataclass(frozen=True, slots=True)
class UCIDConnectionIdentity:
    """Identity of a time-bound connection slot, never of its vessel calls."""

    port_un_locode: str
    origin_terminal: Terminal
    destination_terminal: Terminal
    reference_arrival_window: ReferenceArrivalWindow
    topology_version: str
    sequence: int
    digest: str
    ucid: str

    def __post_init__(self) -> None:
        if self.port_un_locode != PORT_UN_LOCODE:
            raise ValueError(f"UCID port must be {PORT_UN_LOCODE}")
        if self.origin_terminal not in CORE_TERMINALS:
            raise ValueError("origin terminal is outside the core benchmark")
        if self.destination_terminal not in CORE_TERMINALS:
            raise ValueError("destination terminal is outside the core benchmark")
        if self.sequence < 1:
            raise ValueError("UCID sequence must be positive")
        if not self.topology_version.strip():
            raise ValueError("topology_version must not be empty")
        expected = _ucid_digest(
            port_un_locode=self.port_un_locode,
            origin_terminal=self.origin_terminal,
            destination_terminal=self.destination_terminal,
            reference_arrival_window=self.reference_arrival_window,
            topology_version=self.topology_version,
            sequence=self.sequence,
        )
        if self.digest != expected:
            raise ValueError("UCID digest does not match its connection identity")
        expected_ucid = (
            f"UCID-{self.port_un_locode}-{self.sequence:04d}-{self.digest[:12].upper()}"
        )
        if self.ucid != expected_ucid:
            raise ValueError("UCID string does not match its connection identity")


@dataclass(frozen=True, slots=True)
class UCIDAssignment:
    """Auditable vessel-call assignment to an independently stable UCID."""

    identity: UCIDConnectionIdentity
    inbound_candidate: SyntheticCallCandidate
    outbound_candidate: SyntheticCallCandidate
    inbound_candidate_id: str
    outbound_candidate_id: str
    inbound_source_call_id: str
    outbound_source_call_id: str
    inbound_vessel_id: str
    outbound_vessel_id: str

    def __post_init__(self) -> None:
        if self.inbound_candidate_id == self.outbound_candidate_id:
            raise ValueError("a candidate cannot connect to itself")
        if self.inbound_vessel_id == self.outbound_vessel_id:
            raise ValueError("a vessel cannot connect to itself")
        if self.identity.reference_arrival_window != ReferenceArrivalWindow(
            self.inbound_candidate.reference_arrival,
            self.outbound_candidate.reference_arrival,
        ):
            raise ValueError("assignment reference timing must match the UCID slot")


@dataclass(frozen=True, slots=True)
class ProcessAssumptions:
    scenario: ProcessScenario
    cargo_ready_offset: timedelta
    cargo_cutoff_lead: timedelta
    road_transfer_duration: timedelta
    sea_transfer_duration: timedelta

    def __post_init__(self) -> None:
        if self.cargo_ready_offset < timedelta(0):
            raise ValueError("cargo_ready_offset must not be negative")
        if self.cargo_cutoff_lead < timedelta(0):
            raise ValueError("cargo_cutoff_lead must not be negative")
        if self.road_transfer_duration <= timedelta(0):
            raise ValueError("road_transfer_duration must be positive")
        if self.sea_transfer_duration <= timedelta(0):
            raise ValueError("sea_transfer_duration must be positive")

    def transfer_duration(self, mode: TransferMode) -> timedelta:
        if mode is TransferMode.NONE:
            return timedelta(0)
        if mode is TransferMode.ROAD:
            return self.road_transfer_duration
        return self.sea_transfer_duration


@dataclass(frozen=True, slots=True)
class DifficultyThresholds:
    tight_upper_bound: timedelta
    standard_upper_bound: timedelta

    def __post_init__(self) -> None:
        if self.standard_upper_bound <= self.tight_upper_bound:
            raise ValueError("difficulty thresholds must be strictly increasing")

    def classify(self, planning_margin: timedelta) -> DifficultyBand:
        if planning_margin < timedelta(0):
            return DifficultyBand.INFEASIBLE
        if planning_margin < self.tight_upper_bound:
            return DifficultyBand.TIGHT
        if planning_margin < self.standard_upper_bound:
            return DifficultyBand.STANDARD
        return DifficultyBand.COMFORTABLE


@dataclass(frozen=True, slots=True)
class ProcessProjection:
    scenario: ProcessScenario
    cargo_ready_offset: timedelta
    cargo_ready_at: datetime
    cargo_cutoff_lead: timedelta
    planned_cutoff: datetime
    transfer_mode: TransferMode
    transfer_duration: timedelta
    planning_margin: timedelta
    difficulty_band: DifficultyBand


@dataclass(frozen=True, slots=True)
class ReferenceArrivalGapBand:
    """Scenario-independent inclusive/exclusive raw reference-arrival gap."""

    minimum_gap: timedelta = timedelta(0)
    maximum_gap: timedelta | None = None

    def __post_init__(self) -> None:
        if self.minimum_gap < timedelta(0):
            raise ValueError("minimum reference-arrival gap must not be negative")
        if self.maximum_gap is not None and self.maximum_gap <= self.minimum_gap:
            raise ValueError("maximum reference-arrival gap must exceed minimum gap")

    def contains(self, gap: timedelta) -> bool:
        return gap >= self.minimum_gap and (
            self.maximum_gap is None or gap < self.maximum_gap
        )


@dataclass(frozen=True, slots=True)
class BenchmarkQuota:
    origin_terminal: Terminal
    destination_terminal: Terminal
    transfer_mode: TransferMode
    impact_band: ImpactBand
    count: int
    reference_arrival_gap_band: ReferenceArrivalGapBand | None = None
    box_count: int | None = None

    def __post_init__(self) -> None:
        if self.origin_terminal not in CORE_TERMINALS:
            raise ValueError("quota origin terminal is outside the core benchmark")
        if self.destination_terminal not in CORE_TERMINALS:
            raise ValueError("quota destination terminal is outside the core benchmark")
        same_terminal = self.origin_terminal == self.destination_terminal
        if same_terminal and self.transfer_mode is not TransferMode.NONE:
            raise ValueError("same-terminal quotas must use transfer mode NONE")
        if not same_terminal and self.transfer_mode not in (
            TransferMode.ROAD,
            TransferMode.SEA,
        ):
            raise ValueError("inter-terminal quotas must use ROAD or SEA")
        if self.count < 1:
            raise ValueError("quota count must be positive")
        if self.box_count is not None and self.box_count < 1:
            raise ValueError("box_count must be positive when supplied")


@dataclass(frozen=True, slots=True)
class SyntheticConnection:
    identity: UCIDConnectionIdentity
    assignment: UCIDAssignment
    origin: BenchmarkTerminal
    destination: BenchmarkTerminal
    impact_band: ImpactBand
    box_count: int | None
    process_projections: tuple[ProcessProjection, ...]
    evidence: tuple[BenchmarkEvidence, ...]

    @property
    def reference_projection(self) -> ProcessProjection:
        return next(
            item
            for item in self.process_projections
            if item.scenario is ProcessScenario.REFERENCE
        )


@dataclass(frozen=True, slots=True)
class GenerationManifest:
    generator_version: str
    topology_version: str
    seed: str
    input_digest: str
    config_digest: str
    quota_digest: str
    graph_digest: str
    output_digest: str
    source_candidate_count: int
    requested_connection_count: int
    generated_connection_count: int
    dataset_sha256: str
    boundary_versions: tuple[str, ...]
    terminal_code_list_version: str


@dataclass(frozen=True, slots=True)
class SyntheticBenchmark:
    connections: tuple[SyntheticConnection, ...]
    manifest: GenerationManifest


@dataclass(frozen=True, slots=True)
class SyntheticBenchmarkConfig:
    seed: str
    topology_version: str
    dataset_sha256: str
    quotas: tuple[BenchmarkQuota, ...]
    process_assumptions: tuple[ProcessAssumptions, ...]
    difficulty_thresholds: DifficultyThresholds
    evidence: tuple[BenchmarkEvidence, ...]

    def __post_init__(self) -> None:
        if not self.seed:
            raise ValueError("seed must not be empty")
        if not self.topology_version.strip():
            raise ValueError("topology_version must not be empty")
        if not self.dataset_sha256.strip():
            raise ValueError("dataset_sha256 must not be empty")
        if not self.quotas:
            raise ValueError("at least one explicit quota cell is required")
        scenarios = [item.scenario for item in self.process_assumptions]
        if sorted(scenarios) != sorted(ProcessScenario):
            raise ValueError("process assumptions must define LOW, REFERENCE, and CONSERVATIVE once")
        evidence_by_field = {item.field_name: item for item in self.evidence}
        if len(evidence_by_field) != len(self.evidence):
            raise ValueError("evidence field names must be unique")
        missing = REQUIRED_EVIDENCE_FIELDS.difference(evidence_by_field)
        if missing:
            raise ValueError(f"missing required evidence: {sorted(missing)}")

REQUIRED_EVIDENCE_FIELDS = frozenset(
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


def approved_assumption_register() -> tuple[BenchmarkEvidence, ...]:
    """Return the complete PR #3 evidence register using approved sources."""

    real_na = AssumptionBasis.NOT_APPLICABLE
    public = AssumptionBasis.PUBLIC_ANCHOR
    experimental = AssumptionBasis.EXPERIMENTAL
    return (
        BenchmarkEvidence(
            "ais_source_fields",
            ValueOrigin.REAL,
            real_na,
            "doi:10.17632/r37vwd493d.1",
            "Real timestamped AIS fields retained without synthetic replacement.",
        ),
        BenchmarkEvidence(
            "first_available_reference_arrival",
            ValueOrigin.DERIVED,
            real_na,
            "latch://replay/pr2-causal-arrival-update",
            "First AVAILABLE causal reference only; no later prediction or crossing outcome.",
        ),
        BenchmarkEvidence(
            "reference_arrival_window",
            ValueOrigin.DERIVED,
            real_na,
            "latch://synthetic-ucid/pr3-causal-reference-window",
            "Immutable interval between paired first-AVAILABLE causal reference arrivals; not an official service window.",
        ),
        BenchmarkEvidence(
            "reference_arrival_gap",
            ValueOrigin.DERIVED,
            real_na,
            "latch://synthetic-ucid/pr3-causal-reference-window",
            "Outbound minus inbound first-AVAILABLE causal reference arrival.",
        ),
        BenchmarkEvidence(
            "reference_arrival_gap_band",
            ValueOrigin.SYNTHETIC,
            experimental,
            EXPERIMENT_CONFIG_REFERENCE,
            "Optional topology quota interval over the raw causal reference-arrival gap.",
        ),
        BenchmarkEvidence(
            "candidate_id",
            ValueOrigin.DERIVED,
            real_na,
            "latch://synthetic-ucid/pr3-canonical-candidate-digest",
            "Canonical digest of identifier-free first-AVAILABLE candidate content.",
        ),
        BenchmarkEvidence(
            "source_call_lineage",
            ValueOrigin.DERIVED,
            experimental,
            "latch://replay/pr2-retrospective-call-segmentation",
            "Audit-only PR #2 call grouping derived with the exploratory boundary.",
        ),
        BenchmarkEvidence(
            "vessel_lineage",
            ValueOrigin.REAL,
            real_na,
            "doi:10.17632/r37vwd493d.1",
            "Audit-only anonymised AIS vessel identifier; used for self-pair rejection.",
        ),
        BenchmarkEvidence(
            "terminal_identity_tuas",
            ValueOrigin.REAL,
            public,
            SMDG_TCL_V20260609,
            "SMDG TCL v20260609 identifies SGSIN + PSATUA.",
        ),
        BenchmarkEvidence(
            "terminal_identity_pasir_panjang",
            ValueOrigin.REAL,
            public,
            SMDG_TCL_V20260609,
            "SMDG TCL v20260609 identifies SGSIN + PSAPPT.",
        ),
        BenchmarkEvidence(
            "terminal_cluster_context",
            ValueOrigin.REAL,
            public,
            MPA_PSA_AIGF_EOI,
            "MPA/PSA describe Pasir Panjang and Tuas as the main terminal clusters.",
        ),
        BenchmarkEvidence(
            "terminal_assignment",
            ValueOrigin.SYNTHETIC,
            experimental,
            EXPERIMENT_CONFIG_REFERENCE,
            "Candidate-to-terminal assignment is simulated, not observed.",
        ),
        BenchmarkEvidence(
            "candidate_pairing",
            ValueOrigin.SYNTHETIC,
            experimental,
            EXPERIMENT_CONFIG_REFERENCE,
            "Pairing is canonical seeded benchmark construction.",
        ),
        BenchmarkEvidence(
            "topology_version_and_sequence",
            ValueOrigin.SYNTHETIC,
            experimental,
            EXPERIMENT_CONFIG_REFERENCE,
            "Frozen topology/schema version and deterministic connection sequence.",
        ),
        BenchmarkEvidence(
            "transfer_mode_catalog",
            ValueOrigin.REAL,
            public,
            MPA_PSA_AIGF_EOI,
            "MPA/PSA describe road and sea feeder as real IGT modes.",
        ),
        BenchmarkEvidence(
            "transfer_mode_assignment",
            ValueOrigin.SYNTHETIC,
            experimental,
            EXPERIMENT_CONFIG_REFERENCE,
            "Mode assignment is requested by an explicit quota cell.",
        ),
        BenchmarkEvidence(
            "process_scenario_configuration",
            ValueOrigin.SYNTHETIC,
            experimental,
            EXPERIMENT_CONFIG_REFERENCE,
            "LOW, REFERENCE, and CONSERVATIVE are test-only sensitivity configurations applied after topology is frozen.",
        ),
        BenchmarkEvidence(
            "cargo_ready_offset",
            ValueOrigin.SYNTHETIC,
            experimental,
            EXPERIMENT_CONFIG_REFERENCE,
            "Single benchmark offset absorbs generic terminal handling before IGT.",
        ),
        BenchmarkEvidence(
            "cargo_ready_at",
            ValueOrigin.DERIVED,
            experimental,
            EXPERIMENT_CONFIG_REFERENCE,
            "Inbound reference arrival plus experimental cargo_ready_offset.",
        ),
        BenchmarkEvidence(
            "cargo_cutoff_lead",
            ValueOrigin.SYNTHETIC,
            experimental,
            UNECE_TRANSSHIPMENT_WHITE_PAPER,
            "Configured benchmark lead informed by feeder cut-off context; not a PSA rule.",
        ),
        BenchmarkEvidence(
            "transfer_duration",
            ValueOrigin.SYNTHETIC,
            experimental,
            EXPERIMENT_CONFIG_REFERENCE,
            "Actual benchmark duration comes only from scenario configuration.",
        ),
        BenchmarkEvidence(
            "planned_cutoff",
            ValueOrigin.DERIVED,
            experimental,
            EXPERIMENT_CONFIG_REFERENCE,
            "Outbound reference arrival minus configured cargo_cutoff_lead.",
        ),
        BenchmarkEvidence(
            "planning_margin",
            ValueOrigin.DERIVED,
            experimental,
            EXPERIMENT_CONFIG_REFERENCE,
            "Planned cutoff minus cargo-ready time and configured transfer duration.",
        ),
        BenchmarkEvidence(
            "impact_band",
            ValueOrigin.SYNTHETIC,
            experimental,
            EXPERIMENT_CONFIG_REFERENCE,
            "Required scenario label; quotas do not claim PSA prevalence.",
        ),
        BenchmarkEvidence(
            "box_count",
            ValueOrigin.SYNTHETIC,
            experimental,
            EXPERIMENT_CONFIG_REFERENCE,
            "Optional exact synthetic volume; impact_band remains required.",
        ),
        BenchmarkEvidence(
            "difficulty_band",
            ValueOrigin.DERIVED,
            experimental,
            EXPERIMENT_CONFIG_REFERENCE,
            "Derived from planning margin and frozen experimental thresholds.",
        ),
        BenchmarkEvidence(
            "ucid_identity",
            ValueOrigin.SYNTHETIC,
            experimental,
            UNECE_TRANSSHIPMENT_WHITE_PAPER,
            "Connection-slot identity inspired by UCID; not an official assigned UCID.",
        ),
        BenchmarkEvidence(
            "public_sea_transit_reference",
            ValueOrigin.REAL,
            public,
            MPA_PSA_AIGF_CLARIFICATIONS,
            "Approximately 13 nm and four-hour aIGF transit mission profile; evidence metadata only.",
        ),
    )


def to_primitive(value: object) -> object:
    """Convert supported immutable benchmark values to canonical JSON data."""

    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        _require_aware(value, "canonical datetime")
        return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    if isinstance(value, timedelta):
        return value.days * 86_400_000_000 + value.seconds * 1_000_000 + value.microseconds
    if is_dataclass(value):
        if isinstance(value, type):
            raise TypeError("dataclass classes are not supported canonical values")
        return {field.name: to_primitive(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        canonical_mapping: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(
                    "canonical mapping keys must be strings; "
                    f"got {type(key).__name__}"
                )
            canonical_mapping[key] = to_primitive(item)
        return canonical_mapping
    if isinstance(value, (tuple, list)):
        return [to_primitive(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported canonical value: {type(value).__name__}")


def canonical_json(value: object) -> str:
    return json.dumps(
        to_primitive(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def canonical_digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _candidate_key(candidate: SyntheticCallCandidate) -> tuple[object, ...]:
    return (
        candidate.reference_observed_at,
        candidate.source_row_number,
        candidate.reference_arrival,
        candidate.boundary_version,
        candidate.source_type,
    )


def _candidate_payload(candidate: SyntheticCallCandidate) -> dict[str, object]:
    return {
        "reference_observed_at": candidate.reference_observed_at,
        "reference_arrival": candidate.reference_arrival,
        "source_row_number": candidate.source_row_number,
        "boundary_version": candidate.boundary_version,
        "source_type": candidate.source_type,
    }


@dataclass(frozen=True, slots=True)
class _CandidateLineage:
    candidate: SyntheticCallCandidate
    candidate_id: str
    source_call_id: str
    vessel_id: str


def _extract_first_available_candidates(
    updates: Iterable[CausalArrivalUpdate],
) -> tuple[_CandidateLineage, ...]:
    """Project one first AVAILABLE update from each accepted PR #2 call."""

    by_call: dict[str, list[CausalArrivalUpdate]] = {}
    for update in updates:
        by_call.setdefault(update.call_id, []).append(update)

    projected: list[_CandidateLineage] = []
    for source_call_id, call_updates in by_call.items():
        available = sorted(
            (
                update
                for update in call_updates
                if update.prediction_status is PredictionStatus.AVAILABLE
            ),
            key=lambda update: (
                update.observed_at,
                update.source_observation.source_row_number,
            ),
        )
        if not available:
            continue
        first = available[0]
        if first.reference_arrival is None or first.predicted_arrival is None:
            raise ValueError("AVAILABLE update must contain reference and predicted arrival")
        if first.reference_arrival != first.predicted_arrival:
            raise ValueError("first AVAILABLE update must establish its reference arrival")
        candidate = SyntheticCallCandidate(
            reference_observed_at=first.observed_at,
            reference_arrival=first.reference_arrival,
            source_row_number=first.source_observation.source_row_number,
            boundary_version=first.boundary_version,
            source_type=first.source_type,
        )
        candidate_id = f"candidate_{canonical_digest(_candidate_payload(candidate))[:20]}"
        projected.append(
            _CandidateLineage(
                candidate=candidate,
                candidate_id=candidate_id,
                source_call_id=source_call_id,
                vessel_id=first.vessel_id,
            )
        )

    projected.sort(key=lambda item: _candidate_key(item.candidate))
    ids = [item.candidate_id for item in projected]
    if len(set(ids)) != len(ids):
        raise DuplicateCandidateError(
            "first-AVAILABLE causal content produced duplicate candidate IDs"
        )
    return tuple(projected)


def project_first_available_candidates(
    updates: Iterable[CausalArrivalUpdate],
) -> tuple[SyntheticCallCandidate, ...]:
    """Expose only the identifier-free first-AVAILABLE candidate projection."""

    return tuple(
        item.candidate for item in _extract_first_available_candidates(updates)
    )


def _ucid_digest(
    *,
    port_un_locode: str,
    origin_terminal: Terminal,
    destination_terminal: Terminal,
    reference_arrival_window: ReferenceArrivalWindow,
    topology_version: str,
    sequence: int,
) -> str:
    return canonical_digest(
        {
            "port_un_locode": port_un_locode,
            "origin_terminal": origin_terminal,
            "destination_terminal": destination_terminal,
            "reference_arrival_window": reference_arrival_window,
            "topology_version": topology_version,
            "sequence": sequence,
        }
    )


def make_ucid_identity(
    *,
    origin_terminal: Terminal,
    destination_terminal: Terminal,
    reference_arrival_window: ReferenceArrivalWindow,
    topology_version: str,
    sequence: int,
) -> UCIDConnectionIdentity:
    digest = _ucid_digest(
        port_un_locode=PORT_UN_LOCODE,
        origin_terminal=origin_terminal,
        destination_terminal=destination_terminal,
        reference_arrival_window=reference_arrival_window,
        topology_version=topology_version,
        sequence=sequence,
    )
    return UCIDConnectionIdentity(
        port_un_locode=PORT_UN_LOCODE,
        origin_terminal=origin_terminal,
        destination_terminal=destination_terminal,
        reference_arrival_window=reference_arrival_window,
        topology_version=topology_version,
        sequence=sequence,
        digest=digest,
        ucid=f"UCID-{PORT_UN_LOCODE}-{sequence:04d}-{digest[:12].upper()}",
    )


def project_process(
    reference_arrival_window: ReferenceArrivalWindow,
    transfer_mode: TransferMode,
    assumptions: ProcessAssumptions,
    thresholds: DifficultyThresholds,
) -> ProcessProjection:
    transfer_duration = assumptions.transfer_duration(transfer_mode)
    cargo_ready_at = (
        reference_arrival_window.inbound_reference_arrival
        + assumptions.cargo_ready_offset
    )
    planned_cutoff = (
        reference_arrival_window.outbound_reference_arrival
        - assumptions.cargo_cutoff_lead
    )
    planning_margin = planned_cutoff - cargo_ready_at - transfer_duration
    return ProcessProjection(
        scenario=assumptions.scenario,
        cargo_ready_offset=assumptions.cargo_ready_offset,
        cargo_ready_at=cargo_ready_at,
        cargo_cutoff_lead=assumptions.cargo_cutoff_lead,
        planned_cutoff=planned_cutoff,
        transfer_mode=transfer_mode,
        transfer_duration=transfer_duration,
        planning_margin=planning_margin,
        difficulty_band=thresholds.classify(planning_margin),
    )


def _pair_rank(
    seed: str,
    quota: BenchmarkQuota,
    inbound: SyntheticCallCandidate,
    outbound: SyntheticCallCandidate,
) -> str:
    # Deliberately excludes source call IDs, vessel IDs, candidate IDs, impact,
    # process assumptions, and projected difficulty. Vessel identity is
    # consulted only by the self-pair guard.
    return canonical_digest(
        {
            "seed": seed,
            "purpose": "synthetic-call-pair",
            "origin_terminal": quota.origin_terminal,
            "destination_terminal": quota.destination_terminal,
            "transfer_mode": quota.transfer_mode,
            "reference_arrival_gap_band": quota.reference_arrival_gap_band,
            "inbound": _candidate_payload(inbound),
            "outbound": _candidate_payload(outbound),
        }
    )


def _eligible_pairs(
    candidates: tuple[_CandidateLineage, ...],
    quota: BenchmarkQuota,
    seed: str,
) -> list[tuple[_CandidateLineage, _CandidateLineage]]:
    pairs: list[tuple[str, _CandidateLineage, _CandidateLineage]] = []
    for inbound in candidates:
        for outbound in candidates:
            if inbound.candidate_id == outbound.candidate_id:
                continue
            if inbound.vessel_id == outbound.vessel_id:
                continue
            if outbound.candidate.reference_arrival <= inbound.candidate.reference_arrival:
                continue
            gap = (
                outbound.candidate.reference_arrival
                - inbound.candidate.reference_arrival
            )
            if (
                quota.reference_arrival_gap_band is not None
                and not quota.reference_arrival_gap_band.contains(gap)
            ):
                continue
            pairs.append(
                (
                    _pair_rank(
                        seed,
                        quota,
                        inbound.candidate,
                        outbound.candidate,
                    ),
                    inbound,
                    outbound,
                )
            )
    pairs.sort(
        key=lambda item: (
            item[0],
            _candidate_key(item[1].candidate),
            _candidate_key(item[2].candidate),
        )
    )
    return [(inbound, outbound) for _, inbound, outbound in pairs]


def _pair_key(
    pair: tuple[_CandidateLineage, _CandidateLineage],
) -> tuple[str, str]:
    inbound, outbound = pair
    return inbound.candidate_id, outbound.candidate_id


def _allocate_quota_slots(
    candidates: tuple[_CandidateLineage, ...],
    config: SyntheticBenchmarkConfig,
) -> tuple[tuple[BenchmarkQuota, _CandidateLineage, _CandidateLineage], ...]:
    """Find a deterministic global matching of quota slots to ordered pairs."""

    slots: list[
        tuple[
            BenchmarkQuota,
            tuple[tuple[_CandidateLineage, _CandidateLineage], ...],
        ]
    ] = []
    for quota in config.quotas:
        eligible = tuple(_eligible_pairs(candidates, quota, config.seed))
        if len(eligible) < quota.count:
            raise ImpossibleQuotaError(
                "impossible quota cell: "
                f"{quota.origin_terminal.value}->{quota.destination_terminal.value} "
                f"{quota.transfer_mode.value}/{quota.impact_band.value} "
                f"requested={quota.count} eligible_pairs={len(eligible)}"
            )
        slots.extend((quota, eligible) for _ in range(quota.count))

    pair_owner: dict[tuple[str, str], int] = {}
    slot_assignment: dict[
        int, tuple[_CandidateLineage, _CandidateLineage]
    ] = {}

    def augment(start_slot_index: int) -> bool:
        seen_pairs: set[tuple[str, str]] = set()
        seen_slots = {start_slot_index}
        stack: list[
            tuple[
                int,
                int,
                tuple[_CandidateLineage, _CandidateLineage] | None,
            ]
        ] = [(start_slot_index, 0, None)]

        while stack:
            slot_index, pair_index, incoming_pair = stack[-1]
            eligible_pairs = slots[slot_index][1]
            if pair_index >= len(eligible_pairs):
                stack.pop()
                continue

            pair = eligible_pairs[pair_index]
            stack[-1] = (slot_index, pair_index + 1, incoming_pair)
            key = _pair_key(pair)
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            owner = pair_owner.get(key)
            if owner is None:
                replacement_pair = pair
                for path_slot, _, path_incoming_pair in reversed(stack):
                    pair_owner[_pair_key(replacement_pair)] = path_slot
                    slot_assignment[path_slot] = replacement_pair
                    if path_incoming_pair is None:
                        break
                    replacement_pair = path_incoming_pair
                return True
            if owner in seen_slots:
                continue
            seen_slots.add(owner)
            stack.append((owner, 0, pair))
        return False

    matching_order = sorted(
        range(len(slots)),
        key=lambda index: (len(slots[index][1]), index),
    )
    for slot_index in matching_order:
        if not augment(slot_index):
            quota = slots[slot_index][0]
            raise ImpossibleQuotaError(
                "impossible global quota allocation: "
                f"slot={slot_index + 1} "
                f"{quota.origin_terminal.value}->{quota.destination_terminal.value} "
                f"{quota.transfer_mode.value}/{quota.impact_band.value}"
            )

    return tuple(
        (slots[index][0], *slot_assignment[index]) for index in range(len(slots))
    )


def _connection_evidence(config: SyntheticBenchmarkConfig) -> tuple[BenchmarkEvidence, ...]:
    by_name = {item.field_name: item for item in config.evidence}
    return tuple(by_name[name] for name in sorted(REQUIRED_EVIDENCE_FIELDS))


def generate_synthetic_benchmark(
    updates: Iterable[CausalArrivalUpdate],
    config: SyntheticBenchmarkConfig,
) -> SyntheticBenchmark:
    """Generate an exact, immutable benchmark or fail without partial output."""

    candidates = _extract_first_available_candidates(updates)
    requested = sum(quota.count for quota in config.quotas)
    selected = _allocate_quota_slots(candidates, config)

    evidence = _connection_evidence(config)
    connections: list[SyntheticConnection] = []
    for sequence, (quota, inbound, outbound) in enumerate(selected, start=1):
        reference_arrival_window = ReferenceArrivalWindow(
            inbound.candidate.reference_arrival,
            outbound.candidate.reference_arrival,
        )
        identity = make_ucid_identity(
            origin_terminal=quota.origin_terminal,
            destination_terminal=quota.destination_terminal,
            reference_arrival_window=reference_arrival_window,
            topology_version=config.topology_version,
            sequence=sequence,
        )
        assignment = UCIDAssignment(
            identity=identity,
            inbound_candidate=inbound.candidate,
            outbound_candidate=outbound.candidate,
            inbound_candidate_id=inbound.candidate_id,
            outbound_candidate_id=outbound.candidate_id,
            inbound_source_call_id=inbound.source_call_id,
            outbound_source_call_id=outbound.source_call_id,
            inbound_vessel_id=inbound.vessel_id,
            outbound_vessel_id=outbound.vessel_id,
        )
        projections = tuple(
            project_process(
                reference_arrival_window,
                quota.transfer_mode,
                assumptions,
                config.difficulty_thresholds,
            )
            for assumptions in sorted(
                config.process_assumptions,
                key=lambda item: list(ProcessScenario).index(item.scenario),
            )
        )
        connections.append(
            SyntheticConnection(
                identity=identity,
                assignment=assignment,
                origin=CORE_TERMINALS[quota.origin_terminal],
                destination=CORE_TERMINALS[quota.destination_terminal],
                impact_band=quota.impact_band,
                box_count=quota.box_count,
                process_projections=projections,
                evidence=evidence,
            )
        )

    connection_tuple = tuple(connections)
    graph_payload = tuple(connection.identity for connection in connection_tuple)
    input_payload = tuple(item.candidate for item in candidates)
    manifest_without_output = {
        "generator_version": GENERATOR_VERSION,
        "topology_version": config.topology_version,
        "seed": config.seed,
        "input_digest": canonical_digest(input_payload),
        "config_digest": canonical_digest(
            {
                "process_assumptions": config.process_assumptions,
                "difficulty_thresholds": config.difficulty_thresholds,
                "evidence": config.evidence,
            }
        ),
        "quota_digest": canonical_digest(config.quotas),
        "graph_digest": canonical_digest(graph_payload),
        "source_candidate_count": len(candidates),
        "requested_connection_count": requested,
        "generated_connection_count": len(connection_tuple),
        "dataset_sha256": config.dataset_sha256,
        "boundary_versions": tuple(
            sorted({item.candidate.boundary_version for item in candidates})
        ),
        "terminal_code_list_version": SMDG_TCL_VERSION,
    }
    manifest = GenerationManifest(
        **manifest_without_output,
        output_digest=canonical_digest(
            {
                "connections": connection_tuple,
                "manifest": manifest_without_output,
            }
        ),
    )
    return SyntheticBenchmark(connections=connection_tuple, manifest=manifest)


def generate_synthetic_benchmark_from_csv(
    csv_path: str,
    config: SyntheticBenchmarkConfig,
) -> SyntheticBenchmark:
    """I/O boundary using PR #2's unfiltered retrospectively segmented source."""

    from latch.replay import iter_retrospectively_segmented_arrival_updates

    return generate_synthetic_benchmark(
        iter_retrospectively_segmented_arrival_updates(csv_path),
        config,
    )
