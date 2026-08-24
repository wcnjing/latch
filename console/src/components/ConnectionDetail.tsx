/** Operator-facing connection workspace. Implementation evidence lives elsewhere. */

import { useEffect, useState } from 'react';

import type { ConnectionVM, OptionVM } from '../adapters/types';
import { hhmm, hoursAndMinutes, pct, signedHours, stamp } from '../lib/format';
import { Panel, SeverityBadge, StateBadge, Stat } from './ui';

type View = 'situation' | 'plans' | 'outcome';

function Leg({ leg, role }: { leg: ConnectionVM['inbound']; role: 'Inbound' | 'Outbound' }) {
  const late = leg.deviationMin > 0;
  return (
    <div className="operator-leg">
      <div className="text-[10px] text-mist-500">{role}</div>
      <div className="mt-1 truncate text-[14px] font-semibold text-mist-100" title={leg.name}>
        {leg.name}
      </div>
      <div className="mt-0.5 text-[11px] text-mist-500">{leg.terminalLabel}</div>
      <div className="mt-4 grid grid-cols-2 gap-3">
        <div>
          <div className="text-[10px] text-mist-500">Planned</div>
          <div className="tnum mt-1 text-[12px] text-mist-300">{hhmm(leg.scheduled)}</div>
        </div>
        <div>
          <div className="text-[10px] text-mist-500">Expected</div>
          <div className={`tnum mt-1 text-[12px] font-medium ${late ? 'text-risk-500' : 'text-mist-300'}`}>
            {hhmm(leg.estimated)}
          </div>
        </div>
      </div>
      {leg.deviationMin !== 0 && (
        <div className={`tnum mt-3 text-[11px] ${late ? 'text-risk-500' : 'text-safe-500'}`}>
          {late ? '+' : '−'}{Math.abs(leg.deviationMin)} minutes {late ? 'late' : 'early'}
        </div>
      )}
    </div>
  );
}

function MarginComparison({ c }: { c: ConnectionVM }) {
  return (
    <div className="margin-comparison">
      <div className="margin-option margin-option-current">
        <span>Current plan</span>
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
  return (
    <div className="space-y-4">
      <section className={`situation-callout ${c.rescuableByRemovingItt ? 'situation-callout-actionable' : ''}`}>
        <div>
          <span className="text-[11px] font-medium text-mist-500">What needs attention</span>
          <h2>
            {c.slack.currentPlanHours < 0
              ? `This connection misses its cut-off by ${hoursAndMinutes(c.slack.currentPlanHours).replace(' short', '')}.`
              : `This connection has ${hoursAndMinutes(c.slack.currentPlanHours)} of margin remaining.`}
          </h2>
          <p>
            {c.rescuableByRemovingItt
              ? `Keeping both vessels at one terminal restores ${c.slack.ittCostHours.toFixed(1)} hours and makes the connection viable.`
              : c.crossesTerminals
                ? 'The cargo crosses terminals, but removing that transfer alone does not fully recover the connection.'
                : 'Both vessels use the same terminal; the risk comes from vessel timing rather than a terminal transfer.'}
          </p>
        </div>
        {c.rescuableByRemovingItt && <span className="situation-tag">Recoverable</span>}
      </section>

      <Panel title="Vessel timing" subtitle="Planned schedule compared with the latest arrival estimate">
        <div className="vessel-route">
          <Leg leg={c.inbound} role="Inbound" />
          <div className="route-transfer" aria-label={c.crossesTerminals ? 'Terminal transfer required' : 'Same terminal'}>
            <span>→</span>
            <small>{c.crossesTerminals ? 'Terminal transfer' : 'Same terminal'}</small>
          </div>
          <Leg leg={c.outbound} role="Outbound" />
        </div>
      </Panel>

      <Panel title="Connection margin" subtitle="The operational effect of removing the terminal transfer">
        <MarginComparison c={c} />
      </Panel>

      <Panel title="Why this connection is at risk">
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

const PLAN_TITLE: Record<string, string> = {
  PREVENT: 'Keep both vessels at one terminal',
  MOVE: 'Book the terminal transfer',
  OFFER: 'Offer alternatives to the shipping line',
};

function planEffect(option: OptionVM, c: ConnectionVM) {
  if (option.rung.name === 'PREVENT') return `Restores ${c.slack.ittCostHours.toFixed(1)} hours of margin`;
  if (option.rung.name === 'MOVE') return 'Keeps the existing vessel and terminal plan moving';
  if (option.rung.name === 'OFFER') return 'Lets the shipping line choose its preferred alternative';
  return 'Provides another way to protect the connection';
}

function planDescription(option: OptionVM) {
  if (option.rung.name === 'PREVENT') {
    return 'Coordinate a berth change so the inbound and outbound vessels use the same terminal.';
  }
  if (option.rung.name === 'MOVE') {
    return option.detail || 'Reserve the next available transfer movement between terminals.';
  }
  if (option.rung.name === 'OFFER') {
    return option.detail || 'Share the available onward services and let the shipping line choose.';
  }
  return option.detail || option.rung.does;
}

function SuggestedPlans({ c }: { c: ConnectionVM }) {
  const plans = c.options
    .filter((option) => option.status !== 'ruled_out')
    .sort((a, b) => (a.status === 'chosen' ? -1 : b.status === 'chosen' ? 1 : 0))
    .slice(0, 3);

  return (
    <div className="space-y-4">
      <section className="plan-intro">
        <div>
          <h2>Suggested recovery plans</h2>
          <p>Practical options are shown in recommended order. Technical scoring is intentionally hidden.</p>
        </div>
        <span>{plans.length} option{plans.length === 1 ? '' : 's'}</span>
      </section>

      {plans.length > 0 ? (
        <div className="suggested-plans">
          {plans.map((option, index) => {
            const recommended = option.status === 'chosen' || (index === 0 && !plans.some((p) => p.status === 'chosen'));
            return (
              <article key={option.id} className={`suggested-plan ${recommended ? 'suggested-plan-recommended' : ''}`}>
                <header>
                  <span className="plan-number">{index + 1}</span>
                  <div>
                    <h3>{PLAN_TITLE[option.rung.name] ?? option.rung.does}</h3>
                    <p>{planEffect(option, c)}</p>
                  </div>
                  <span className={recommended ? 'plan-label-recommended' : 'plan-label'}>
                    {recommended ? 'Recommended' : option.status === 'advisory' ? 'Planner action' : 'Alternative'}
                  </span>
                </header>
                <div className="plan-description">
                  <p>{planDescription(option)}</p>
                </div>
              </article>
            );
          })}
        </div>
      ) : (
        <section className="empty-operator-state">
          <h3>No recovery plan was produced</h3>
          <p>This connection needs manual review by terminal operations.</p>
        </section>
      )}

      <section className="next-decision">
        <div>
          <span>Next step</span>
          <strong>
            {c.gate?.needsCustomer
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

function Outcome({ c }: { c: ConnectionVM }) {
  if (!c.outcome) {
    return (
      <section className="empty-operator-state">
        <h2>Outcome pending</h2>
        <p>Complete the required decision to create the operational record.</p>
      </section>
    );
  }

  const tone =
    c.outcome.tone === 'good'
      ? 'outcome-good'
      : c.outcome.tone === 'bad' || c.outcome.tone === 'fault'
        ? 'outcome-bad'
        : 'outcome-neutral';

  return (
    <section className={`operator-outcome ${tone}`}>
      <span>{c.outcome.badge}</span>
      <h2>{c.outcome.label}</h2>
      <p className="outcome-what">{c.outcome.what}</p>
      <p>{c.outcome.why}</p>
      {c.outcome.excludedFromMetric && <small>This outcome is excluded from the service metric.</small>}
    </section>
  );
}

export function ConnectionDetail({ c }: { c: ConnectionVM }) {
  const [view, setView] = useState<View>('situation');

  useEffect(() => setView('situation'), [c.id]);

  return (
    <div className="space-y-4" data-tour="connection-detail">
      <section className="connection-summary">
        <div className="flex flex-wrap items-center gap-3">
          <SeverityBadge label={c.severityLabel} big />
          <h1 className="font-mono text-[18px] font-semibold text-mist-100">{c.id}</h1>
          <StateBadge label={c.stateLabel} />
          <span className="ml-auto hidden font-mono text-[10px] text-mist-600 sm:inline">{c.ucid}</span>
        </div>
        <div className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Stat label="Boxes affected" value={c.boxes} hint="on this connection" />
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
          <Stat label="Detected" value={<span className="text-[14px]">{stamp(c.detectedAt)}</span>} hint="Singapore time" />
        </div>
      </section>

      <nav className="detail-tabs operator-detail-tabs" role="tablist" aria-label="Connection workflow">
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
      {view === 'plans' && <SuggestedPlans c={c} />}
      {view === 'outcome' && <Outcome c={c} />}
    </div>
  );
}
