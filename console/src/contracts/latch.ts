/**
 * LATCH — shapes produced by workstream A (Watcher) and workstream B (agent core).
 *
 * Every type here is transcribed from the Python as it actually is, not from
 * the design sketch. Each block cites the file and the function that emits it.
 * Where a shape only exists in process and never crosses a wire, that is said
 * explicitly — the console cannot consume it, and CONTRACTS.md lists what we
 * asked A/B for as a result.
 *
 * Nothing in this file is invented. If the console needs a field that is not
 * below, it goes in CONTRACTS.md under REQUEST TO A/B, not in here.
 *
 * Data honesty: every figure that reaches these shapes rests on real Singapore
 * AIS vessel movement data and arrival estimates derived from it, combined with
 * synthetic transhipment connections (`latch/connections.py`). Container
 * connections, terminals, box counts and loading cut-offs are simulated.
 */

/* ==========================================================================
 * 1. Enumerations
 * src/latch/models.py, events.py, state.py, tools/base.py, triage.py
 * ======================================================================== */

/** models.py :: Terminal */
export type Terminal = 'tuas' | 'pasir_panjang' | 'brani' | 'keppel' | 'unknown';

/** models.py :: TerminalResolution — how the terminal assignment was arrived at. */
export type TerminalResolution = 'berth' | 'terminal' | 'inferred' | 'simulated';

/** models.py :: SourceKind — ordered worst-to-best. */
export type SourceKind = 'assumed_default' | 'cache' | 'live_api';

/** models.py :: ToolOutcome — the confidence engine's view of a tool call. */
export type ToolOutcome = 'ok' | 'retried' | 'failed';

/**
 * models.py :: Rung.
 *
 * Note the gap. Rung 2 (absorb / resequence discharge) was cut in B because it
 * needs a stowage and crane model. The numbering gap is deliberate and B's
 * comment says it should stay visible. See CONTRACTS.md section 2.
 */
export type Rung = 'rung_1_inform' | 'rung_3_move' | 'rung_4_offer';

/** models.py :: ApprovalRole — who the Gate Controller requires a signature from. */
export type ApprovalRole =
  | 'auto'
  | 'berth_planner'
  | 'vessel_ops'
  | 'duty_manager'
  | 'customer';

/** models.py :: ActionKind — what a plan actually does. Every one ends in a stub. */
export type ActionKind =
  | 'surface_density_score'
  | 'book_itt_leg'
  | 'amend_discharge_order'
  | 'offer_options_to_line'
  | 'roll_to_next_service'
  | 'no_action';

/** models.py :: Resolution — terminal verdict for a risk. */
export type Resolution =
  | 'connection_held'
  | 'customer_decided'
  | 'customer_declined_all'
  | 'window_lapsed_no_response'
  | 'dismissed_no_action'
  | 'superseded'
  | 'failed';

/**
 * models.py :: Resolution.is_service_success.
 *
 * Transcribed rather than re-derived so the console cannot disagree with B
 * about which outcomes count. A line that declined every option was served.
 * A line that never heard from us was not.
 */
export const SERVICE_SUCCESS_RESOLUTIONS: readonly Resolution[] = [
  'connection_held',
  'customer_decided',
  'customer_declined_all',
];

/** state.py :: RiskState — the lifecycle. */
export type RiskState =
  | 'detected'
  | 'triaged'
  | 'deliberating'
  | 'awaiting_approval'
  | 'escalated'
  | 'awaiting_customer'
  | 'executing'
  | 'dismissed'
  | 'superseded'
  | 'stale'
  | 'lost_lock'
  | 'lapsed'
  | 'resolved'
  | 'failed';

/** state.py :: TERMINAL_STATES */
export const TERMINAL_STATES: readonly RiskState[] = [
  'resolved',
  'failed',
  'dismissed',
  'superseded',
];

/** events.py :: RiskSeverity — A's own classification. */
export type RiskSeverity = 'SAFE' | 'WATCH' | 'AT_RISK';

/**
 * events.py :: WatcherConfidence.
 *
 * How sure A is that this is a risk at all. NOT the same number as
 * Plan.confidence, which is how much to trust one specific plan. A's
 * confidence is an input to B's and never overwrites it.
 */
export type WatcherConfidence = 'LOW' | 'MEDIUM' | 'HIGH';

/** events.py :: ConnectionType */
export type ConnectionType = 'SAME_TERMINAL' | 'INTER_TERMINAL';

/** events.py :: ReasonCode — why the connection is at risk. */
export type ReasonCode =
  | 'INBOUND_ETA_SLIP'
  | 'OUTBOUND_CUTOFF_ADVANCED'
  | 'INTER_TERMINAL_TRANSFER_TIME'
  | 'BERTH_CONGESTION'
  | 'YARD_CONGESTION'
  | 'DISCHARGE_SEQUENCE';

/**
 * events.py :: _reason_codes.
 *
 * Only the first two are ever emitted by the live Watcher path. The other four
 * are declared in the enum and unreachable today. See CONTRACTS.md section 5.
 */
export const REASON_CODES_EMITTED_BY_WATCHER: readonly ReasonCode[] = [
  'INBOUND_ETA_SLIP',
  'INTER_TERMINAL_TRANSFER_TIME',
];

/** tools/base.py :: ToolStatus */
export type ToolStatus = 'ok' | 'timeout' | 'error' | 'cached_fallback';

/** triage.py :: TriageRoute — how a triage verdict was reached. */
export type TriageRoute =
  | 'dismissed_safe'
  | 'dismissed_too_small'
  | 'fast_tracked'
  | 'model_kept'
  | 'model_dismissed';

/** tools/stubs.py :: TransferMode — road is fast and dirty, barge slow and clean. */
export type TransferMode = 'road' | 'barge';

/** cases.py :: Admission — the supersession registry's verdict per event. */
export type Admission =
  | 'new'
  | 'supersedes'
  | 'duplicate'
  | 'recovered'
  | 'already_resolved';

/* ==========================================================================
 * 2. Frozen policy constants
 * src/latch/config.py — reproduced so the console can render a threshold
 * beside a value without hardcoding a number in a component.
 * ======================================================================== */

export const POLICY = {
  /** config.py :: CONFIDENCE_ESCALATION_THRESHOLD */
  confidenceEscalationThreshold: 0.7,
  /** config.py :: AUTO_APPROVE_MAX_BOXES */
  autoApproveMaxBoxes: 40,
  /** config.py :: AUTO_APPROVE_MAX_COST_SGD */
  autoApproveMaxCostSgd: 8000,
  /** config.py :: CUSTOMER_WINDOW_MIN — the EXTERNAL window put to the line. */
  customerWindowMin: 180,
  /** config.py :: LOCK_TTL_SEC */
  lockTtlSec: 180,
  /** config.py :: SLACK_CONSUMED_TRIGGER — A raises on this, not on delay size. */
  slackConsumedTrigger: 0.6,
  /** config.py :: CONFIDENCE_AGE_SCALE_MIN */
  confidenceAgeScaleMin: 120,
  /** config.py :: CONFIDENCE_UNVERIFIED_PENALTY — linear, per unverified input. */
  confidenceUnverifiedPenalty: 0.05,
  /** config.py :: CONFIDENCE_FLOOR */
  confidenceFloor: 0.05,
  /** models.py :: MIN_SLACK_HOURS — priority denominator floor. */
  minSlackHours: 0.25,
} as const;

/** config.py :: CONFIDENCE_SOURCE_FACTOR */
export const CONFIDENCE_SOURCE_FACTOR: Record<SourceKind, number> = {
  live_api: 1.0,
  cache: 0.85,
  assumed_default: 0.6,
};

/** config.py :: CONFIDENCE_TOOL_FACTOR */
export const CONFIDENCE_TOOL_FACTOR: Record<ToolOutcome, number> = {
  ok: 1.0,
  retried: 0.9,
  failed: 0.7,
};

/**
 * gates.py :: LADDERS — the per-rung escalation path, least to most senior.
 *
 * This is what makes "escalated from X to Y" renderable: index 0 is what the
 * gate would have required with nothing tripped, and the index actually used
 * is min(number of tripped criteria, ladder length - 1).
 */
export const GATE_LADDERS: Record<Rung, readonly ApprovalRole[]> = {
  rung_1_inform: ['berth_planner'],
  rung_3_move: ['auto', 'vessel_ops', 'duty_manager'],
  rung_4_offer: ['vessel_ops', 'duty_manager'],
};

/* ==========================================================================
 * 3. A to B wire format: the risk event
 * src/latch/events.py :: RiskEvent.to_dict() / RiskEvent.from_dict()
 *
 * NOTE the asymmetry, which is real and load-bearing: `from_dict` reads many
 * more keys than `to_dict` writes. A round trip through `to_dict` silently
 * drops terminals, vessel names, source and every assumption flag.
 * See CONTRACTS.md section 4.
 * ======================================================================== */

/** Exactly the keys `RiskEvent.to_dict()` always writes. */
export interface RiskEventWireRequired {
  connection_id: string;
  state: RiskSeverity;
  /** Hours of margin under the plan as it stands. Negative means already short. */
  current_plan_slack_hours: number;
  /** Hours of margin if the inter-terminal transfer requirement were removed. */
  no_itt_slack_hours: number;
  /**
   * A statement of fact — a transfer sits on the critical path — NOT a
   * judgement that removing it would rescue the connection. That judgement is
   * `RiskEvent.itt_is_the_problem`, derived from the two slack figures.
   */
  avoidable_by_terminal_prevention: boolean;
  affected_boxes: number;
  /** Serialised from `watcher_confidence`. The JSON key is `confidence`. */
  confidence: WatcherConfidence;
  reason_codes: ReasonCode[];
}

/** Keys `to_dict()` writes only when present. */
export interface RiskEventWireOptional {
  detected_at?: string;
  ucid?: string;
}

/**
 * Keys `from_dict()` accepts but `to_dict()` never writes. The live Watcher
 * (`watcher.py :: to_risk_event`) sets all of these on the in-process object,
 * so they exist — they just do not survive JSON.
 */
export interface RiskEventWireEnrichment {
  inbound_terminal?: Terminal;
  outbound_terminal?: Terminal;
  terminal_resolution?: TerminalResolution;
  inbound_vessel?: string;
  outbound_vessel?: string;
  source?: string;
}

export type RiskEventWire = RiskEventWireRequired &
  RiskEventWireOptional &
  RiskEventWireEnrichment;

/**
 * events.py :: Assumptions.as_dict().
 *
 * Reaches the console only as the payload of the second `observation` step in
 * a runner-produced trace, spread flat into that step. Not a top-level key
 * anywhere.
 */
export interface AssumptionsWire {
  connection_type: ConnectionType;
  ucid_synthetic: boolean;
  pairing_synthetic: boolean;
  terminals_synthetic: boolean;
  boxes_synthetic: boolean;
  transfer_scenario: string;
  /** Always true. Slack is a scenario output, never an observation. */
  slack_is_scenario_output: boolean;
  /** Always "margin if the transfer requirement were removed". */
  no_itt_slack_means: string;
}

/* ==========================================================================
 * 4. A internals: the synthetic connection layer
 * src/latch/connections.py, src/latch/watcher.py
 *
 * NOT serialised anywhere. Listed because the console has to describe its own
 * data honestly and these are the parameters that decide what "synthetic"
 * means here.
 * ======================================================================== */

/** connections.py :: ConnectionParams.as_dict() — frozen before the agent existed. */
export interface ConnectionParamsWire {
  inter_terminal_share: number;
  min_boxes: number;
  max_boxes: number;
  min_connection_window_h: number;
  max_connection_window_h: number;
  berth_and_discharge_h: number;
  planned_transfer_h: number;
  watch_threshold_h: number;
}

/** connections.py :: ConnectionParams defaults, verbatim. */
export const CONNECTION_PARAM_DEFAULTS: ConnectionParamsWire = {
  inter_terminal_share: 0.45,
  min_boxes: 8,
  max_boxes: 120,
  min_connection_window_h: 5.0,
  max_connection_window_h: 34.0,
  berth_and_discharge_h: 4.5,
  planned_transfer_h: 1.5,
  watch_threshold_h: 4.0,
};

/** connections.py :: SyntheticConnection. In-process only. */
export interface SyntheticConnection {
  connection_id: string;
  call_id: string;
  vessel_id: string;
  inbound_terminal: Terminal;
  outbound_terminal: Terminal;
  outbound_service: string;
  /** ISO-8601. Anchored on the vessel's ORIGINAL expected arrival, not the current one. */
  outbound_cutoff: string;
  boxes: number;
  params: ConnectionParamsWire;
}

/**
 * watcher.py :: SlackBreakdown — "the arithmetic, kept so the console can show
 * its working".
 *
 * It is the only place the derivation of slack exists, and it is NOT
 * serialised. `to_risk_event` consumes it and throws it away. See CONTRACTS.md
 * REQUEST TO A #1 — this is the single most useful thing the connection detail
 * panel could show and today it cannot.
 */
export interface SlackBreakdown {
  cargo_ready: string;
  outbound_cutoff: string;
  no_itt_slack_h: number;
  transfer_h: number;
  current_plan_slack_h: number;
  eta_slip_min: number;
}

/* ==========================================================================
 * 5. ConnectionRisk wire format
 * src/latch/serde.py :: risk_to_dict() / risk_from_dict()
 *
 * This is B's internal domain model on the wire. It is what `fixtures/risks.json`
 * contains. The runner does NOT emit it — `handle()` returns an `Outcome`
 * carrying a Trace, and the risk itself never leaves the process. See
 * CONTRACTS.md section 6.
 * ======================================================================== */

/** serde.py :: vessel_call_to_dict() */
export interface VesselCallWire {
  vessel_name: string;
  imo: string | null;
  service_code: string;
  terminal: Terminal;
  terminal_resolution: TerminalResolution;
  berth: string | null;
  /** ISO-8601 */
  scheduled: string;
  /** ISO-8601 */
  estimated: string;
}

/** serde.py :: risk_to_dict() */
export interface ConnectionRiskWire {
  /** serde.py :: WIRE_VERSION. A mismatch raises rather than guessing. */
  wire_version: number;
  risk_id: string;
  /** Aligned with the SMDG/UN-CEFACT Unique Connection ID proposal. */
  ucid: string;
  detected_at: string;
  inbound: VesselCallWire;
  outbound: VesselCallWire;
  boxes_at_risk: number;
  slack_total_min: number;
  slack_remaining_min: number;
  source: string;
  data_age_min: number;
  /**
   * Precomputed so the console does not reimplement the arithmetic. B's decoder
   * ignores these and recomputes, on the grounds that trusting a sender's
   * arithmetic would let a bug in A become a bug in B's priority ordering.
   */
  derived: {
    eta_deviation_min: number;
    slack_consumed_pct: number;
    /** boxes_at_risk / max(slack_remaining_hours, MIN_SLACK_HOURS) */
    priority: number;
    crosses_terminals: boolean;
  };
}

/* ==========================================================================
 * 6. Plans and provenance — B's ranked options
 * src/latch/models.py :: Plan, PlanAction, Provenance
 * src/latch/deliberation.py :: DeliberationResult, ExcludedOption
 *
 * IN-PROCESS ONLY. There is no serialiser for Plan anywhere in B. The trace
 * records the CHOSEN plan's rung, confidence and rationale via
 * `trace.decision(...)` and nothing else — no plan_id, no cost_sgd, no
 * emissions, no actions, no per-option ranking.
 *
 * The console brief asks for "B's ranked options with rung, cost (SGD),
 * emissions delta (kgCO2e), rationale and confidence". Today only rung,
 * rationale and confidence survive, and only for the one option chosen. This
 * is the largest single gap and is CONTRACTS.md REQUEST TO B #1.
 * ======================================================================== */

/** models.py :: PlanAction */
export interface PlanAction {
  kind: ActionKind;
  /** Resource key, service code, or party. */
  target: string;
  detail: string;
}

/** models.py :: Provenance — one input to a plan, and where it came from. */
export interface Provenance {
  field_name: string;
  source: SourceKind;
  age_min: number;
  tool_outcome: ToolOutcome;
  /**
   * False marks the field UNVERIFIED. `ToolResult.provenance` forces this false
   * for anything that was not a first-attempt live OK, so a cache fallback is
   * always unverified.
   */
  verified: boolean;
}

/** models.py :: Plan */
export interface Plan {
  plan_id: string;
  risk_id: string;
  rung: Rung;
  actions: PlanAction[];
  rationale: string;
  cost_sgd: number;
  emissions_kg_co2e: number;
  resources_required: string[];
  provenance: Provenance[];
  /** Set by the confidence engine after construction. Never by the model. */
  confidence: number;
  options_alive: number;
}

/** deliberation.py :: ExcludedOption — considered and rejected, in code, pre-prompt. */
export interface ExcludedOption {
  option_id: string;
  rung: Rung;
  reason: string;
}

/** deliberation.py :: DeliberationResult */
export interface DeliberationResult {
  plans: Plan[];
  chosen: Plan | null;
  tool_results: ToolResult[];
  rationale: string;
  /** Rung 1 advisories. Emitted ALONGSIDE the chosen action, never instead of one. */
  advisories: Plan[];
  excluded: ExcludedOption[];
  model: string;
  input_tokens: number;
  output_tokens: number;
  /** Set when the model named an id that was not a candidate. */
  rejected_choice: string | null;
}

/** tools/base.py :: ToolResult. In-process; the trace carries a subset. */
export interface ToolResult {
  tool: string;
  status: ToolStatus;
  value: unknown;
  latency_ms: number;
  source: SourceKind;
  age_min: number;
  attempts: number;
  error_class: string | null;
}

/** tools/stubs.py :: ITTSlot */
export interface ITTSlot {
  slot_id: string;
  from_terminal: Terminal;
  to_terminal: Terminal;
  departs_at: string;
  capacity_teu: number;
  mode: TransferMode;
  /** Per box. deliberation.py multiplies by affected_boxes. */
  cost_sgd: number;
  /** Per box. deliberation.py multiplies by affected_boxes. */
  emissions_kg_co2e: number;
}

/** tools/stubs.py — frozen synthetic inventory constants, per box, per mode. */
export const ITT_COST_PER_BOX_SGD: Record<TransferMode, number> = { road: 48.0, barge: 31.0 };
export const ITT_EMISSIONS_PER_BOX_KG: Record<TransferMode, number> = { road: 12.4, barge: 4.1 };
export const ITT_TRANSIT_MIN: Record<TransferMode, number> = { road: 55, barge: 190 };

/* ==========================================================================
 * 7. Gate Controller
 * src/latch/gates.py :: GateDecision, evaluate()
 *
 * IN-PROCESS ONLY. `GateDecision` is never serialised. Its wire form is the
 * trace `gate` step (section 9), which carries rung, required_role, escalated,
 * escalation_reason, status and latency_s — but NOT the criteria that tripped
 * as structured data, only the human-readable `escalation_reason` string.
 * ======================================================================== */

export interface GateDecision {
  rung: Rung;
  required_role: ApprovalRole;
  escalated: boolean;
  /** Semicolon-joined human-readable reasons. Empty when nothing tripped. */
  escalation_reason: string;
}

/* ==========================================================================
 * 8. Lock Table
 * src/latch/locks.py :: Reservation, ClaimResult
 *
 * IN-PROCESS ONLY. `LockTable` is a single-process in-memory store with no
 * serialiser and no snapshot method. Its wire form is the trace `lock` step
 * (section 9), one per claim. The console cannot render the table's current
 * contents; it can only render what each trace says about its own claims.
 * CONTRACTS.md REQUEST TO B #3.
 * ======================================================================== */

export interface Reservation {
  resource: string;
  risk_id: string;
  priority: number;
  claimed_at: string;
  expires_at: string;
  /** A committed reservation is never preempted — the physical move has begun. */
  committed: boolean;
}

/** locks.py :: ClaimResult.reason — the closed set the LockTable itself emits. */
export type ClaimReason =
  | 'uncontested'
  | 'already_held'
  | 'incumbent_committed'
  | 'preempted_lower_priority'
  | 'outranked';

export interface ClaimResult {
  granted: boolean;
  resource: string;
  risk_id: string;
  our_priority: number;
  winner_priority: number | null;
  preempted_risk_id: string | null;
  reason: ClaimReason;
  /** ClaimResult.status — 'held' when granted, 'lost' otherwise. */
  status: 'held' | 'lost';
}

/* ==========================================================================
 * 9. Execution trace — the B to C wire format
 * src/latch/trace.py :: Trace.as_dict(), TraceStep.as_dict()
 *
 * This is `fixtures/traces.json`. NOTE: `TraceStep.as_dict()` SPREADS the
 * payload flat alongside seq/type/at rather than nesting it, so every step is
 * a flat object and the discriminant is `type`.
 * ======================================================================== */

export interface TraceStepBase {
  seq: number;
  type: string;
  /** ISO-8601, wall clock at record time — NOT scenario time. See CONTRACTS.md section 7. */
  at: string;
}

/**
 * trace.py :: observation(summary, **extra).
 *
 * `**extra` is open. Every key below has been observed in the codebase; a
 * consumer must tolerate keys it does not know.
 */
export interface ObservationStep extends TraceStepBase {
  type: 'observation';
  summary: string;
  priority?: number;
  connection_type?: ConnectionType;
  reason_codes?: ReasonCode[];
  watcher_confidence?: WatcherConfidence;
  triage_route?: TriageRoute;
  /** True on the steps that record an option ruled out before the prompt was built. */
  considered?: boolean;
  rung?: Rung;
  /** Set when the model named a plan id that did not exist. */
  rejected_id?: string;
  /** The assumptions payload is spread flat into one observation step. */
  ucid_synthetic?: boolean;
  pairing_synthetic?: boolean;
  terminals_synthetic?: boolean;
  boxes_synthetic?: boolean;
  transfer_scenario?: string;
  slack_is_scenario_output?: boolean;
  no_itt_slack_means?: string;
  [key: string]: unknown;
}

/** trace.py :: state_change(from_state, to_state, reason) */
export interface StateChangeStep extends TraceStepBase {
  type: 'state_change';
  from_state: RiskState;
  to_state: RiskState;
  reason: string;
}

/**
 * trace.py :: decision(rung, chosen, confidence, rationale).
 *
 * Rung 1 advisories are recorded here with `chosen: false`. There is no cost,
 * no emissions, no plan_id and no action list on this step.
 */
export interface DecisionStep extends TraceStepBase {
  type: 'decision';
  rung: Rung;
  chosen: boolean;
  confidence: number;
  rationale: string;
}

/** trace.py :: tool_call(tool, status, latency_ms, **extra) */
export interface ToolCallStep extends TraceStepBase {
  type: 'tool_call';
  tool: string;
  status: ToolStatus;
  latency_ms: number;
  attempts?: number;
  booking_ref?: string;
  alternatives_found?: number;
  [key: string]: unknown;
}

/** trace.py :: lock(resource, status, our_priority, winner_priority, action) */
export interface LockStep extends TraceStepBase {
  type: 'lock';
  resource: string;
  status: 'held' | 'lost';
  our_priority: number;
  winner_priority: number | null;
  /** `ClaimResult.reason` from the runner; free text in scripted fixtures. */
  action: string;
}

/** trace.py :: error(tool, error_class, retries, recovery) */
export interface ErrorStep extends TraceStepBase {
  type: 'error';
  tool: string;
  error_class: string;
  retries: number;
  /** e.g. "cached inventory @ T-8m" or "no fallback available". */
  recovery: string;
}

/**
 * trace.py :: confidence(breakdown_dict), where the dict is
 * confidence.py :: ConfidenceBreakdown.as_dict() spread flat.
 */
export interface ConfidenceStep extends TraceStepBase {
  type: 'confidence';
  computed: number;
  method: 'provenance';
  factors: {
    /** The WEAKEST source across all inputs. A plan is as good as its worst input. */
    source: SourceKind | 'none';
    source_factor: number;
    /** The OLDEST input's age. */
    data_age_min: number;
    age_factor: number;
    /** The WORST tool outcome across all inputs. */
    tool_outcome: ToolOutcome | 'none';
    tool_factor: number;
    unverified_inputs: number;
    unverified_penalty: number;
  };
  /** Designed to be shown verbatim next to the number. */
  derivation: string;
}

/** trace.py :: gate(rung, role, escalated, status, latency_s, escalation_reason) */
export interface GateStep extends TraceStepBase {
  type: 'gate';
  rung: Rung;
  /** NOTE the key rename: the recorder's parameter is `role`, the key is `required_role`. */
  required_role: ApprovalRole;
  escalated: boolean;
  escalation_reason: string;
  status: GateStatus;
  /** How long the approval took. NOT a deadline. See CONTRACTS.md REQUEST TO B #2. */
  latency_s: number;
}

/**
 * Observed gate statuses. 'auto' and 'required' come from `runner.handle`;
 * 'approved', 'rejected' and 'lapsed' from the approval branch; 'pending' from
 * the scripted fixtures only.
 */
export type GateStatus =
  | 'auto'
  | 'required'
  | 'pending'
  | 'approved'
  | 'rejected'
  | 'lapsed';

/** trace.py :: external_gate(party, options_sent, window_min, outcome) */
export interface ExternalGateStep extends TraceStepBase {
  type: 'external_gate';
  party: string;
  options_sent: number;
  /** config.CUSTOMER_WINDOW_MIN, 180 minutes. The window put to the LINE. */
  window_min: number;
  outcome: ExternalGateOutcome;
}

export type ExternalGateOutcome = 'DECIDED' | 'DECLINED_ALL' | 'LAPSED_NO_RESPONSE';

/** trace.py :: model_call(model, input_tokens, output_tokens, purpose) */
export interface ModelCallStep extends TraceStepBase {
  type: 'model_call';
  model: string;
  /** 'triage' | 'deliberation' | 'deliberation (re-run)' observed. */
  purpose: string;
  input_tokens: number;
  output_tokens: number;
  /** Priced at config.PRICING. This is the per-decision token cost. */
  usd: number;
}

export type TraceStep =
  | ObservationStep
  | StateChangeStep
  | DecisionStep
  | ToolCallStep
  | LockStep
  | ErrorStep
  | ConfidenceStep
  | GateStep
  | ExternalGateStep
  | ModelCallStep;

/** trace.py :: Trace.for_risk() — the `trigger` block. */
export interface TraceTrigger {
  source: string;
  eta_deviation_min: number;
  slack_consumed_pct: number;
  inbound_terminal: Terminal;
  outbound_terminal: Terminal;
  terminal_resolution: TerminalResolution;
}

/** trace.py :: CostMeter.as_dict() */
export interface CostWire {
  model_calls: number;
  input_tokens: number;
  output_tokens: number;
  usd: number;
  by_model: Record<string, number>;
}

/** trace.py :: Trace.as_dict() */
export interface TraceWire {
  trace_id: string;
  risk_id: string;
  ucid: string;
  trigger: TraceTrigger;
  steps: TraceStep[];
  outcome: {
    resolution: Resolution | null;
    service_success: boolean | null;
    boxes: number;
    /** Hours between detection and options reaching the line. Null when none sent. */
    decision_lead_time_h: number | null;
    options_alive_at_send: number;
  };
  cost: CostWire;
}

/* ==========================================================================
 * 10. Console view model — B's own C-facing seam
 * src/latch/console.py :: case_view(trace)
 *
 * This is `fixtures/console_views.json`. B built it so that "B decides what a
 * step means, C decides how it looks". The console's adapter consumes this
 * where it can and falls back to the raw trace where it cannot — see
 * CONTRACTS.md section 11 for what case_view drops.
 * ======================================================================== */

/** console.py :: WaterfallStep — one factor's contribution as a step down from 1.0. */
export interface WaterfallStep {
  label: string;
  detail: string;
  kind: 'multiply' | 'subtract';
  factor: number;
  /** The confidence value after this factor is applied. */
  running: number;
}

/** console.py :: ConfidencePanel (via dataclasses.asdict, so properties are NOT included). */
export interface ConfidencePanelWire {
  value: number;
  band: 'auto' | 'escalate';
  threshold: number;
  derivation: string;
  waterfall: WaterfallStep[];
}

/** console.py :: OptionRow */
export interface OptionRowWire {
  option_id: string;
  rung: Rung | '';
  detail: string;
  status: 'chosen' | 'offered' | 'ruled_out' | 'advisory';
}

/** console.py :: PendingApproval */
export interface PendingApprovalWire {
  rung: Rung | '';
  role: ApprovalRole | '';
  escalated: boolean;
  reason: string;
  status: GateStatus | '';
}

/** console.py :: case_view() */
export interface CaseViewWire {
  trace_id: string;
  risk_id: string;
  ucid: string;
  trigger: TraceTrigger;
  resolution: Resolution | null;
  service_success: boolean | null;
  boxes: number;
  decision_lead_time_h: number | null;
  options_alive_at_send: number;
  confidence: ConfidencePanelWire | null;
  confidence_headline: string | null;
  ladder: OptionRowWire[];
  approvals: PendingApprovalWire[];
  customer_gate: {
    options_sent: number;
    window_min: number;
    outcome: ExternalGateOutcome;
  } | null;
  cost: CostWire;
  step_count: number;
}

/* ==========================================================================
 * 11. Run summary
 * scripts/make_fixtures.py + trace.py :: TraceStore.metrics()
 * This is `fixtures/summary.json`.
 * ======================================================================== */

export interface SummaryWire {
  scenarios: number;
  closed: number;
  /** Denominator. Excludes dismissed and superseded — see the two counts below. */
  at_risk: number;
  served: number;
  service_rate: number | null;
  excluded_dismissed: number;
  excluded_superseded: number;
  total_usd: number;
  usd_per_risk: number;
  resolutions: Record<string, Resolution>;
  final_states: Record<string, RiskState>;
}

/* ==========================================================================
 * 12. Supersession registry
 * src/latch/cases.py :: AdmissionDecision
 *
 * IN-PROCESS ONLY, and it lives OUTSIDE `runner.handle()`. A trace produced by
 * the runner therefore never contains a `state_change` into `superseded`; the
 * registry closes the previous case from the outside. The scripted fixtures in
 * `make_fixtures.py` write that state change by hand.
 * See CONTRACTS.md REQUEST TO B #4.
 * ======================================================================== */

export interface AdmissionDecision {
  admission: Admission;
  connection_id: string;
  reason: string;
  superseded_trace_id: string | null;
}

/* ==========================================================================
 * 13. Runner outcome
 * src/latch/runner.py :: Outcome — what `handle()` actually returns.
 * IN-PROCESS ONLY; no serialiser.
 * ======================================================================== */

export interface RunnerOutcome {
  trace: TraceWire;
  state: RiskState;
  resolution: Resolution;
  chosen: Plan | null;
  gate: GateDecision | null;
}
