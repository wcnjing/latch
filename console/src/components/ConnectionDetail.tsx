/** Operator-facing connection workspace. Implementation evidence lives elsewhere. */

import { useEffect, useRef, useState } from 'react';

import type { ConnectionVM, OptionVM } from '../adapters/types';
import { hhmm, hoursAndMinutes, pct, signedHours, stamp } from '../lib/format';
import { Panel, SeverityBadge, Stat } from './ui';

type View = 'situation' | 'plans' | 'actions';

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
  const recordOnly = c.lifecycle !== 'live' || c.state === 'executing';

  return (
    <div className="placement-visual">
      <section className="placement-row">
        <header>
          <span>{recordOnly ? 'Arrangement at detection' : 'Current arrangement'}</span>
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
            <span>{recordOnly ? 'Placement considered' : 'Proposed placement'}</span>
            <small className="placement-recommended-label">{recordOnly ? 'Recorded' : 'Recommended'}</small>
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
              <small>{recordOnly ? 'Plan recorded at decision time' : 'Exact berth requires planner confirmation'}</small>
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

function Situation({ c }: { c: ConnectionVM }) {
  const historical = c.lifecycle !== 'live';
  const executing = c.state === 'executing' && !c.outcome;
  return (
    <div className="space-y-4">
      <section className={`situation-callout ${c.rescuableByRemovingItt ? 'situation-callout-actionable' : ''}`}>
        <div>
          <span className="text-[11px] font-medium text-mist-500">{historical ? 'Original risk' : executing ? 'Connection status' : 'What needs attention'}</span>
          <h2>
            {historical
              ? 'This connection is closed.'
              : executing
                ? 'The recovery plan is in progress.'
              : c.slack.currentPlanHours < 0
              ? `This connection misses its cut-off by ${hoursAndMinutes(c.slack.currentPlanHours).replace(' short', '')}.`
              : `This connection has ${hoursAndMinutes(c.slack.currentPlanHours)} of margin remaining.`}
          </h2>
          <p>
            {historical
              ? c.outcome?.what ?? c.stateNote ?? 'The captured risk is retained here for historical review.'
              : executing
                ? `${c.boxes} boxes are being monitored while operations confirms the service result.`
              : c.rescuableByRemovingItt
              ? `Keeping both vessels at one terminal restores ${c.slack.ittCostHours.toFixed(1)} hours and makes the connection viable.`
              : c.crossesTerminals
                ? 'The cargo crosses terminals, but removing that transfer alone does not fully recover the connection.'
                : 'Both vessels use the same terminal; the risk comes from vessel timing rather than a terminal transfer.'}
          </p>
        </div>
        {historical
          ? <span className="situation-tag situation-tag-closed">Closed</span>
          : executing
            ? <span className="situation-tag">In progress</span>
          : c.rescuableByRemovingItt && <span className="situation-tag">Recoverable</span>}
      </section>

      <Panel
        title={historical || executing ? 'Vessel placement record' : 'Vessel placement'}
        subtitle={historical || executing ? 'Arrangement and placement considered at decision time' : 'Current calls and proposed placement'}
      >
        <PlacementVisual c={c} />
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
          <h2>Plans</h2>
          <p>Compare the options, then select one for approval.</p>
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

    </div>
  );
}

type OperatorAction = { title: string; detail: string; owner: string };

function mailboxFor(contact: string): string {
  const normalised = contact.toLowerCase();
  if (normalised.includes('shipping line')) return 'duty.operations@carrier.example';
  if (normalised.includes('customer')) return 'customer.operations@terminal.example';
  if (normalised.includes('duty manager')) return 'duty.manager@terminal.example';
  if (normalised.includes('vessel planning')) return 'vessel.planning@terminal.example';
  if (normalised.includes('vessel operations')) return 'vessel.operations@terminal.example';
  if (normalised.includes('terminal operations')) {
    const terminal = normalised.replace('terminal operations', '').trim().replaceAll(' ', '.');
    return `${terminal || 'terminal'}.operations@terminal.example`;
  }
  return 'operations@terminal.example';
}

function Actions({
  c,
  selectedPlanKey,
  selectedPlanLabel,
  onOpenPlans,
}: {
  c: ConnectionVM;
  selectedPlanKey: string | null;
  selectedPlanLabel: string | null;
  onOpenPlans: () => void;
}) {
  const chosen = c.options.find((option) => option.status === 'chosen') ?? null;
  const planKey = selectedPlanKey ?? chosen?.rung.name ?? null;
  const planLabel = selectedPlanLabel ?? (chosen ? planTitle(chosen, c) : 'the selected recovery plan');
  const executionPending = c.lifecycle === 'live' && c.state === 'executing' && !c.outcome;
  const decisionNeeded = c.lifecycle === 'live' && c.approval?.actionable === true && c.gate?.status === 'awaiting';
  const successful = c.outcome?.serviceSuccess === true;
  const [copied, setCopied] = useState(false);

  let title: string;
  let summary: string;
  let contact: string;
  let where: string;
  let subject: string;
  let message: string;
  let actions: OperatorAction[];

  if (decisionNeeded) {
    const operationalContact = planKey === 'PREVENT'
      ? `${c.inbound.terminalLabel} berth planner`
      : planKey === 'OFFER'
        ? 'Shipping line duty contact'
        : 'Inter-terminal transfer desk';
    const operationalLocation = planKey === 'PREVENT'
      ? `${c.inbound.terminalLabel} vessel planning desk`
      : planKey === 'OFFER'
        ? 'Customer communications queue'
        : `${c.inbound.terminalLabel} transfer desk`;
    title = 'Choose, approve, and issue the plan';
    summary = `${c.boxes} boxes need an approved recovery instruction before the decision window closes.`;
    contact = c.gate?.requiredRoleLabel ?? 'Vessel Operations';
    where = 'Approval panel on this page';
    subject = `${c.id} — approval required for ${planLabel}`;
    actions = [
      {
        title: 'Choose the recovery plan',
        detail: 'Open Plans, compare the viable options, and select one for approval.',
        owner: 'You',
      },
      {
        title: 'Get the operational approval',
        detail: `Ask ${contact} to approve ${planLabel}.`,
        owner: contact,
      },
      {
        title: 'Issue the instruction',
        detail: `Send the approved plan to ${operationalContact} at the ${operationalLocation}.`,
        owner: operationalContact,
      },
    ];
    message = `${c.id} — approval requested for ${planLabel}. ${c.boxes} boxes connect from ${c.inbound.name} at ${c.inbound.terminalLabel} to ${c.outbound.name} at ${c.outbound.terminalLabel}. Current margin is ${signedHours(c.slack.currentPlanHours)}. Please confirm approval and operational capacity.`;
  } else if (executionPending) {
    title = 'Confirm the recovery is complete';
    summary = `${planLabel} is in progress. Follow the handoff through to terminal receipt and loading confirmation.`;
    contact = `${c.outbound.terminalLabel} Terminal Operations`;
    where = `${c.inbound.terminalLabel} → ${c.outbound.terminalLabel} operations channel`;
    subject = `${c.id} — confirm terminal receipt and loading status`;
    actions = [
      {
        title: 'Check the current movement',
        detail: `Confirm all ${c.boxes} boxes have left ${c.inbound.terminalLabel}.`,
        owner: `${c.inbound.terminalLabel} Terminal Operations`,
      },
      {
        title: 'Confirm terminal receipt',
        detail: `Ask ${c.outbound.terminalLabel} to confirm the boxes are received and staged.`,
        owner: contact,
      },
      {
        title: 'Record the loading result',
        detail: `Confirm whether the boxes loaded on ${c.outbound.name}, then close or rebook the connection.`,
        owner: 'Vessel Operations',
      },
    ];
    message = `${c.id} — status check for ${planLabel}. Please confirm movement and terminal receipt for ${c.boxes} boxes from ${c.inbound.terminalLabel} to ${c.outbound.terminalLabel}, and advise whether loading on ${c.outbound.name} remains on track.`;
  } else if (c.outcome) {
    title = successful ? 'Close the operational follow-up' : 'Rebook and notify the shipping line';
    summary = successful
      ? `${c.boxes} boxes were served. Confirm the final loading record and close the customer update.`
      : `${c.boxes} boxes were not served. Move them to the next available service and send the revised routing.`;
    contact = successful ? `${c.outbound.terminalLabel} Terminal Operations` : 'Shipping line service desk';
    where = successful ? `${c.outbound.terminalLabel} loading desk` : 'Customer booking queue';
    subject = successful
      ? `${c.id} — final loading confirmation`
      : `${c.id} — rebooking required for ${c.boxes} boxes`;
    actions = successful
      ? [
          {
            title: 'Confirm final loading',
            detail: `Check that all ${c.boxes} boxes are recorded against ${c.outbound.name}.`,
            owner: contact,
          },
          {
            title: 'Close the customer update',
            detail: 'Send the final service confirmation and close the connection record.',
            owner: 'Customer Operations',
          },
        ]
      : [
          {
            title: 'Find the next service',
            detail: `Rebook all ${c.boxes} boxes from ${c.outbound.terminalLabel}.`,
            owner: 'Shipping line service desk',
          },
          {
            title: 'Send the revised routing',
            detail: 'Share the new vessel, cut-off, and booking reference with terminal operations.',
            owner: 'Customer Operations',
          },
          {
            title: 'Update the connection record',
            detail: 'Attach the revised booking and close the rolled connection.',
            owner: 'Vessel Operations',
          },
        ];
    message = successful
      ? `${c.id} — please confirm final loading for all ${c.boxes} boxes on ${c.outbound.name} at ${c.outbound.terminalLabel}. Once confirmed, we will close the connection record.`
      : `${c.id} — ${c.boxes} boxes were not served on ${c.outbound.name}. Please confirm the next available onward service from ${c.outbound.terminalLabel} and return the revised vessel, cut-off, and booking reference.`;
  } else {
    title = 'Verify the connection before acting';
    summary = 'The latest operational state is incomplete. Confirm the vessel calls before issuing a recovery instruction.';
    contact = 'Vessel planning desk';
    where = `${c.inbound.terminalLabel} and ${c.outbound.terminalLabel} operations channels`;
    subject = `${c.id} — verify vessel call details`;
    actions = [
      {
        title: 'Verify both vessel calls',
        detail: `Confirm the latest estimates for ${c.inbound.name} and ${c.outbound.name}.`,
        owner: contact,
      },
      {
        title: 'Re-open only if the risk remains',
        detail: 'Create a new connection review with the confirmed terminal and timing data.',
        owner: 'Vessel Operations',
      },
    ];
    message = `${c.id} — please confirm the current terminal and estimated time for ${c.inbound.name} and ${c.outbound.name}. The connection record is incomplete and should not be acted on until both calls are verified.`;
  }
  const emailAddress = mailboxFor(contact);
  const emailBody = `Hello ${contact},\n\n${message}\n\nPlease reply with confirmation and any operational constraints.\n\nRegards,\nTerminal Operations`;
  const emailDraft = `To: ${emailAddress}\nSubject: ${subject}\n\n${emailBody}`;
  const mailto = `mailto:${emailAddress}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(emailBody)}`;

  const copyMessage = async () => {
    try {
      await navigator.clipboard.writeText(emailDraft);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      setCopied(false);
    }
  };

  return (
    <section className="action-workspace">
      <header className="action-hero">
        <div>
          <span>Operator actions</span>
          <h2>{title}</h2>
          <p>{summary}</p>
        </div>
        {decisionNeeded && (
          <button type="button" className="button-primary" onClick={onOpenPlans}>
            Review plans
          </button>
        )}
      </header>

      <div className="action-grid">
        <section className="action-checklist">
          <h3>Do this next</h3>
          <ol>
            {actions.map((action, index) => (
              <li key={action.title}>
                <span>{index + 1}</span>
                <div>
                  <strong>{action.title}</strong>
                  <p>{action.detail}</p>
                  <small>{action.owner}</small>
                </div>
              </li>
            ))}
          </ol>
        </section>

        <aside className="action-contact-card">
          <span>Who to contact</span>
          <strong>{contact}</strong>
          <a href={`mailto:${emailAddress}`}>{emailAddress}</a>
          <dl>
            <div>
              <dt>Where</dt>
              <dd>{where}</dd>
            </div>
            <div>
              <dt>Connection</dt>
              <dd>{c.id}</dd>
            </div>
          </dl>
        </aside>
      </div>

      <section className="action-message-card">
        <header>
          <div>
            <span>Email draft</span>
            <h3>Ready for review</h3>
          </div>
          <div className="action-message-actions">
            <button type="button" className="button-secondary" onClick={copyMessage}>
              {copied ? 'Copied' : 'Copy email'}
            </button>
            <a className="button-primary" href={mailto}>Open email</a>
          </div>
        </header>
        <dl className="action-email-fields">
          <div><dt>To</dt><dd>{emailAddress}</dd></div>
          <div><dt>Subject</dt><dd>{subject}</dd></div>
        </dl>
        <div className="action-email-body">{emailBody}</div>
      </section>
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
  const outcomePending = c.lifecycle === 'live' && c.state === 'executing' && !c.outcome;

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
          <SeverityBadge label={c.lifecycle === 'live' ? c.severityLabel : 'CLOSED'} big />
          <h1 className="font-mono text-[18px] font-semibold text-mist-100">{c.id}</h1>
        </div>
        <div className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-3">
          <Stat label="Boxes affected" value={c.boxes} hint="on this connection" />
          {!outcomePending && c.lifecycle === 'live' ? (
            <Stat
              label="Current margin"
              value={signedHours(c.slack.currentPlanHours)}
              hint={`${pct(c.slack.consumedPct)} of the window used`}
              tone={c.slack.currentPlanHours < 0 ? 'bad' : 'good'}
            />
          ) : c.lifecycle !== 'live' ? (
            <Stat
              label="Final status"
              value={c.outcome?.serviceSuccess === true ? 'Served' : c.outcome ? 'Not served' : c.stateLabel}
              hint={c.outcome?.label ?? c.stateNote ?? 'Connection closed'}
              tone={c.outcome?.serviceSuccess === true ? 'good' : c.outcome ? 'bad' : 'default'}
            />
          ) : null}
          <Stat label="Detected" value={<span className="text-[14px]">{stamp(c.detectedAt)}</span>} hint="Singapore time" />
        </div>
      </section>

      <nav className="detail-tabs operator-detail-tabs" role="tablist" aria-label="Connection workflow" data-tour="connection-workflow">
        {([
          ['situation', 'Situation'],
          ['plans', 'Plans'],
          ['actions', 'Actions'],
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
      {view === 'actions' && (
        <Actions
          c={c}
          selectedPlanKey={selectedPlanKey}
          selectedPlanLabel={selectedPlanLabel}
          onOpenPlans={() => setView('plans')}
        />
      )}
    </div>
  );
}
