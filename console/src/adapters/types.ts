/**
 * The console's view model.
 *
 * Nothing downstream of `toViewModel.ts` imports from `contracts/latch.ts`.
 * These types are what components consume, and swapping fixtures for a live
 * feed is a change to the adapter alone.
 *
 * Two conventions carry through everything here:
 *
 *   `Sourced<T>` — a value that knows whether it is verified, and if not, why.
 *     Unverified numbers are marked at the number, never in a footnote.
 *
 *   `Missing`   — a field B does not carry. Rendered as an explicit gap, never
 *     as a blank, a zero, or a plausible default. See CONTRACTS.md section 6.
 */

import type {
  ApprovalRole,
  CaseViewWire,
  ConnectionRiskWire,
  ExternalGateOutcome,
  ReasonCode,
  Resolution,
  RiskEventWire,
  RiskSeverity,
  RiskState,
  Rung,
  Terminal,
  TerminalResolution,
  ToolStatus,
  TraceWire,
  WatcherConfidence,
} from '../contracts/latch';

/* -------------------------------------------------------------------------
 * Value wrappers
 * ---------------------------------------------------------------------- */

/** Why a value is not verified. Drawn from the run, never asserted. */
export interface Unverified {
  /** e.g. 'query_itt_slot' or 'watcher_assessment' — the provenance field name. */
  field: string;
  /** 'cache fallback', 'retried', 'failed', 'watcher confidence MEDIUM'. */
  reason: string;
  /** How stale, in minutes. 0 when staleness is not the issue. */
  ageMin: number;
}

export interface Sourced<T> {
  value: T;
  verified: boolean;
  /** Present only when `verified` is false. */
  unverified?: Unverified;
}

/** A field the wire format does not carry. */
export interface Missing {
  missing: true;
  /** Shown to the operator, e.g. 'not carried in trace'. */
  label: string;
  /** Where to chase it, e.g. 'CONTRACTS.md REQUEST TO B #1'. */
  request: string;
}

export type MaybeMissing<T> = T | Missing;

export function isMissing<T>(v: MaybeMissing<T>): v is Missing {
  return typeof v === 'object' && v !== null && (v as Missing).missing === true;
}

/* -------------------------------------------------------------------------
 * Ladder vocabulary
 * ---------------------------------------------------------------------- */

export interface RungVM {
  /** 1, 3 or 4. Never renumbered — the gap at 2 is deliberate. */
  number: number;
  /** B's enum value, for the JSON toggle and for debugging. */
  enumValue: Rung;
  /** PREVENT / MOVE / OFFER. */
  name: string;
  /** One line: what this rung actually does. */
  does: string;
  /** Who owns the decision. */
  authority: string;
  /** True for rung 1: advisory, never executed by the agent. */
  advisoryOnly: boolean;
}

/** The cut rung, rendered as a visible gap rather than silently skipped. */
export interface CutRungVM {
  number: 2;
  name: string;
  whyCut: string;
}

/* -------------------------------------------------------------------------
 * Confidence — the centrepiece
 * ---------------------------------------------------------------------- */

export interface WaterfallStepVM {
  label: string;
  detail: string;
  kind: 'multiply' | 'subtract';
  factor: number;
  /** Running confidence after this factor. */
  running: number;
  /** How much this factor removed. Positive means it hurt. */
  cost: number;
}

/** One tool that did not return cleanly, and what was used instead. */
export interface DegradationVM {
  tool: string;
  /** 'timed out', 'errored'. */
  what: string;
  attempts: number;
  retries: number;
  /** B's own recovery string, e.g. 'cached inventory @ T-8m'. */
  fallback: string;
  /** True when the fallback was stale data rather than nothing. */
  servedStale: boolean;
  ageMin: number;
  latencyMs: number;
}

export interface ConfidenceVM {
  value: number;
  band: 'auto' | 'escalate';
  threshold: number;
  belowThreshold: boolean;
  /** B's derivation string, shown verbatim beside the number. */
  derivation: string;
  waterfall: WaterfallStepVM[];
  /** The weakest input's source, which is what sets `source_factor`. */
  weakestSource: string;
  /** The oldest input's age, which is what sets `age_factor`. */
  oldestInputMin: number;
  worstToolOutcome: string;
  /** Tools that failed or retried on this run. */
  degradations: DegradationVM[];
  /**
   * The specific inputs the confidence engine counted as unverified,
   * reconstructed from the trace by the same rule `deliberation.py` uses.
   */
  unverifiedFields: Unverified[];
  /**
   * False when the reconstructed field list does not match B's own
   * `unverified_inputs` count. The UI shows the count and says the field
   * names could not be established, rather than showing a guess.
   */
  unverifiedFieldsReconciled: boolean;
  unverifiedCount: number;
  inputCount: number | null;
}

/* -------------------------------------------------------------------------
 * The gate
 * ---------------------------------------------------------------------- */

export interface EscalationVM {
  /** The role the gate requires when nothing trips: LADDERS[rung][0]. */
  wouldHaveBeen: ApprovalRole;
  wouldHaveBeenLabel: string;
  became: ApprovalRole;
  becameLabel: string;
  /** B's escalation_reason, split into one line per tripped criterion. */
  reasons: string[];
  /** True when a confidence criterion is among them. */
  triggeredByConfidence: boolean;
  /** How far up the ladder, in steps. */
  steps: number;
  ladder: ApprovalRole[];
}

export interface GateVM {
  rung: RungVM;
  requiredRole: ApprovalRole;
  requiredRoleLabel: string;
  /** True when the agent may act without a signature. */
  autoApproved: boolean;
  /** True when a human must sign before anything happens. */
  blocks: boolean;
  /** Rung 4: the decision leaves the building and cannot be escalated past. */
  needsCustomer: boolean;
  escalated: boolean;
  escalation: EscalationVM | null;
  /** Where the gate ended up: approved, rejected, lapsed, or still open. */
  status: 'auto' | 'awaiting' | 'approved' | 'rejected' | 'lapsed';
  /** Seconds the approval took, when B recorded it. */
  latencyS: number | null;
}

/** What the approval panel needs to render a decision the operator can take. */
export interface ApprovalVM {
  /** False for rung 1 — advisory, so there is nothing to approve. */
  actionable: boolean;
  role: ApprovalRole;
  roleLabel: string;
  /** Rung 1 only: acknowledge and hand off rather than approve. */
  handoff: boolean;
  /** Stated up front, before the operator decides. */
  ifNothingHappens: string;
  /**
   * Console-side countdown. B carries no deadline — CONTRACTS.md section 7 —
   * so this is our timer and the UI says so.
   */
  countdown: {
    windowMin: number;
    source: 'console-timer';
    note: string;
  } | null;
}

/* -------------------------------------------------------------------------
 * Options
 * ---------------------------------------------------------------------- */

export interface OptionVM {
  id: string;
  rung: RungVM;
  status: 'chosen' | 'considered' | 'advisory' | 'ruled_out';
  /** What the option physically is, e.g. "barge, departs 05:37, 190m transit". */
  detail: string;
  /** The agent's own words. Only the chosen option and advisories carry one. */
  rationale: string;
  /** Why code excluded it, before the model ever saw it. */
  exclusionReason: string | null;
  confidence: number | null;
  /**
   * Singapore dollars. NOT the same unit as `CostVM.usd`, which is inference
   * cost — B keeps them apart deliberately and so does the console.
   */
  costSgd: MaybeMissing<number>;
  emissionsKgCo2e: MaybeMissing<number>;
  /**
   * False for Rung 1 advisories and Rung 4 offers: neither moves a box, so
   * zero is the correct value rather than an absent one. B exposes the same
   * distinction as `OptionRow.has_cost`.
   */
  movesCargo: boolean;
}

/* -------------------------------------------------------------------------
 * Contested resources
 * ---------------------------------------------------------------------- */

export interface LockVM {
  resource: string;
  held: boolean;
  ourPriority: number;
  winnerPriority: number | null;
  /** B's `ClaimResult.reason`, in operator English. */
  outcome: string;
  /** What the connection did about it. */
  consequence: string;
}

/* -------------------------------------------------------------------------
 * Timeline
 * ---------------------------------------------------------------------- */

export type TimelineKind =
  | 'observation'
  | 'state_change'
  | 'decision'
  | 'tool_call'
  | 'lock'
  | 'error'
  | 'confidence'
  | 'gate'
  | 'external_gate'
  | 'model_call';

/** Visual weight. Errors and escalations must read differently at a glance. */
export type TimelineTone = 'normal' | 'muted' | 'decision' | 'error' | 'escalation' | 'success';

export interface TimelineEventVM {
  seq: number;
  kind: TimelineKind;
  tone: TimelineTone;
  /** Short label for the gutter, e.g. 'TOOL', 'GATE', 'ERROR'. */
  label: string;
  /** One line of operator English. */
  title: string;
  /** Optional supporting lines. */
  detail: string[];
  latencyMs: number | null;
  toolStatus: ToolStatus | null;
  /** Per-decision token cost, when this step is a model call. */
  tokens: { model: string; purpose: string; input: number; output: number; usd: number } | null;
  /** The raw step, for the JSON toggle. */
  raw: Record<string, unknown>;
}

/* -------------------------------------------------------------------------
 * Reasons, outcome, cost, provenance
 * ---------------------------------------------------------------------- */

export interface ReasonVM {
  code: ReasonCode;
  /** Operator English, not the enum string. */
  title: string;
  detail: string;
  /**
   * False for the four codes the live Watcher cannot emit
   * (CONTRACTS.md section 5). The UI marks them.
   */
  emittedByWatcher: boolean;
}

export interface OutcomeVM {
  resolution: Resolution;
  label: string;
  /** What actually happened to the boxes, in plain English. */
  what: string;
  /** B's own `service_success`, read rather than re-derived. */
  serviceSuccess: boolean;
  /**
   * Whether B's value matches the transcribed `SERVICE_SUCCESS_RESOLUTIONS`
   * list. Asserted by `npm run smoke`, so a change to B's classification
   * surfaces as a failed reconciliation instead of a silent disagreement.
   */
  serviceSuccessReconciled: boolean;
  /** Whether the shipping line was ever asked. B's value, not inferred. */
  reachedTheLine: boolean;
  /** True when the system broke rather than decided. */
  agentFault: boolean;
  /** The one-word verdict shown on the outcome panel. */
  badge: string;
  /** Why this counts, or does not, as serving the customer. */
  why: string;
  /** True for dismissed and superseded: excluded from the north-star denominator. */
  excludedFromMetric: boolean;
  customerGate: {
    optionsSent: number;
    windowMin: number;
    outcome: ExternalGateOutcome;
  } | null;
  decisionLeadTimeH: number | null;
  /** What the executed action actually committed, in SGD. Null when nothing fired. */
  actionCostSgd: number | null;
  actionEmissionsKgCo2e: number | null;
}

export interface CostVM {
  modelCalls: number;
  inputTokens: number;
  outputTokens: number;
  usd: number;
  byModel: Record<string, number>;
  /** Per-decision breakdown, one entry per model_call step. */
  perDecision: { seq: number; model: string; purpose: string; usd: number; input: number; output: number }[];
}

export interface TriageVM {
  /** 'dismissed_safe', 'fast_tracked', 'model_kept', … */
  route: string;
  routeLabel: string;
  kept: boolean;
  /** True when triage decided without spending a model call. */
  decidedFree: boolean;
  reason: string;
}

/** What this connection's data actually rests on. Rendered, not hidden. */
export interface ProvenanceVM {
  /** Always the full sentence. Never shortened. */
  dataBasis: string;
  /** How the terminal assignment was arrived at. `simulated` for live A output. */
  terminalResolution: TerminalResolution;
  terminalResolutionLabel: string;
  /** True when any part of the connection graph is synthetic. */
  anySynthetic: boolean;
  syntheticFields: string[];
  transferScenario: string;
  /** True when no model was consulted on this run. */
  modelScripted: boolean;
  modelDisclosure: string;
  /** True for the SUPERSEDED and STALE fixtures. */
  authored: boolean;
  authoredBecause: string | null;
}

/* -------------------------------------------------------------------------
 * The connection
 * ---------------------------------------------------------------------- */

export interface VesselLegVM {
  name: string;
  terminal: Terminal;
  terminalLabel: string;
  /** ISO-8601, from ConnectionRiskWire. */
  scheduled: string;
  estimated: string;
  /** Minutes late. Negative means early. */
  deviationMin: number;
}

export interface SlackVM {
  /** Margin under the plan as it stands. Negative means already short. */
  currentPlanHours: number;
  /** Margin if the inter-terminal transfer requirement were removed. */
  noIttHours: number;
  /** The gap between them: what the transfer is costing. */
  ittCostHours: number;
  /** How short the current plan is. Zero when it fits. */
  deficitHours: number;
  /** Fraction of the connection window already burned. */
  consumedPct: number;
}

/**
 * `lifecycle` drives Step 4 behaviour: a resolved connection shows its outcome
 * rather than disappearing, and abandoned ones read differently from both.
 */
export type Lifecycle = 'live' | 'resolved' | 'abandoned';

export interface ConnectionVM {
  /** `risk_id` / `connection_id`. Stable across updates — the update key. */
  id: string;
  ucid: string;
  severity: RiskSeverity;
  severityLabel: string;
  state: RiskState;
  stateLabel: string;
  /** One line explaining an off-ramp state (superseded, stale, lapsed, lost_lock). */
  stateNote: string | null;
  lifecycle: Lifecycle;
  boxes: number;
  /** boxes / max(slack hours, 0.25). What the Lock Table arbitrates on. */
  priority: number;
  detectedAt: string;

  slack: SlackVM;
  /**
   * `RiskEvent.itt_is_the_problem` — removing the transfer would rescue this.
   * NOT `avoidable_by_terminal_prevention`, which is only "a transfer is on the
   * critical path". See CONTRACTS.md section 5.
   */
  rescuableByRemovingItt: boolean;
  crossesTerminals: boolean;

  inbound: VesselLegVM;
  outbound: VesselLegVM;

  watcherConfidence: WatcherConfidence;
  reasons: ReasonVM[];
  triage: TriageVM;

  confidence: ConfidenceVM | null;
  gate: GateVM | null;
  approval: ApprovalVM | null;
  options: OptionVM[];
  locks: LockVM[];
  timeline: TimelineEventVM[];
  outcome: OutcomeVM | null;
  cost: CostVM;
  provenance: ProvenanceVM;

  /** For the raw-JSON toggle. Never the primary view. */
  raw: {
    event: RiskEventWire;
    risk: ConnectionRiskWire;
    trace: TraceWire;
    caseView: CaseViewWire;
  };
}

/* -------------------------------------------------------------------------
 * Fixture envelope (C-owned) and the console's top-level state
 * ---------------------------------------------------------------------- */

/** What `capture_fixtures.py` writes. C's packaging of A/B output. */
export interface FixtureBundle {
  fixture_id: string;
  title: string;
  what_it_shows: string;
  provenance: {
    produced_by: string;
    authored: boolean;
    authored_because?: string;
    model_responses: string;
    model_disclosure?: string;
    data_basis: string;
    timestamps?: string;
    tool_inventory?: string;
  };
  event: RiskEventWire;
  derived: {
    is_actionable: boolean;
    slack_deficit_hours: number;
    itt_cost_hours: number;
    itt_is_the_problem: boolean;
    priority: number;
    watcher_confidence_factor: number;
  };
  assumptions: {
    connection_type: string;
    ucid_synthetic: boolean;
    pairing_synthetic: boolean;
    terminals_synthetic: boolean;
    boxes_synthetic: boolean;
    transfer_scenario: string;
    slack_is_scenario_output: boolean;
    no_itt_slack_means: string;
  };
  risk: ConnectionRiskWire;
  trace: TraceWire;
  case_view: CaseViewWire;
  result: {
    state: RiskState;
    resolution: Resolution | null;
    service_success: boolean | null;
  };
  gate: {
    rung: Rung;
    required_role: ApprovalRole;
    escalated: boolean;
    escalation_reason: string;
    auto_approved: boolean;
    blocks: boolean;
    needs_customer: boolean;
    ladder: ApprovalRole[];
    would_have_been: ApprovalRole;
    confidence_threshold: number;
  } | null;
  model_calls: { purpose: string; model: string }[];
  /** Present on the supersession fixture only. */
  superseding_event?: RiskEventWire;
  admission?: {
    admission: string;
    connection_id: string;
    reason: string;
    superseded_trace_id: string | null;
  }[];
}

export interface FixtureIndex {
  generated_by: string;
  data_basis: string;
  model_responses: string;
  policy: {
    confidence_escalation_threshold: number;
    deliberation_model: string;
    triage_model: string;
  };
  fixtures: {
    fixture_id: string;
    file: string;
    title: string;
    connection_id: string;
    severity: RiskSeverity;
    boxes: number;
    state: RiskState;
    resolution: Resolution | null;
    service_success: boolean | null;
    authored: boolean;
    confidence: number | null;
    required_role: ApprovalRole | null;
    escalated: boolean;
    usd: number;
  }[];
}
