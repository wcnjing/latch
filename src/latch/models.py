"""Domain contracts for LATCH.

This module is the boundary between the three workstreams. Workstream A
produces `ConnectionRisk`; workstream C renders `Trace` and supplies the
production confidence engine. Everything here is a frozen dataclass or an
enum, and nothing here imports from the rest of the package.

Treat changes to this file as breaking. Announce them.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

# Priority uses 1/slack, so slack has to be floored somewhere above zero or a
# connection that is already blown outranks everything else forever.
MIN_SLACK_HOURS = 0.25


class Terminal(StrEnum):
    """SGSIN container terminals.

    Whether we can actually resolve a vessel call to one of these is the
    subject of the day-1 data gate. `UNKNOWN` is a real, expected value —
    see `TerminalResolution`.
    """

    TUAS = "tuas"
    PASIR_PANJANG = "pasir_panjang"
    BRANI = "brani"
    KEPPEL = "keppel"
    UNKNOWN = "unknown"


class TerminalResolution(StrEnum):
    """How a terminal assignment was arrived at.

    Carried on every vessel call so the provenance of the inter-terminal
    split is never rhetorical. If the public OCEANS-X tier turns out to be
    port-level only, this field is what makes the resulting claim honest
    instead of implied — and it feeds the confidence calculation directly.
    """

    BERTH = "berth"  # exact berth in the feed
    TERMINAL = "terminal"  # terminal named in the feed
    INFERRED = "inferred"  # derived from the service rotation, with error
    SIMULATED = "simulated"  # synthetic layer; no claim to reality


class SourceKind(StrEnum):
    """Where a value came from. Ordered worst-to-best is deliberate."""

    ASSUMED_DEFAULT = "assumed_default"
    CACHE = "cache"
    LIVE_API = "live_api"


class ToolOutcome(StrEnum):
    OK = "ok"
    RETRIED = "retried"
    FAILED = "failed"


class Rung(StrEnum):
    """Rungs are categories of authority — who must approve — not a cost order.

    Rung 2 (absorb / resequence discharge) was cut: it needs a stowage and
    crane model we would get wrong. The gap in the numbering is intentional
    and should stay visible.
    """

    INFORM = "rung_1_inform"  # berth planner decides
    MOVE = "rung_3_move"  # vessel ops decides
    OFFER = "rung_4_offer"  # the shipping line decides


class ApprovalRole(StrEnum):
    """Who the Gate Controller requires a signature from."""

    AUTO = "auto"  # no human in the loop
    BERTH_PLANNER = "berth_planner"
    VESSEL_OPS = "vessel_ops"
    DUTY_MANAGER = "duty_manager"
    CUSTOMER = "customer"  # the line; external, cannot be compelled


class ActionKind(StrEnum):
    """What a plan actually does.

    Every one of these terminates in a stub. We do not have write access to
    any terminal system and are not pretending otherwise — the interfaces are
    modelled on the message semantics named beside them, and the contribution
    is the decision layer above.
    """

    SURFACE_DENSITY_SCORE = "surface_density_score"  # advisory only
    BOOK_ITT_LEG = "book_itt_leg"  # cf. IFTMBF booking request
    AMEND_DISCHARGE_ORDER = "amend_discharge_order"  # cf. COPRAR
    OFFER_OPTIONS_TO_LINE = "offer_options_to_line"  # cf. IFTSAI / JIT APIs
    ROLL_TO_NEXT_SERVICE = "roll_to_next_service"  # the default action
    NO_ACTION = "no_action"


class Resolution(StrEnum):
    """Terminal verdict for a risk.

    The three customer-gate outcomes are the product. The box physically
    rolls in all three; only one of them is a service failure.
    """

    CONNECTION_HELD = "connection_held"  # resolved internally, box connects
    CUSTOMER_DECIDED = "customer_decided"  # line chose in time
    CUSTOMER_DECLINED_ALL = "customer_declined_all"  # line rejected everything
    WINDOW_LAPSED_NO_RESPONSE = "window_lapsed_no_response"  # nobody answered
    DISMISSED_NO_ACTION = "dismissed_no_action"  # triage killed it
    SUPERSEDED = "superseded"  # ETA improved; abandoned cleanly
    FAILED = "failed"  # we broke, not the connection

    @property
    def is_service_success(self) -> bool:
        """Did the customer hold a live decision before the window closed?

        This is the north-star metric, and the distinction it draws is the
        entire pitch: a line that explicitly declined every option was still
        served. A line that never heard from us was not.
        """
        return self in (
            Resolution.CONNECTION_HELD,
            Resolution.CUSTOMER_DECIDED,
            Resolution.CUSTOMER_DECLINED_ALL,
        )


@dataclass(frozen=True, slots=True)
class VesselCall:
    """One vessel's call at Singapore, inbound or outbound."""

    vessel_name: str
    service_code: str
    terminal: Terminal
    terminal_resolution: TerminalResolution
    scheduled: datetime
    estimated: datetime
    imo: str | None = None
    berth: str | None = None

    @property
    def deviation_min(self) -> float:
        return (self.estimated - self.scheduled).total_seconds() / 60.0


@dataclass(frozen=True, slots=True)
class ConnectionRisk:
    """A transhipment connection losing slack. The unit of work.

    Emitted by the Watcher (workstream A). The agent core never fetches this
    itself, which is why B does not block on the day-1 data gate: whether the
    inter-terminal split came from a berth field or the synthetic layer is
    recorded in `terminal_resolution` and changes confidence, not control flow.
    """

    risk_id: str
    ucid: str  # aligned with the SMDG/UN-CEFACT Unique Connection ID proposal
    detected_at: datetime
    inbound: VesselCall
    outbound: VesselCall
    boxes_at_risk: int
    slack_total_min: float
    slack_remaining_min: float
    source: str  # e.g. "oceans_x.vessel_movements"
    data_age_min: float = 0.0

    @property
    def eta_deviation_min(self) -> float:
        return self.inbound.deviation_min

    @property
    def slack_consumed_pct(self) -> float:
        """Fraction of the connection window already burned.

        This, not delay magnitude, is what the Watcher triggers on. A six-hour
        slip against thirty hours of slack is nothing; a ninety-minute slip
        against two hours is critical.
        """
        if self.slack_total_min <= 0:
            return 1.0
        consumed = 1.0 - (self.slack_remaining_min / self.slack_total_min)
        return min(max(consumed, 0.0), 1.0)

    @property
    def slack_remaining_hours(self) -> float:
        return self.slack_remaining_min / 60.0

    @property
    def priority(self) -> float:
        """boxes_at_risk x (1 / slack_remaining_hours), floored.

        The Lock Table arbitrates on this rather than first-come, so that a
        large cargo volume against a closing window beats a small one that
        merely asked first.
        """
        return self.boxes_at_risk / max(self.slack_remaining_hours, MIN_SLACK_HOURS)

    @property
    def crosses_terminals(self) -> bool:
        return self.inbound.terminal != self.outbound.terminal


@dataclass(frozen=True, slots=True)
class Provenance:
    """Where one input to a plan came from.

    Confidence is computed from a list of these. The model may reason about
    its own certainty; it may never set the number.
    """

    field_name: str
    source: SourceKind
    age_min: float = 0.0
    tool_outcome: ToolOutcome = ToolOutcome.OK
    verified: bool = True


@dataclass(frozen=True, slots=True)
class PlanAction:
    kind: ActionKind
    target: str  # resource key, service code, or party
    detail: str = ""


@dataclass(frozen=True, slots=True)
class Plan:
    """A ranked option produced by Deliberation.

    `confidence` is populated by the confidence engine after construction,
    never by the model. It defaults to 0.0 so an unscored plan cannot
    accidentally pass a gate.
    """

    plan_id: str
    risk_id: str
    rung: Rung
    actions: tuple[PlanAction, ...]
    rationale: str
    cost_sgd: float = 0.0
    emissions_kg_co2e: float = 0.0
    resources_required: tuple[str, ...] = ()
    provenance: tuple[Provenance, ...] = ()
    confidence: float = 0.0
    options_alive: int = 0

    def with_confidence(self, value: float) -> "Plan":
        """Return a copy carrying a computed confidence score."""
        return dataclasses_replace(self, confidence=value)


@dataclass(frozen=True, slots=True)
class CustomerOffer:
    """What goes to the line at Rung 4, and what came back.

    `window_min` is the response window we committed to. `responded_at` being
    None once the window has closed is the failure case — and the only one of
    the three exits that counts as a service failure.
    """

    offer_id: str
    risk_id: str
    options: tuple[Plan, ...]
    sent_at: datetime
    window_min: int
    responded_at: datetime | None = None
    chosen_plan_id: str | None = None
    declined_all: bool = False

    @property
    def options_sent(self) -> int:
        return len(self.options)


@dataclass(slots=True)
class RiskRecord:
    """Mutable working state for one risk as it moves through the ladder.

    The only mutable type in this module. Persisted so a restart mid-
    deliberation resumes rather than restarts.
    """

    risk: ConnectionRisk
    state: str  # RiskState value; typed as str to keep this module import-free
    plans: list[Plan] = field(default_factory=list)
    chosen_plan_id: str | None = None
    offer: CustomerOffer | None = None
    resolution: Resolution | None = None
    approval_role: ApprovalRole = ApprovalRole.AUTO
    held_locks: list[str] = field(default_factory=list)


def dataclasses_replace(obj, /, **changes):
    """`dataclasses.replace` for slotted frozen dataclasses.

    Imported lazily to keep the module's import surface at zero for the
    consumers who only need the types.
    """
    import dataclasses

    return dataclasses.replace(obj, **changes)
