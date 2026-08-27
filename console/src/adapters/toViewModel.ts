/**
 * The only module in the console that touches A's and B's shapes.
 *
 * Everything downstream consumes `ConnectionVM`, so swapping fixtures for a
 * live feed is a change to this file alone.
 *
 * Three rules hold throughout:
 *
 *   1. Nothing is invented. A field B does not carry becomes a `Missing`
 *      marker naming the request that would fix it, never a zero or a blank.
 *   2. Nothing is recomputed that B already computed. Confidence, priority,
 *      slack consumption, escalation and service-success all come from A or B.
 *      Where this file does derive something, it says so and — for the
 *      unverified-field list — checks its answer against B's own count.
 *   3. Enum strings never reach the screen. Every one is mapped to operator
 *      English here.
 *
 * See CONTRACTS.md for why each gap exists.
 */

import {
  GATE_LADDERS,
  POLICY,
  SERVICE_SUCCESS_RESOLUTIONS,
  type ApprovalRole,
  type ConfidenceStep,
  type DecisionStep,
  type ErrorStep,
  type ExternalGateStep,
  type GateStep,
  type LockStep,
  type ModelCallStep,
  type ObservationStep,
  type OptionsStep,
  type ReasonCode,
  type Resolution,
  type RiskSeverity,
  type RiskState,
  type Rung,
  type StateChangeStep,
  type Terminal,
  type TerminalResolution,
  type TimingResolution,
  type ToolCallStep,
  type TraceStep,
  type TraceWire,
} from '../contracts/latch';

import { isMissing } from './types';
import type {
  ApprovalVM,
  ConfidenceVM,
  ConnectionVM,
  CostVM,
  CutRungVM,
  DegradationVM,
  EscalationVM,
  FixtureBundle,
  GateVM,
  Lifecycle,
  LockVM,
  Missing,
  OptionVM,
  OutcomeBadge,
  OutcomeTone,
  OutcomeVM,
  ProvenanceVM,
  ReasonVM,
  RungVM,
  SlackVM,
  TimelineEventVM,
  TimelineKind,
  TimelineTone,
  TriageVM,
  Unverified,
  VesselLegVM,
  WaterfallStepVM,
} from './types';

/* =========================================================================
 * Vocabulary — every enum the operator would otherwise have to read raw
 * ====================================================================== */

const RUNGS: Record<Rung, RungVM> = {
  rung_1_inform: {
    number: 1,
    enumValue: 'rung_1_inform',
    name: 'PREVENT',
    does: 'Reassign the berth so both vessels work the same terminal, removing the transfer entirely',
    authority: 'Berth Planner decides',
    advisoryOnly: true,
  },
  rung_3_move: {
    number: 3,
    enumValue: 'rung_3_move',
    name: 'MOVE',
    does: 'Book the inter-terminal transfer slot',
    authority: 'Vessel Operations decides',
    advisoryOnly: false,
  },
  rung_4_offer: {
    number: 4,
    enumValue: 'rung_4_offer',
    name: 'OFFER',
    does: 'Put ranked options to the shipping line while the choice is still real',
    authority: 'The shipping line decides — PSA cannot decide for them',
    advisoryOnly: false,
  },
};

/** Rendered as a visible gap in the ladder. Never renumbered away. */
export const CUT_RUNG: CutRungVM = {
  number: 2,
  name: 'ABSORB',
  whyCut:
    'Resequencing discharge to buy hours was cut deliberately: it needs a stowage and crane model we would get wrong. The gap in the numbering is left visible rather than renumbered away.',
};

export const RUNG_ORDER: (RungVM | CutRungVM)[] = [
  RUNGS.rung_1_inform,
  CUT_RUNG,
  RUNGS.rung_3_move,
  RUNGS.rung_4_offer,
];

const ROLE_LABEL: Record<ApprovalRole, string> = {
  auto: 'No signature required',
  berth_planner: 'Berth Planner',
  vessel_ops: 'Vessel Operations',
  duty_manager: 'Duty Manager',
  customer: 'Shipping line',
};

const TERMINAL_LABEL: Record<Terminal, string> = {
  tuas: 'Tuas',
  pasir_panjang: 'Pasir Panjang',
  brani: 'Brani',
  keppel: 'Keppel',
  unknown: 'Terminal unknown',
};

const TERMINAL_RESOLUTION_LABEL: Record<TerminalResolution, string> = {
  berth: 'Exact berth from the feed',
  terminal: 'Terminal named in the feed',
  inferred: 'Inferred from the service rotation',
  simulated: 'Simulated — no claim to reality',
};

export const TIMING_RESOLUTION_LABEL: Record<TimingResolution, string> = {
  derived_causal_arrival: 'Derived causal AIS estimate',
  legacy_slack_fallback: 'Reconstructed legacy timing',
};

const SEVERITY_LABEL: Record<RiskSeverity, string> = {
  SAFE: 'SAFE',
  WATCH: 'WATCH',
  AT_RISK: 'AT RISK',
};

const STATE_LABEL: Record<RiskState, string> = {
  detected: 'Detected',
  triaged: 'Triaged',
  deliberating: 'Deliberating',
  awaiting_approval: 'Awaiting approval',
  escalated: 'Escalated',
  awaiting_customer: 'Awaiting the line',
  executing: 'Executing',
  dismissed: 'Dismissed',
  superseded: 'Superseded',
  stale: 'Stale',
  lost_lock: 'Lost the slot',
  lapsed: 'Lapsed',
  resolved: 'Resolved',
  failed: 'Failed',
};

/** One line for the off-ramp states, so a badge never stands unexplained. */
const STATE_NOTE: Partial<Record<RiskState, string>> = {
  superseded:
    'The arrival estimate improved while the agent was still working. Abandoned cleanly, and excluded from the metric — this was never a connection genuinely at risk of failing.',
  stale:
    'Upstream data went missing and there was nothing cached to fall back on. Confidence was not computed, because a plan resting on nothing we can name is not a plan. Gates tighten.',
  lapsed:
    'The approval never came, so nothing was booked and the boxes rolled. Declining to act is still a decision, and it is traced as one.',
  lost_lock:
    'A more urgent connection took the contested slot. This one re-deliberates with that option removed.',
  dismissed: 'Triage decided there was nothing to act on, and spent nothing deciding it.',
};

const REASONS: Record<ReasonCode, { title: string; detail: string; emitted: boolean }> = {
  INBOUND_ETA_SLIP: {
    title: 'Inbound vessel running late',
    detail: 'The arrival estimate has slipped against the time the connection was planned around.',
    emitted: true,
  },
  INTER_TERMINAL_TRANSFER_TIME: {
    title: 'Cargo has to cross terminals',
    detail:
      'The inbound and outbound legs are at different terminals, so an inter-terminal transfer sits on the critical path.',
    emitted: true,
  },
  OUTBOUND_CUTOFF_ADVANCED: {
    title: 'Outbound loading cut-off moved earlier',
    detail: 'The window closed from the other end rather than the vessel being late.',
    emitted: false,
  },
  BERTH_CONGESTION: {
    title: 'Berth congestion at arrival',
    detail: 'The vessel is expected to wait for a berth before discharge can start.',
    emitted: false,
  },
  YARD_CONGESTION: {
    title: 'Yard congestion',
    detail: 'Yard density is expected to slow the move between discharge and the transfer.',
    emitted: false,
  },
  DISCHARGE_SEQUENCE: {
    title: 'Boxes are buried in the discharge sequence',
    detail: 'The containers come off late in the sequence, eating the margin before the transfer starts.',
    emitted: false,
  },
};

const TRIAGE_LABEL: Record<string, string> = {
  dismissed_safe: 'Dismissed — Watcher reports SAFE',
  dismissed_too_small: 'Dismissed — below the volume floor',
  fast_tracked: 'Fast-tracked — too serious to ask about',
  model_kept: 'Kept by the triage model',
  model_dismissed: 'Dismissed by the triage model',
};

const RESOLUTION_COPY: Record<Resolution, { label: string; what: string; why: string }> = {
  connection_held: {
    label: 'Connection held',
    what: 'The boxes made the outbound vessel.',
    why: 'Resolved inside PSA without spending the line’s attention.',
  },
  customer_decided: {
    label: 'The line decided',
    what: 'The line chose one of the options it was given.',
    why: 'A live decision held before the window closed. This is what the system is for.',
  },
  customer_declined_all: {
    label: 'The line declined every option',
    what: 'The boxes rolled to the next service.',
    why: 'The line was asked, had real options, and said no. That is a served customer, not a service failure.',
  },
  window_lapsed_no_response: {
    label: 'Window lapsed — no response',
    what: 'The boxes rolled to the next service.',
    why: 'The line was asked and nobody answered before the window closed. The box rolls either way; the difference is that this customer was never actually served. This is the north-star failure.',
  },
  internally_declined: {
    label: 'Declined internally',
    what: 'The transfer was not booked. The boxes rolled to the next service.',
    why: 'The approver declined the escalated action. The shipping line was never contacted — this was a PSA decision, not the line’s.',
  },
  approval_lapsed: {
    label: 'Approval lapsed',
    what: 'Nothing was booked. The boxes rolled to the next service.',
    why: 'The internal approval window closed with no answer. The shipping line was never contacted, so this is not a lapsed customer window.',
  },
  dismissed_no_action: {
    label: 'Dismissed at triage',
    what: 'Nothing was done, and nothing needed to be.',
    why: 'Excluded from the metric — counting it would punish the system for correctly deciding there was nothing to do.',
  },
  superseded: {
    label: 'Superseded',
    what: 'The risk evaporated before anything was acted on.',
    why: 'Excluded from the metric for the same reason as a dismissal.',
  },
  failed: {
    label: 'Failed',
    what: 'The agent broke.',
    why: 'This is us failing, not the connection.',
  },
};

/* =========================================================================
 * Step helpers
 * ====================================================================== */

const isType = <T extends TraceStep>(kind: T['type']) => (s: TraceStep): s is T => s.type === kind;

const observations = (t: TraceWire) => t.steps.filter(isType<ObservationStep>('observation'));
const decisions = (t: TraceWire) => t.steps.filter(isType<DecisionStep>('decision'));
const toolCalls = (t: TraceWire) => t.steps.filter(isType<ToolCallStep>('tool_call'));
const errors = (t: TraceWire) => t.steps.filter(isType<ErrorStep>('error'));
const gates = (t: TraceWire) => t.steps.filter(isType<GateStep>('gate'));
const modelCalls = (t: TraceWire) => t.steps.filter(isType<ModelCallStep>('model_call'));
const optionsStep = (t: TraceWire): OptionsStep | null =>
  t.steps.filter(isType<OptionsStep>('options')).at(-1) ?? null;
const confidenceStep = (t: TraceWire): ConfidenceStep | null =>
  t.steps.filter(isType<ConfidenceStep>('confidence')).at(-1) ?? null;
const externalGate = (t: TraceWire): ExternalGateStep | null =>
  t.steps.filter(isType<ExternalGateStep>('external_gate')).at(-1) ?? null;

const missing = (label: string, request: string): Missing => ({ missing: true, label, request });

/**
 * Fallback for traces captured before B landed the `options` step (REQUEST #1,
 * commit 6be7bb4). Kept rather than deleted so an older trace renders an honest
 * gap instead of a zero.
 */
const NOT_IN_TRACE = () =>
  missing('not carried in this trace', 'captured before B landed the options step');

const NOT_COSTED = () =>
  missing('excluded before costing', 'ruled out in code before a plan was built');

/* =========================================================================
 * Confidence
 * ====================================================================== */

/**
 * Rebuild the list of inputs the confidence engine counted as unverified.
 *
 * `Provenance` is never serialised (CONTRACTS.md section 6), so the trace gives
 * a count and not names. The rule is transcribed from `deliberation.py`:
 *
 *     provenance = [event.provenance()] + [r.provenance(r.tool,
 *                      verified=r.ok and r.attempts == 1) for r in tool_results]
 *
 * and `ToolResult.provenance` forces `verified` false for anything that is not
 * a first-attempt live OK. `tool_results` is only what `_gather` ran, so the
 * tool calls that count are the ones recorded before the confidence step.
 *
 * The count is then checked against B's own `unverified_inputs`. If they
 * disagree the caller is told, and the UI shows the count without naming
 * fields rather than showing a guess.
 */
function reconstructUnverified(
  trace: TraceWire,
  conf: ConfidenceStep,
  watcherConfidence: string,
): { fields: Unverified[]; reconciled: boolean; inputCount: number } {
  const gatherTools = toolCalls(trace).filter((s) => s.seq < conf.seq);
  const fields: Unverified[] = [];

  if (watcherConfidence !== 'HIGH') {
    fields.push({
      field: 'watcher_assessment',
      reason: `the Watcher rates its own assessment ${watcherConfidence}, not HIGH`,
      ageMin: 0,
    });
  }

  for (const call of gatherTools) {
    const attempts = call.attempts ?? 1;
    const clean = call.status === 'ok' && attempts === 1;
    if (clean) continue;
    fields.push({
      field: call.tool,
      reason:
        call.status === 'cached_fallback'
          ? `served from cache after ${attempts} live attempts failed`
          : call.status === 'ok'
            ? `succeeded only on attempt ${attempts}`
            : `the call ${call.status === 'timeout' ? 'timed out' : 'errored'} and no live value was obtained`,
      ageMin: call.status === 'cached_fallback' ? conf.factors.data_age_min : 0,
    });
  }

  const inputCount = 1 + gatherTools.length;
  return {
    fields,
    reconciled: fields.length === conf.factors.unverified_inputs,
    inputCount,
  };
}

function buildDegradations(trace: TraceWire): DegradationVM[] {
  const calls = toolCalls(trace);
  return errors(trace).map((err) => {
    const call =
      calls.filter((c) => c.tool === err.tool && c.seq < err.seq).at(-1) ??
      calls.find((c) => c.tool === err.tool);
    const servedStale = /cache/i.test(err.recovery);
    const ageMatch = err.recovery.match(/T-(\d+(?:\.\d+)?)m/);
    return {
      tool: err.tool,
      what: err.error_class === 'timeout' ? 'timed out' : `failed (${err.error_class})`,
      attempts: call?.attempts ?? err.retries + 1,
      retries: err.retries,
      fallback: err.recovery,
      servedStale,
      ageMin: ageMatch ? Number(ageMatch[1]) : 0,
      latencyMs: call?.latency_ms ?? 0,
    };
  });
}

function buildConfidence(trace: TraceWire, watcherConfidence: string): ConfidenceVM | null {
  const conf = confidenceStep(trace);
  if (!conf) return null;

  const f = conf.factors;
  const waterfall: WaterfallStepVM[] = [];
  let running = 1;

  const multiply = (label: string, detail: string, factor: number) => {
    const before = running;
    running = Number((running * factor).toFixed(4));
    waterfall.push({
      label,
      detail,
      kind: 'multiply',
      factor,
      running,
      cost: Number((before - running).toFixed(4)),
    });
  };

  multiply('Source', `weakest input came from ${f.source}`, f.source_factor);
  multiply('Data age', `oldest input was ${f.data_age_min.toFixed(0)} min old`, f.age_factor);
  multiply('Tool outcome', `worst tool outcome was ${f.tool_outcome}`, f.tool_factor);

  if (f.unverified_penalty) {
    const before = running;
    running = Number((running - f.unverified_penalty).toFixed(4));
    waterfall.push({
      label: 'Unverified inputs',
      detail: `${f.unverified_inputs} input${f.unverified_inputs === 1 ? '' : 's'} could not be verified`,
      kind: 'subtract',
      factor: f.unverified_penalty,
      running,
      cost: Number((before - running).toFixed(4)),
    });
  }

  const { fields, reconciled, inputCount } = reconstructUnverified(trace, conf, watcherConfidence);

  return {
    value: conf.computed,
    band: conf.computed < POLICY.confidenceEscalationThreshold ? 'escalate' : 'auto',
    threshold: POLICY.confidenceEscalationThreshold,
    belowThreshold: conf.computed < POLICY.confidenceEscalationThreshold,
    derivation: conf.derivation,
    waterfall,
    weakestSource: String(f.source),
    oldestInputMin: f.data_age_min,
    worstToolOutcome: String(f.tool_outcome),
    degradations: buildDegradations(trace),
    unverifiedFields: fields,
    unverifiedFieldsReconciled: reconciled,
    unverifiedCount: f.unverified_inputs,
    inputCount,
  };
}

/* =========================================================================
 * Gate and approval
 * ====================================================================== */

function buildEscalation(
  rung: Rung,
  requiredRole: ApprovalRole,
  escalated: boolean,
  reason: string,
  wouldHaveBeen?: ApprovalRole,
): EscalationVM | null {
  if (!escalated) return null;
  const ladder = [...GATE_LADDERS[rung]];
  const from = wouldHaveBeen ?? ladder[0];
  const reasons = reason
    .split(';')
    .map((r) => r.trim())
    .filter(Boolean);
  return {
    wouldHaveBeen: from,
    wouldHaveBeenLabel: ROLE_LABEL[from],
    became: requiredRole,
    becameLabel: ROLE_LABEL[requiredRole],
    reasons,
    triggeredByConfidence: reasons.some((r) => /confidence/i.test(r)),
    steps: Math.max(ladder.indexOf(requiredRole) - ladder.indexOf(from), 0),
    ladder,
  };
}

function buildGate(bundle: FixtureBundle): GateVM | null {
  const trace = bundle.trace;
  const steps = gates(trace);
  const captured = bundle.gate;
  if (!captured && steps.length === 0) return null;

  // `Outcome.gate` is null on the lapsed path even though the gate fired
  // (runner.py `_resolve` is called without it), so the trace is the fallback.
  const first = steps[0];
  const last = steps.at(-1);
  const rung = (captured?.rung ?? first?.rung) as Rung;
  const requiredRole = (captured?.required_role ?? first?.required_role) as ApprovalRole;
  const escalated = captured?.escalated ?? first?.escalated ?? false;
  const reason = captured?.escalation_reason || first?.escalation_reason || '';

  const status: GateVM['status'] = (() => {
    const s = last?.status;
    if (s === 'approved') return 'approved';
    if (s === 'rejected') return 'rejected';
    if (s === 'lapsed') return 'lapsed';
    if (s === 'auto') return 'auto';
    return 'awaiting';
  })();

  const rungVM = RUNGS[rung];
  return {
    rung: rungVM,
    requiredRole,
    requiredRoleLabel: ROLE_LABEL[requiredRole],
    autoApproved: captured?.auto_approved ?? requiredRole === 'auto',
    blocks: captured?.blocks ?? (rung !== 'rung_1_inform' && requiredRole !== 'auto'),
    needsCustomer: captured?.needs_customer ?? rung === 'rung_4_offer',
    escalated,
    escalation: buildEscalation(rung, requiredRole, escalated, reason, captured?.would_have_been),
    status,
    latencyS: last?.latency_s ?? null,
  };
}

/**
 * The approval window for one bundle, for the playback clock.
 *
 * Exported so the store counts down against the same number the panel shows.
 * They were two constants before, and the store's was a literal 15 with no
 * relationship to anything B said.
 */
export function approvalWindowMin(bundle: FixtureBundle): number {
  return requestedGateStep(bundle.trace)?.window_min ?? DEFAULT_APPROVAL_WINDOW_MIN;
}

/** Only for traces predating REQUEST TO B #2. Labelled as ours wherever shown. */
const DEFAULT_APPROVAL_WINDOW_MIN = 15;

/** The gate step recording the request, which is the only one carrying a deadline. */
function requestedGateStep(trace: TraceWire): GateStep | null {
  return (
    trace.steps.find(
      (s): s is GateStep => s.type === 'gate' && s.status === 'required',
    ) ?? null
  );
}

function buildApproval(
  gate: GateVM | null,
  state: RiskState,
  requested: GateStep | null,
): ApprovalVM | null {
  if (!gate) return null;

  // Rung 1 changes nothing on its own, so there is nothing to approve. It gets
  // an acknowledge-and-hand-off affordance instead. gates.py:79 skips every
  // escalation criterion for it, and `blocks` is false unconditionally.
  if (gate.rung.advisoryOnly) {
    return {
      actionable: false,
      role: 'berth_planner',
      roleLabel: ROLE_LABEL.berth_planner,
      handoff: true,
      ifNothingHappens:
        'Nothing. This is a notification, not a request — the boxes stay exactly where they are while it is read. Only the Berth Planner can act on it.',
      countdown: null,
    };
  }

  if (gate.needsCustomer) {
    return {
      actionable: false,
      role: 'customer',
      roleLabel: ROLE_LABEL.customer,
      handoff: false,
      ifNothingHappens:
        'The window closes and the boxes roll to the next service. The cargo moves either way — the difference is whether the line chose it.',
      // Policy, not invention: the window is B's `CUSTOMER_WINDOW_MIN` and is
      // recorded on the `external_gate` step. B still serialises no absolute
      // deadline for the customer gate, so the clock itself is rendered here.
      countdown: {
        windowMin: POLICY.customerWindowMin,
        expiresAt: null,
        source: 'policy',
        note: `${POLICY.customerWindowMin}-minute window from config.CUSTOMER_WINDOW_MIN, recorded on the external gate step. B serialises no absolute deadline for the customer gate, so the clock is rendered here against that window.`,
      },
    };
  }

  const open = gate.status === 'awaiting' && state !== 'resolved' && state !== 'failed';
  return {
    actionable: gate.blocks,
    role: gate.requiredRole,
    roleLabel: gate.requiredRoleLabel,
    handoff: false,
    ifNothingHappens:
      'Auto-declines. The approval lapses, nothing is booked, the boxes roll, and B records the outcome as APPROVAL_LAPSED — distinct from the resolution used when the shipping line itself never replies, so an unsigned internal approval is not reported as a customer we failed.',
    countdown: open ? approvalCountdown(requested) : null,
  };
}

/**
 * The internal approval countdown.
 *
 * B now sends `window_min` and `expires_at` on the `required` gate step, so
 * the clock on screen is the one policy actually specifies. The fallback is
 * kept, and kept honest: a trace captured before that landed renders a timer
 * labelled as the console's own rather than silently borrowing the authority
 * of a deadline nobody set.
 */
function approvalCountdown(requested: GateStep | null): ApprovalVM['countdown'] {
  if (requested?.window_min != null) {
    return {
      windowMin: requested.window_min,
      expiresAt: requested.expires_at ?? null,
      source: 'policy',
      note: `${requested.window_min}-minute window from config.APPROVAL_WINDOW_MIN, recorded on the gate step when the approval was requested.`,
    };
  }
  return {
    windowMin: 15,
    expiresAt: null,
    source: 'console-timer',
    note: 'Console-side timer. This trace carries no approval deadline, so the clock is ours and not policy.',
  };
}

/* =========================================================================
 * Options
 * ====================================================================== */

function buildOptions(trace: TraceWire): OptionVM[] {
  const out: OptionVM[] = [];
  const opts = optionsStep(trace);
  const decisionSteps = decisions(trace);
  const chosen = decisionSteps.find((d) => d.chosen);

  /* --- the comparison the agent actually made --------------------------
     B's `options` step carries every candidate with its cost and emissions,
     runners-up included. That is what makes a ranking legible as a ranking
     rather than an assertion about a winner. */
  if (opts) {
    for (const cand of opts.candidates) {
      const movesCargo = cand.rung === 'rung_3_move';
      out.push({
        id: cand.option_id,
        rung: RUNGS[cand.rung],
        status: cand.chosen ? 'chosen' : 'considered',
        detail: cand.detail,
        rationale: cand.chosen ? (chosen?.rationale ?? '') : '',
        exclusionReason: null,
        confidence: cand.chosen ? (chosen?.confidence ?? null) : null,
        costSgd: cand.cost_sgd,
        emissionsKgCo2e: cand.emissions_kg_co2e,
        movesCargo,
      });
    }
  }

  /* --- decisions ------------------------------------------------------
     Rung 1 advisories are traced as decisions with `chosen: false`. The
     chosen decision is skipped when the options step already covered it, so
     one option never appears twice. */
  for (const d of decisionSteps) {
    if (d.chosen && opts) continue;
    out.push({
      id: `seq-${d.seq}`,
      rung: RUNGS[d.rung],
      status: d.chosen ? 'chosen' : 'advisory',
      detail: '',
      rationale: d.rationale,
      exclusionReason: null,
      confidence: d.confidence,
      costSgd: d.cost_sgd ?? NOT_IN_TRACE(),
      emissionsKgCo2e: d.emissions_kg_co2e ?? NOT_IN_TRACE(),
      movesCargo: d.rung === 'rung_3_move',
    });
  }

  /* --- ruled out in code, before the prompt was built ------------------ */
  for (const o of observations(trace)) {
    if (!o.considered) continue;
    const summary = o.summary;
    const marker = summary.indexOf('ruled out ');
    const tail = marker >= 0 ? summary.slice(marker + 'ruled out '.length) : summary;
    const [id, ...rest] = tail.split(': ');
    out.push({
      id,
      rung: RUNGS[(o.rung ?? 'rung_3_move') as Rung],
      status: 'ruled_out',
      detail: '',
      rationale: '',
      exclusionReason: rest.join(': '),
      confidence: null,
      costSgd: NOT_COSTED(),
      emissionsKgCo2e: NOT_COSTED(),
      movesCargo: false,
    });
  }

  const rank = { chosen: 0, advisory: 1, considered: 2, ruled_out: 3 } as const;
  return out.sort(
    (a, b) =>
      rank[a.status] - rank[b.status] ||
      (isMissing(a.costSgd) || isMissing(b.costSgd) ? 0 : a.costSgd - b.costSgd),
  );
}

/* =========================================================================
 * Contested resources
 * ====================================================================== */

/**
 * `ClaimResult.reason` in operator English, plus what it meant for this
 * connection. The Lock Table exists so two deliberations cannot both book the
 * last slot, and a console that only showed "lost" would not say why.
 */
const CLAIM_COPY: Record<string, { outcome: string; consequence: string }> = {
  uncontested: {
    outcome: 'Reserved — nothing else wanted it',
    consequence: 'Held through to the booking, then committed.',
  },
  already_held: {
    outcome: 'Re-claimed a reservation this connection already held',
    consequence: 'The reservation was refreshed rather than duplicated.',
  },
  incumbent_committed: {
    outcome: 'Already committed to another connection',
    consequence:
      'A committed slot is consumed capacity — the move has begun and cannot be un-booked. This connection re-deliberated with the option removed.',
  },
  preempted_lower_priority: {
    outcome: 'Taken from a lower-priority connection',
    consequence:
      'Arbitrated on boxes over remaining slack, not on who asked first. The other connection was told, so it could re-deliberate.',
  },
  outranked: {
    outcome: 'Outranked by a more urgent connection',
    consequence: 'This connection re-deliberated with the option removed.',
  },
};

function buildLocks(trace: TraceWire): LockVM[] {
  return trace.steps.filter(isType<LockStep>('lock')).map((s) => {
    const copy = CLAIM_COPY[s.action] ?? {
      outcome: s.action || (s.status === 'held' ? 'Reserved' : 'Not granted'),
      consequence: '',
    };
    return {
      resource: s.resource,
      held: s.status === 'held',
      ourPriority: s.our_priority,
      winnerPriority: s.winner_priority,
      outcome: copy.outcome,
      consequence: copy.consequence,
    };
  });
}

/* =========================================================================
 * Timeline
 * ====================================================================== */

function toTimelineEvent(step: TraceStep): TimelineEventVM {
  const base = { seq: step.seq, raw: step as unknown as Record<string, unknown> };
  const none = { latencyMs: null, toolStatus: null, tokens: null };

  switch (step.type) {
    case 'observation': {
      const s = step as ObservationStep;
      const detail: string[] = [];
      if (s.reason_codes?.length) {
        detail.push(s.reason_codes.map((c) => REASONS[c]?.title ?? c).join(' · '));
      }
      if (s.triage_route) detail.push(TRIAGE_LABEL[s.triage_route] ?? s.triage_route);
      if (s.slack_is_scenario_output) {
        detail.push('Every figure below is a scenario output, not an observation.');
      }
      return {
        ...base,
        ...none,
        kind: 'observation',
        tone: s.considered ? 'muted' : 'normal',
        label: s.considered ? 'RULED OUT' : 'OBSERVED',
        title: s.summary,
        detail,
      };
    }
    case 'state_change': {
      const s = step as StateChangeStep;
      const offRamp = ['superseded', 'stale', 'lapsed', 'lost_lock', 'failed'].includes(s.to_state);
      return {
        ...base,
        ...none,
        kind: 'state_change',
        tone: offRamp ? 'escalation' : s.to_state === 'resolved' ? 'success' : 'muted',
        label: 'STATE',
        title: `${STATE_LABEL[s.from_state]} → ${STATE_LABEL[s.to_state]}`,
        detail: s.reason ? [s.reason] : [],
      };
    }
    case 'decision': {
      const s = step as DecisionStep;
      const rung = RUNGS[s.rung];
      return {
        ...base,
        ...none,
        kind: 'decision',
        tone: 'decision',
        title: s.chosen
          ? `Chose Rung ${rung.number} — ${rung.name}`
          : `Rung ${rung.number} — ${rung.name} (advisory, not the action)`,
        label: 'DECIDED',
        detail: [s.rationale, `Confidence ${s.confidence.toFixed(4)}`].filter(Boolean),
      };
    }
    case 'tool_call': {
      const s = step as ToolCallStep;
      const bad = s.status !== 'ok';
      return {
        ...base,
        kind: 'tool_call',
        tone: bad ? 'error' : 'normal',
        label: 'TOOL',
        title: s.tool,
        detail:
          s.attempts && s.attempts > 1 ? [`${s.attempts} attempts`] : [],
        latencyMs: s.latency_ms,
        toolStatus: s.status,
        tokens: null,
      };
    }
    case 'lock': {
      const s = step as LockStep;
      return {
        ...base,
        ...none,
        kind: 'lock',
        tone: s.status === 'lost' ? 'escalation' : 'normal',
        label: 'LOCK',
        title:
          s.status === 'held'
            ? `Reserved ${s.resource}`
            : `Lost ${s.resource} to a more urgent connection`,
        detail: [
          `Our priority ${s.our_priority}` +
            (s.winner_priority != null ? ` · winner ${s.winner_priority}` : ''),
          s.action,
        ].filter(Boolean),
      };
    }
    case 'error': {
      const s = step as ErrorStep;
      return {
        ...base,
        ...none,
        kind: 'error',
        tone: 'error',
        label: 'ERROR',
        title: `${s.tool} — ${s.error_class}`,
        detail: [`${s.retries} retr${s.retries === 1 ? 'y' : 'ies'}`, `Fell back to: ${s.recovery}`],
      };
    }
    case 'confidence': {
      const s = step as ConfidenceStep;
      return {
        ...base,
        ...none,
        kind: 'confidence',
        tone: s.computed < POLICY.confidenceEscalationThreshold ? 'escalation' : 'normal',
        label: 'CONFIDENCE',
        title: `Computed ${s.computed.toFixed(4)}`,
        detail: [s.derivation],
      };
    }
    case 'gate': {
      const s = step as GateStep;
      const rung = RUNGS[s.rung];
      return {
        ...base,
        ...none,
        kind: 'gate',
        tone: s.escalated ? 'escalation' : s.status === 'approved' ? 'success' : 'normal',
        label: 'GATE',
        title: s.escalated
          ? `Escalated to ${ROLE_LABEL[s.required_role]}`
          : `Rung ${rung.number} requires ${ROLE_LABEL[s.required_role]}`,
        detail: [s.escalation_reason, `Status: ${s.status}`].filter(Boolean),
      };
    }
    case 'external_gate': {
      const s = step as ExternalGateStep;
      return {
        ...base,
        ...none,
        kind: 'external_gate',
        tone: s.outcome === 'LAPSED_NO_RESPONSE' ? 'error' : 'decision',
        label: 'LINE',
        title: `${s.options_sent} option${s.options_sent === 1 ? '' : 's'} sent to the ${s.party}`,
        detail: [
          `${s.window_min}-minute window`,
          s.outcome === 'DECIDED'
            ? 'The line chose.'
            : s.outcome === 'DECLINED_ALL'
              ? 'The line declined every option — and was served.'
              : 'No reply before the window closed.',
        ],
      };
    }
    case 'model_call': {
      const s = step as ModelCallStep;
      return {
        ...base,
        kind: 'model_call',
        tone: 'muted',
        label: 'MODEL',
        title: `${s.model} · ${s.purpose}`,
        detail: [`${s.input_tokens.toLocaleString()} in / ${s.output_tokens.toLocaleString()} out`],
        latencyMs: null,
        toolStatus: null,
        tokens: {
          model: s.model,
          purpose: s.purpose,
          input: s.input_tokens,
          output: s.output_tokens,
          usd: s.usd,
        },
      };
    }
    default: {
      const s = step as TraceStep;
      return {
        ...base,
        ...none,
        kind: s.type as TimelineKind,
        tone: 'normal' as TimelineTone,
        label: s.type.toUpperCase(),
        title: s.type,
        detail: [],
      };
    }
  }
}

/* =========================================================================
 * Outcome, cost, triage, provenance
 * ====================================================================== */

/**
 * Whose outcome this was, and what colour that is.
 *
 * Badge and tone are decided together because they were decided apart, and
 * disagreed: `outcomeBadge` weighed four flags while the panel's styling
 * ternary weighed two, so a `failed` resolution announced "system fault" in
 * the same neutral grey as a routine internal hold.
 *
 * Every input is nullable, and null means B did not say. That case gets its
 * own badge rather than a default, because the alternative — treating an
 * absent `reached_the_line` as false — has the console assert on screen that
 * the shipping line was never contacted, on no evidence at all.
 */
function outcomeVerdict(f: {
  serviceSuccess: boolean | null;
  reachedTheLine: boolean | null;
  excludedFromMetric: boolean | null;
  agentFault: boolean | null;
}): { badge: OutcomeBadge; tone: OutcomeTone } {
  if (f.agentFault) return { badge: 'system fault', tone: 'fault' };
  if (f.excludedFromMetric) return { badge: 'not counted', tone: 'neutral' };
  if (
    f.serviceSuccess === null ||
    f.reachedTheLine === null ||
    f.excludedFromMetric === null ||
    f.agentFault === null
  ) {
    return { badge: 'outcome not recorded', tone: 'gap' };
  }
  if (!f.reachedTheLine) {
    return f.serviceSuccess
      ? { badge: 'held internally', tone: 'neutral' }
      : { badge: 'decided internally', tone: 'neutral' };
  }
  return f.serviceSuccess
    ? { badge: 'customer served', tone: 'good' }
    : { badge: 'service failure', tone: 'bad' };
}

function buildOutcome(bundle: FixtureBundle): OutcomeVM | null {
  const resolution = bundle.result.resolution;
  if (!resolution) return null;
  const ext = externalGate(bundle.trace);
  const copy = RESOLUTION_COPY[resolution];
  const cv = bundle.case_view;

  // Every one of these is B's. Null is preserved as null: the console does not
  // get to decide what B declined to tell it.
  const serviceSuccess = cv.service_success;
  const reachedTheLine = cv.reached_the_line;
  const agentFault = cv.agent_fault;
  const excludedFromMetric = cv.excluded_from_metric;

  // Named, so the circularity that broke the previous version of this check is
  // visible on the page: reconciling a value against the same expression that
  // produced it can only ever succeed.
  const byTranscribedList = SERVICE_SUCCESS_RESOLUTIONS.includes(resolution);
  const verdict = outcomeVerdict({
    serviceSuccess,
    reachedTheLine,
    excludedFromMetric,
    agentFault,
  });

  return {
    resolution,
    label: copy.label,
    what: copy.what,
    serviceSuccess,
    serviceSuccessReconciled:
      serviceSuccess === null ? null : serviceSuccess === byTranscribedList,
    reachedTheLine,
    agentFault,
    why: copy.why,
    excludedFromMetric,
    badge: verdict.badge,
    tone: verdict.tone,
    customerGate: ext
      ? { optionsSent: ext.options_sent, windowMin: ext.window_min, outcome: ext.outcome }
      : null,
    decisionLeadTimeH: bundle.trace.outcome.decision_lead_time_h,
    actionCostSgd: bundle.trace.outcome.action_cost_sgd ?? null,
    actionEmissionsKgCo2e: bundle.trace.outcome.action_emissions_kg_co2e ?? null,
  };
}

function buildCost(trace: TraceWire): CostVM {
  return {
    modelCalls: trace.cost.model_calls,
    inputTokens: trace.cost.input_tokens,
    outputTokens: trace.cost.output_tokens,
    usd: trace.cost.usd,
    byModel: trace.cost.by_model,
    perDecision: modelCalls(trace).map((s) => ({
      seq: s.seq,
      model: s.model,
      purpose: s.purpose,
      usd: s.usd,
      input: s.input_tokens,
      output: s.output_tokens,
    })),
  };
}

function buildTriage(trace: TraceWire): TriageVM {
  const step = observations(trace).find((o) => o.triage_route);
  const route = (step?.triage_route as string) ?? 'unknown';
  const usedModel = modelCalls(trace).some((m) => m.purpose === 'triage');
  return {
    route,
    routeLabel: TRIAGE_LABEL[route] ?? route,
    kept: !route.startsWith('dismissed'),
    decidedFree: !usedModel,
    reason: step?.summary ?? '',
  };
}

function buildProvenance(bundle: FixtureBundle): ProvenanceVM {
  const a = bundle.assumptions;
  const synthetic = [
    a.ucid_synthetic && 'connection id',
    a.pairing_synthetic && 'which box connects to which vessel',
    a.terminals_synthetic && 'terminal assignment',
    a.boxes_synthetic && 'box count',
  ].filter(Boolean) as string[];

  return {
    dataBasis: bundle.provenance.data_basis,
    terminalResolution: bundle.risk.inbound.terminal_resolution,
    terminalResolutionLabel: TERMINAL_RESOLUTION_LABEL[bundle.risk.inbound.terminal_resolution],
    anySynthetic: synthetic.length > 0,
    syntheticFields: synthetic,
    transferScenario: a.transfer_scenario,
    modelScripted: bundle.provenance.model_responses !== 'live',
    modelDisclosure:
      bundle.provenance.model_disclosure ??
      'No model was consulted on this run. The trace measures the pipeline, not the agent.',
    authored: bundle.provenance.authored,
    authoredBecause: bundle.provenance.authored_because ?? null,
  };
}

function buildLeg(
  call: FixtureBundle['risk']['inbound'],
  fallbackName: string,
  timingResolution: TimingResolution,
): VesselLegVM {
  const deviationMin =
    (new Date(call.estimated).getTime() - new Date(call.scheduled).getTime()) / 60000;
  return {
    name: call.vessel_name === 'UNKNOWN' ? fallbackName : call.vessel_name,
    terminal: call.terminal,
    terminalLabel: TERMINAL_LABEL[call.terminal],
    referenceTime: call.scheduled,
    arrivalTime: call.estimated,
    timingResolution,
    timingProvenanceLabel: TIMING_RESOLUTION_LABEL[timingResolution],
    deviationMin: Math.round(deviationMin),
  };
}

function lifecycleOf(state: RiskState): Lifecycle {
  if (state === 'resolved' || state === 'failed') return 'resolved';
  if (state === 'dismissed' || state === 'superseded' || state === 'stale' || state === 'lost_lock') {
    return 'abandoned';
  }
  return 'live';
}

/* =========================================================================
 * The one entry point
 * ====================================================================== */

export function toViewModel(bundle: FixtureBundle): ConnectionVM {
  const { event, risk, trace, derived } = bundle;
  const state = bundle.result.state;
  const gate = buildGate(bundle);

  const slack: SlackVM = {
    currentPlanHours: event.current_plan_slack_hours,
    noIttHours: event.no_itt_slack_hours,
    ittCostHours: derived.itt_cost_hours,
    deficitHours: derived.slack_deficit_hours,
    consumedPct: risk.derived.slack_consumed_pct,
  };

  return {
    id: event.connection_id,
    ucid: trace.ucid,
    severity: event.state,
    severityLabel: SEVERITY_LABEL[event.state],
    state,
    stateLabel: STATE_LABEL[state],
    stateNote: STATE_NOTE[state] ?? null,
    lifecycle: lifecycleOf(state),
    boxes: event.affected_boxes,
    priority: derived.priority,
    detectedAt: risk.detected_at,

    slack,
    rescuableByRemovingItt: derived.itt_is_the_problem,
    crossesTerminals: risk.derived.crosses_terminals,

    inbound: buildLeg(
      risk.inbound,
      event.inbound_vessel ?? 'Unknown vessel',
      event.timing_resolution,
    ),
    outbound: buildLeg(
      risk.outbound,
      event.outbound_vessel ?? 'Unknown vessel',
      event.timing_resolution,
    ),

    watcherConfidence: event.confidence,
    reasons: event.reason_codes.map((code) => ({
      code,
      title: REASONS[code].title,
      detail: REASONS[code].detail,
      emittedByWatcher: REASONS[code].emitted,
    })) satisfies ReasonVM[],
    triage: buildTriage(trace),

    confidence: buildConfidence(trace, event.confidence),
    gate,
    approval: buildApproval(gate, state, requestedGateStep(trace)),
    options: buildOptions(trace),
    locks: buildLocks(trace),
    timeline: trace.steps.map(toTimelineEvent),
    outcome: buildOutcome(bundle),
    cost: buildCost(trace),
    provenance: buildProvenance(bundle),

    raw: { event, risk, trace, caseView: bundle.case_view },
  };
}

export function toViewModels(bundles: FixtureBundle[]): ConnectionVM[] {
  return bundles.map(toViewModel);
}

/** Risk queue ordering: at-risk first, then by B's own priority. */
export function byCriticality(a: ConnectionVM, b: ConnectionVM): number {
  const rank: Record<RiskSeverity, number> = { AT_RISK: 0, WATCH: 1, SAFE: 2 };
  const workflowRank = (c: ConnectionVM) => {
    if (c.lifecycle !== 'live') return 3;
    if (c.approval?.actionable === true && c.gate?.status === 'awaiting') return 0;
    if (!c.outcome) return 1;
    return 2;
  };
  return (
    workflowRank(a) - workflowRank(b) ||
    rank[a.severity] - rank[b.severity] ||
    b.priority - a.priority
  );
}

export { ROLE_LABEL, RUNGS, STATE_LABEL, TERMINAL_LABEL, SEVERITY_LABEL };
