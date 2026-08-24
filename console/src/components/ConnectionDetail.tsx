/** Operator-facing connection workspace. Implementation evidence lives elsewhere. */

import { useEffect, useRef, useState } from 'react';

import type { ConnectionVM, OptionVM } from '../adapters/types';
import { hhmm, hoursAndMinutes, pct, signedHours, stamp } from '../lib/format';
import { Panel, SeverityBadge, StateBadge, Stat } from './ui';

type View = 'situation' | 'plans' | 'outcome';

function VesselChip({
  leg,
  role,
  movement,
}: {
  leg: ConnectionVM['inbound'];
  role: 'Inbound' | 'Outbound';
  movement?: 'stay' | 'move';
}) {
  const late = leg.deviationMin > 0;
  return (
    <div className={`placement-vessel ${movement ? `placement-vessel-${movement}` : ''}`}>
      <div className="placement-vessel-icon" aria-hidden>
        <svg viewBox="0 0 34 20">
          <path d="M3 13.5h28l-4 4H8z" />
          <path d="M9 7.5h12v6H9zM13 3.5h6v4h-6z" />
        </svg>
      </div>
      <div className="placement-vessel-copy">
        <span>{role}</span>
        <strong title={leg.name}>{leg.name}</strong>
        <small className={late ? 'text-risk-500' : ''}>
          Expected {hhmm(leg.estimated)}{late ? ` · ${leg.deviationMin}m late` : ''}
        </small>
      </div>
      {movement && <span className={`placement-movement placement-movement-${movement}`}>{movement === 'stay' ? 'Stays' : 'Move here'}</span>}
    </div>
  );
}

function PlacementVisual({ c }: { c: ConnectionVM }) {
  const recommendColocation = c.crossesTerminals && c.rescuableByRemovingItt;
  const historical = c.lifecycle !== 'live';

  return (
    <div className="placement-visual">
      <section className="placement-row">
        <header>
          <span>{historical ? 'Arrangement at detection' : 'Current arrangement'}</span>
          <small>{c.crossesTerminals ? 'Cargo crosses terminals' : 'Already co-located'}</small>
        </header>
        <div className="placement-current-grid">
          <div className="placement-terminal">
            <span className="placement-terminal-label">{c.inbound.terminalLabel}</span>
            <VesselChip leg={c.inbound} role="Inbound" />
          </div>
          <div className={`placement-transfer-path ${c.crossesTerminals ? 'placement-transfer-path-risk' : ''}`}>
            <span aria-hidden>→</span>
            <small>{c.crossesTerminals ? `${c.slack.ittCostHours.toFixed(1)}h transfer` : 'Same terminal'}</small>
          </div>
          <div className="placement-terminal">
            <span className="placement-terminal-label">{c.outbound.terminalLabel}</span>
            <VesselChip leg={c.outbound} role="Outbound" />
          </div>
        </div>
      </section>

      {recommendColocation ? (
        <section className="placement-row placement-row-proposed">
          <header>
            <span>{historical ? 'Placement considered' : 'Proposed placement'}</span>
            <small className="placement-recommended-label">{historical ? 'Historical' : 'Recommended'}</small>
          </header>
          <div className="placement-proposal-grid">
            <div className="placement-terminal placement-terminal-target">
              <div className="placement-target-heading">
                <span className="placement-terminal-label">{c.inbound.terminalLabel}</span>
                <span>Shared terminal</span>
              </div>
              <div className="placement-target-vessels">
                <VesselChip leg={c.inbound} role="Inbound" movement="stay" />
                <VesselChip leg={c.outbound} role="Outbound" movement="move" />
              </div>
            </div>
            <div className="placement-impact-card">
              <span>Operational effect</span>
              <strong>+{c.slack.ittCostHours.toFixed(1)}h margin</strong>
              <p>No terminal transfer for the boxes.</p>
              <small>{historical ? 'Historical plan · exact berth required planner confirmation' : 'Proposed only · exact berth requires planner confirmation'}</small>
            </div>
          </div>
        </section>
      ) : (
        <section className="placement-note">
          <strong>{c.crossesTerminals ? 'Co-location does not fully recover this connection' : 'No berth move is needed'}</strong>
          <p>{c.crossesTerminals ? 'Review the other suggested recovery plans.' : `Both vessels already call at ${c.inbound.terminalLabel}.`}</p>
        </section>
      )}
    </div>
  );
}

function MarginComparison({ c }: { c: ConnectionVM }) {
  return (
    <div className="margin-comparison">
      <div className="margin-option margin-option-current">
        <span>{c.lifecycle === 'live' ? 'Current plan' : 'Plan at detection'}</span>
        <strong className={c.slack.currentPlanHours < 0 ? 'text-risk-500' : 'text-safe-500'}>
          {signedHours(c.slack.currentPlanHours)}
        </strong>
        <small>
          {c.slack.currentPlanHours < 0
            ? `${hoursAndMinutes(c.slack.currentPlanHours)} — boxes miss the cut-off`
            : `${hoursAndMinutes(c.slack.currentPlanHours)} of remaining margin`}
        </small>
      </div>
      <div className="margin-arrow" aria-hidden>→</div>
      <div className="margin-option margin-option-better">
        <span>Without the terminal transfer</span>
        <strong className={c.slack.noIttHours < 0 ? 'text-risk-500' : 'text-safe-500'}>
          {signedHours(c.slack.noIttHours)}
        </strong>
        <small>
          {c.slack.noIttHours > 0
            ? `${hoursAndMinutes(c.slack.noIttHours)} of usable margin`
            : 'The connection would still miss its cut-off'}
        </small>
      </div>
    </div>
  );
}

function Situation({ c }: { c: ConnectionVM }) {
  const historical = c.lifecycle !== 'live';
  return (
    <div className="space-y-4">
      <section className={`situation-callout ${c.rescuableByRemovingItt ? 'situation-callout-actionable' : ''}`}>
        <div>
          <span className="text-[11px] font-medium text-mist-500">{historical ? 'Original risk' : 'What needs attention'}</span>
          <h2>
            {historical
              ? `This connection is closed as ${c.stateLabel.toLowerCase()}.`
              : c.slack.currentPlanHours < 0
              ? `This connection misses its cut-off by ${hoursAndMinutes(c.slack.currentPlanHours).replace(' short', '')}.`
              : `This connection has ${hoursAndMinutes(c.slack.currentPlanHours)} of margin remaining.`}
          </h2>
          <p>
            {historical
              ? c.outcome?.what ?? c.stateNote ?? 'The captured risk is retained here for historical review.'
              : c.rescuableByRemovingItt
              ? `Keeping both vessels at one terminal restores ${c.slack.ittCostHours.toFixed(1)} hours and makes the connection viable.`
              : c.crossesTerminals
                ? 'The cargo crosses terminals, but removing that transfer alone does not fully recover the connection.'
                : 'Both vessels use the same terminal; the risk comes from vessel timing rather than a terminal transfer.'}
          </p>
        </div>
        {historical
          ? <span className="situation-tag situation-tag-closed">Closed</span>
          : c.rescuableByRemovingItt && <span className="situation-tag">Recoverable</span>}
      </section>

      <Panel
        title={historical ? 'Vessel placement record' : 'Vessel placement'}
        subtitle={historical ? 'Captured arrangement and the plan considered at the time' : 'Current terminal calls and the proposed co-location plan'}
      >
        <PlacementVisual c={c} />
      </Panel>

      <Panel
        title={historical ? 'Historical connection margin' : 'Connection margin'}
        subtitle={historical ? 'Margin captured when the risk was detected' : 'The operational effect of removing the terminal transfer'}
      >
        <MarginComparison c={c} />
      </Panel>

      <Panel title={historical ? 'Why this connection was flagged' : 'Why this connection is at risk'}>
        <div className="operator-reasons">
          {c.reasons.map((reason) => (
            <div key={reason.code}>
              <span className="reason-dot" />
              <div>
                <strong>{reason.title}</strong>
                <p>{reason.detail}</p>
              </div>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
}

function planTitle(option: OptionVM, c: ConnectionVM) {
  if (option.rung.name === 'PREVENT') return `Co-locate both vessels at ${c.inbound.terminalLabel}`;
  if (option.rung.name === 'MOVE') {
    const mode = option.detail?.split(',')[0]?.trim();
    return `Move ${c.boxes} boxes${mode ? ` by ${mode}` : ' between terminals'}`;
  }
  if (option.rung.name === 'OFFER') {
    const count = option.detail?.match(/\d+/)?.[0];
    return count ? `Offer ${count} onward services` : `Offer alternatives for ${c.outbound.name}`;
  }
  return option.rung.does;
}

function planEffect(option: OptionVM, c: ConnectionVM) {
  if (option.rung.name === 'PREVENT') return `Restores ${c.slack.ittCostHours.toFixed(1)} hours of margin`;
  if (option.rung.name === 'MOVE') return `Protects ${c.outbound.name}'s current call`;
  if (option.rung.name === 'OFFER') return `Lets the line choose another service from ${c.outbound.terminalLabel}`;
  return 'Provides another way to protect the connection';
}

function planDescription(option: OptionVM, c: ConnectionVM) {
  if (option.rung.name === 'PREVENT') {
    return `Move ${c.outbound.name} to ${c.inbound.terminalLabel}; ${c.inbound.name} stays in place.`;
  }
  if (option.rung.name === 'MOVE') {
    return option.detail
      ? `${c.inbound.terminalLabel} → ${c.outbound.terminalLabel} · ${option.detail}`
      : `Reserve the next movement from ${c.inbound.terminalLabel} to ${c.outbound.terminalLabel}.`;
  }
  if (option.rung.name === 'OFFER') {
    return option.detail
      ? `${option.detail}; ask the shipping line to choose.`
      : `Share alternatives to ${c.outbound.name} and let the shipping line choose.`;
  }
  return option.detail || option.rung.does;
}

type PlanGroup = { key: string; primary: OptionVM; variants: OptionVM[]; recommended: boolean };

function groupPlans(c: ConnectionVM): PlanGroup[] {
  const grouped = new Map<string, OptionVM[]>();
  for (const option of c.options.filter((item) => item.status !== 'ruled_out')) {
    const key = option.rung.name;
    grouped.set(key, [...(grouped.get(key) ?? []), option]);
  }

  return [...grouped.entries()]
    .map(([key, variants]) => ({
      key,
      primary: variants.find((option) => option.status === 'chosen') ?? variants[0]!,
      variants,
      recommended: variants.some((option) => option.status === 'chosen'),
    }))
    .sort((a, b) => Number(b.recommended) - Number(a.recommended))
    .slice(0, 3);
}

function planSteps(option: OptionVM, c: ConnectionVM): string[] {
  if (option.rung.name === 'PREVENT') {
    return [
      `Confirm ${c.inbound.terminalLabel} can receive both vessel calls.`,
      `Keep ${c.inbound.name} at ${c.inbound.terminalLabel}.`,
      `Move ${c.outbound.name} from ${c.outbound.terminalLabel} to ${c.inbound.terminalLabel}.`,
      'Have the berth planner assign the exact berth and publish the revised call.',
    ];
  }
  if (option.rung.name === 'MOVE') {
    return [
      `Reserve the selected transfer departure${option.detail ? `: ${option.detail}` : ''}.`,
      `Stage all ${c.boxes} boxes at ${c.inbound.terminalLabel}.`,
      `Move the boxes to ${c.outbound.terminalLabel} and confirm terminal receipt.`,
      `Deliver the boxes before ${c.outbound.name}'s loading cut-off.`,
    ];
  }
  if (option.rung.name === 'OFFER') {
    return [
      'Prepare the available onward-service alternatives.',
      'Send the ranked choices to the shipping line.',
      'Hold the response window while the line chooses.',
      'Book the selected service and notify terminal operations.',
    ];
  }
  return ['Review the recommendation with the responsible planner.', 'Confirm the operational instruction before execution.'];
}

export type PlanSelection = { key: string; label: string };

function PlanDetail({
  group,
  c,
  selectedForApproval,
  onSelect,
}: {
  group: PlanGroup;
  c: ConnectionVM;
  selectedForApproval: boolean;
  onSelect: () => void;
}) {
  const option = group.primary;
  const canSelect = c.lifecycle === 'live' && c.approval?.actionable === true;
  return (
    <section className="plan-detail-panel">
      <header>
        <div>
          <span>Plan details</span>
          <h3>{planTitle(option, c)}</h3>
        </div>
        <span className={group.recommended ? 'plan-label-recommended' : 'plan-label'}>
          {group.recommended ? 'Recommended' : 'Alternative'}
        </span>
      </header>

      <div className="plan-detail-grid">
        <div>
          <h4>What happens next</h4>
          <ol className="plan-steps">
            {planSteps(option, c).map((step, index) => (
              <li key={step}>
                <span>{index + 1}</span>
                <p>{step}</p>
              </li>
            ))}
          </ol>
        </div>

        <aside>
          <h4>{group.variants.length > 1 ? 'Available departures' : 'Operational note'}</h4>
          {group.variants.length > 1 ? (
            <div className="plan-variants">
              {group.variants.map((variant) => (
                <div key={variant.id} className={variant.status === 'chosen' ? 'plan-variant-selected' : ''}>
                  <span>{variant.detail || 'Planner-arranged movement'}</span>
                  {variant.status === 'chosen' && <strong>Selected</strong>}
                </div>
              ))}
            </div>
          ) : (
            <p className="plan-caveat">
              {option.rung.name === 'PREVENT'
                ? 'The terminal is proposed; the berth planner must confirm the exact berth before this becomes an instruction.'
                : option.rung.name === 'OFFER'
                  ? 'The shipping line owns the final choice and may let the response window close.'
                  : 'Terminal Operations must confirm capacity before execution.'}
            </p>
          )}
        </aside>
      </div>

      {canSelect && (
        <footer className="plan-detail-actions">
          <div>
            <span>Approval choice</span>
            <strong>{selectedForApproval ? 'This plan will be sent for approval' : 'Review complete? Select this plan to continue.'}</strong>
          </div>
          <button
            type="button"
            className={selectedForApproval ? 'button-secondary plan-selected-button' : 'button-primary'}
            onClick={onSelect}
            disabled={selectedForApproval}
          >
            {selectedForApproval ? '✓ Selected for approval' : 'Select this plan'}
          </button>
        </footer>
      )}
    </section>
  );
}

function SuggestedPlans({
  c,
  selectedPlanKey,
  onPlanSelect,
}: {
  c: ConnectionVM;
  selectedPlanKey: string | null;
  onPlanSelect: (selection: PlanSelection) => void;
}) {
  const plans = groupPlans(c);
  const [openPlan, setOpenPlan] = useState<string | null>(plans[0]?.key ?? null);
  const selectedPlan = plans.find((plan) => plan.key === openPlan) ?? plans[0] ?? null;
  const approvalPlan =
    plans.find((plan) => plan.key === selectedPlanKey) ??
    plans.find((plan) => plan.recommended) ??
    plans[0] ??
    null;

  return (
    <div className="space-y-4">
      <section className="plan-intro">
        <div>
          <h2>Suggested recovery plans</h2>
          <p>Distinct strategies are shown once. Select a plan to inspect its operational steps.</p>
        </div>
        <span>{plans.length} option{plans.length === 1 ? '' : 's'}</span>
      </section>

      {plans.length > 0 ? (
        <div className="suggested-plans">
          {plans.map((group, index) => {
            const option = group.primary;
            const recommended = group.recommended || (index === 0 && !plans.some((plan) => plan.recommended));
            const expanded = selectedPlan?.key === group.key;
            return (
              <button
                type="button"
                key={group.key}
                className={`suggested-plan ${recommended ? 'suggested-plan-recommended' : ''} ${expanded ? 'suggested-plan-expanded' : ''} ${approvalPlan?.key === group.key ? 'suggested-plan-selected' : ''}`}
                onClick={() => setOpenPlan(group.key)}
                aria-expanded={expanded}
              >
                <header>
                  <span className="plan-number">{index + 1}</span>
                  <div>
                    <h3>{planTitle(option, c)}</h3>
                    <p>{planEffect(option, c)}</p>
                  </div>
                  <span className={recommended ? 'plan-label-recommended' : 'plan-label'}>
                    {recommended ? 'Recommended' : option.status === 'advisory' ? 'Planner action' : 'Alternative'}
                  </span>
                </header>
                <div className="plan-description">
                  <p>{planDescription(option, c)}</p>
                  <span>
                    {approvalPlan?.key === group.key ? 'Selected for approval' : expanded ? 'Details open' : 'View details'}
                    <b aria-hidden>{approvalPlan?.key === group.key ? '✓' : expanded ? '−' : '+'}</b>
                  </span>
                </div>
              </button>
            );
          })}
        </div>
      ) : (
        <section className="empty-operator-state">
          <h3>No recovery plan was produced</h3>
          <p>This connection needs manual review by terminal operations.</p>
        </section>
      )}

      {selectedPlan && (
        <PlanDetail
          group={selectedPlan}
          c={c}
          selectedForApproval={approvalPlan?.key === selectedPlan.key}
          onSelect={() => onPlanSelect({ key: selectedPlan.key, label: planTitle(selectedPlan.primary, c) })}
        />
      )}

      <section className="next-decision">
        <div>
          <span>Next step</span>
          <strong>
            {c.lifecycle !== 'live'
              ? 'This plan is historical; review the recorded outcome'
              : c.state === 'executing'
                ? 'Monitor execution and confirm the service result'
                : c.gate?.needsCustomer
                  ? 'Release the alternatives to the shipping line'
                  : c.gate?.blocks
                    ? `Get approval from ${c.gate.requiredRoleLabel}`
                    : c.approval?.handoff
                      ? `Hand the recommendation to ${c.approval.roleLabel}`
                      : 'Proceed with the recommended plan'}
          </strong>
        </div>
        <span className="text-[18px] text-accent-500" aria-hidden>→</span>
      </section>
    </div>
  );
}

function OutcomeFact({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <div className="outcome-fact">
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </div>
  );
}

function Outcome({ c, selectedPlanLabel }: { c: ConnectionVM; selectedPlanLabel: string | null }) {
  if (!c.outcome) {
    const executionPending = c.lifecycle === 'live' && (
      c.state === 'executing' || c.gate?.status === 'approved'
    );

    if (executionPending) {
      const chosen = c.options.find((option) => option.status === 'chosen') ?? null;
      const releasedPlan = selectedPlanLabel ?? (chosen ? planTitle(chosen, c) : 'Recovery plan');
      return (
        <section className="pending-outcome-panel execution-outcome-panel">
          <header>
            <span>Execution in progress</span>
            <h2>Waiting for the service outcome</h2>
            <p>The decision is complete and the plan has been released. No further approval is needed right now.</p>
          </header>
          <div className="execution-outcome-status">
            <div className="execution-outcome-bar" role="status" aria-label="Waiting for service confirmation">
              <span />
            </div>
            <div className="execution-outcome-steps">
              <article className="execution-step execution-step-complete">
                <span>✓</span>
                <div>
                  <strong>Decision captured</strong>
                  <small>{c.gate?.status === 'approved' ? 'Approved for execution' : 'No approval required'}</small>
                </div>
              </article>
              <article className="execution-step execution-step-active">
                <span>2</span>
                <div>
                  <strong>Plan in execution</strong>
                  <small>{releasedPlan}</small>
                </div>
              </article>
              <article className="execution-step">
                <span>3</span>
                <div>
                  <strong>Outcome pending</strong>
                  <small>Waiting for terminal service confirmation</small>
                </div>
              </article>
            </div>
          </div>
          <footer className="execution-outcome-note">
            <span>{c.boxes} boxes being monitored</span>
            <strong>Refreshes when the operational result is recorded</strong>
          </footer>
        </section>
      );
    }

    return (
      <section className="pending-outcome-panel">
        <header>
          <span>Awaiting operator decision</span>
          <h2>No outcome has been recorded yet</h2>
          <p>Approve, decline, or let the window close. The recorded outcome will replace these possible paths.</p>
        </header>
        <div className="outcome-paths">
          <article className="outcome-path outcome-path-good">
            <span>Approve</span>
            <strong>Execute the recommended plan</strong>
            <p>The selected movement is released and the connection continues toward service.</p>
          </article>
          <article className="outcome-path">
            <span>Decline</span>
            <strong>Do not book the recovery</strong>
            <p>Nothing is committed and the boxes move to the next available service.</p>
          </article>
          <article className="outcome-path">
            <span>No response</span>
            <strong>Window closes automatically</strong>
            <p>The plan is auto-declined and the lapse is recorded separately.</p>
          </article>
        </div>
      </section>
    );
  }

  const tone =
    c.outcome.tone === 'good'
      ? 'outcome-good'
      : c.outcome.tone === 'bad' || c.outcome.tone === 'fault'
        ? 'outcome-bad'
        : 'outcome-neutral';

  const chosen = c.options.find((option) => option.status === 'chosen') ?? null;
  const planWasExecuted = c.outcome.serviceSuccess === true || c.gate?.status === 'approved';
  const proposedPlan = selectedPlanLabel ?? (chosen ? planTitle(chosen, c) : null);
  const executedPlan = planWasExecuted
    ? proposedPlan ?? 'Executed plan was not recorded'
    : proposedPlan
      ? `Not executed · ${proposedPlan} was proposed`
      : 'No recovery plan was executed';
  const decision =
    c.gate?.status === 'approved'
      ? 'Approved'
      : c.gate?.status === 'rejected'
        ? 'Declined'
        : c.gate?.status === 'lapsed'
          ? 'Window lapsed'
          : c.outcome.customerGate
            ? 'Shipping line decision'
            : 'Recorded automatically';
  const owner = c.outcome.reachedTheLine
    ? 'Shipping line'
    : c.gate?.requiredRoleLabel ?? (c.outcome.agentFault ? 'System' : 'Terminal Operations');
  const cargoResult = c.outcome.serviceSuccess === true
    ? `${c.boxes} boxes served`
    : c.outcome.serviceSuccess === false
      ? `${c.boxes} boxes rolled`
      : `${c.boxes} boxes recorded`;
  const customerContact = c.outcome.reachedTheLine === true
    ? c.outcome.customerGate
      ? `Yes · ${c.outcome.customerGate.optionsSent} option${c.outcome.customerGate.optionsSent === 1 ? '' : 's'} sent`
      : 'Yes'
    : c.outcome.reachedTheLine === false
      ? 'No · resolved internally'
      : 'Not recorded';
  const metricStatus = c.outcome.excludedFromMetric === true
    ? 'Excluded'
    : c.outcome.excludedFromMetric === false
      ? 'Included'
      : 'Not recorded';

  return (
    <section className={`operator-outcome ${tone}`}>
      <header className="outcome-hero">
        <div>
          <span>{c.outcome.badge}</span>
          <h2>{c.outcome.label}</h2>
          <p className="outcome-what">{c.outcome.what}</p>
        </div>
        <span className="outcome-recorded-chip">Recorded outcome</span>
      </header>

      <div className="outcome-facts">
        <OutcomeFact
          label="Cargo result"
          value={cargoResult}
          detail={c.outcome.serviceSuccess === true ? 'Outbound service protected' : c.outcome.what}
        />
        <OutcomeFact label="Decision" value={decision} detail={`Owned by ${owner}`} />
        <OutcomeFact label="Customer contacted" value={customerContact} detail={c.outcome.reachedTheLine ? 'External decision path' : 'Internal decision path'} />
        <OutcomeFact label="Service metric" value={metricStatus} detail={c.outcome.why} />
      </div>

      <div className="outcome-detail-grid">
        <section>
          <h3>Execution record</h3>
          <dl>
            <div><dt>Plan</dt><dd>{executedPlan}</dd></div>
            <div><dt>Route</dt><dd>{c.inbound.terminalLabel} → {c.outbound.terminalLabel}</dd></div>
            <div><dt>Decision owner</dt><dd>{owner}</dd></div>
            <div><dt>Connection</dt><dd>{c.id}</dd></div>
          </dl>
        </section>
        <section>
          <h3>Operational follow-up</h3>
          <dl>
            <div><dt>Boxes</dt><dd>{c.boxes}</dd></div>
            <div><dt>Result</dt><dd>{c.outcome.what}</dd></div>
            <div><dt>Customer</dt><dd>{customerContact}</dd></div>
            <div><dt>Next action</dt><dd>{c.outcome.serviceSuccess ? 'Monitor final loading confirmation' : 'Rebook on the next available service'}</dd></div>
          </dl>
        </section>
      </div>

      {c.outcome.customerGate && (
        <div className="outcome-customer-record">
          <span>Shipping line window</span>
          <strong>
            {c.outcome.customerGate.optionsSent} option{c.outcome.customerGate.optionsSent === 1 ? '' : 's'} ·{' '}
            {c.outcome.customerGate.windowMin} minutes · {c.outcome.customerGate.outcome}
          </strong>
        </div>
      )}
    </section>
  );
}

export function ConnectionDetail({
  c,
  selectedPlanKey,
  selectedPlanLabel,
  onPlanSelect,
}: {
  c: ConnectionVM;
  selectedPlanKey: string | null;
  selectedPlanLabel: string | null;
  onPlanSelect: (selection: PlanSelection) => void;
}) {
  const [view, setView] = useState<View>('situation');
  const detailRef = useRef<HTMLDivElement>(null);

  useEffect(() => setView('situation'), [c.id]);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      const root = detailRef.current;
      const scroller = root?.closest<HTMLElement>('.detail-column');
      if (!root || !scroller) return;
      const behavior = window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth';

      if (window.getComputedStyle(scroller).overflowY !== 'visible') {
        scroller.scrollTo({ top: 0, behavior });
      } else {
        root.scrollIntoView({ block: 'start', behavior });
      }
    });

    return () => window.cancelAnimationFrame(frame);
  }, [view, c.id]);

  return (
    <div ref={detailRef} className="space-y-4" data-tour="connection-detail">
      <section className="connection-summary">
        <div className="flex flex-wrap items-center gap-3">
          <SeverityBadge label={c.severityLabel} big />
          <h1 className="font-mono text-[18px] font-semibold text-mist-100">{c.id}</h1>
          <StateBadge label={c.stateLabel} />
          <span className="ml-auto hidden font-mono text-[10px] text-mist-600 sm:inline">{c.ucid}</span>
        </div>
        <div className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Stat label="Boxes affected" value={c.boxes} hint="on this connection" />
          {c.lifecycle === 'live' ? (
            <>
              <Stat
                label="Current margin"
                value={signedHours(c.slack.currentPlanHours)}
                hint={`${pct(c.slack.consumedPct)} of the window used`}
                tone={c.slack.currentPlanHours < 0 ? 'bad' : 'good'}
              />
              <Stat
                label="Transfer effect"
                value={`+${c.slack.ittCostHours.toFixed(1)}h`}
                hint={c.crossesTerminals ? 'available if transfer is removed' : 'no transfer involved'}
                tone={c.rescuableByRemovingItt ? 'good' : 'default'}
              />
            </>
          ) : (
            <>
              <Stat
                label="Final status"
                value={c.outcome?.serviceSuccess === true ? 'Served' : c.outcome ? 'Not served' : c.stateLabel}
                hint={c.outcome?.label ?? c.stateNote ?? 'Connection closed'}
                tone={c.outcome?.serviceSuccess === true ? 'good' : c.outcome ? 'bad' : 'default'}
              />
              <Stat
                label="Decision path"
                value={c.outcome?.reachedTheLine ? 'Customer' : 'Internal'}
                hint={c.outcome?.reachedTheLine ? 'shipping line contacted' : 'resolved within operations'}
              />
            </>
          )}
          <Stat label="Detected" value={<span className="text-[14px]">{stamp(c.detectedAt)}</span>} hint="Singapore time" />
        </div>
      </section>

      <nav className="detail-tabs operator-detail-tabs" role="tablist" aria-label="Connection workflow" data-tour="connection-workflow">
        {([
          ['situation', 'Situation'],
          ['plans', 'Suggested plans'],
          ['outcome', 'Outcome'],
        ] as const).map(([id, label]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={view === id}
            onClick={() => setView(id)}
            className={`detail-tab ${view === id ? 'detail-tab-active' : ''}`}
          >
            {label}
          </button>
        ))}
      </nav>

      {view === 'situation' && <Situation c={c} />}
      {view === 'plans' && (
        <SuggestedPlans c={c} selectedPlanKey={selectedPlanKey} onPlanSelect={onPlanSelect} />
      )}
      {view === 'outcome' && <Outcome c={c} selectedPlanLabel={selectedPlanLabel} />}
    </div>
  );
}
