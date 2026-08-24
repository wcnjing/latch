import type { ConnectionVM, OutcomeTone } from '../adapters/types';
import { signedHours } from '../lib/format';
import { SeverityBadge, StateBadge } from './ui';

const OUTCOME_DOT: Record<OutcomeTone, string> = {
  good: 'bg-safe-500',
  bad: 'bg-risk-500',
  fault: 'bg-risk-500',
  neutral: 'bg-mist-500',
  gap: 'bg-mist-600',
};

const COUNT_WORD = ['No', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine'];

/** "Three" up to nine, then the numeral. Reads as a sentence, not a stat. */
function spell(n: number): string {
  return COUNT_WORD[n] ?? String(n);
}

/**
 * Why this connection is in trouble, composed only from fields the trace
 * actually carries.
 *
 * Every clause is guarded. A sentence assembled from optional data is exactly
 * where a console starts asserting things nobody recorded, and this is the
 * most prominent sentence on the landing screen.
 */
function whyAtRisk(c: ConnectionVM): string {
  const parts: string[] = [];
  const late = Math.round(c.inbound.deviationMin);

  if (late > 0) {
    parts.push(`Inbound ${c.inbound.name} is ${late} min late`);
  } else if (late < 0) {
    parts.push(`Inbound ${c.inbound.name} is ${Math.abs(late)} min early`);
  } else {
    parts.push(`Inbound ${c.inbound.name} is on schedule`);
  }

  if (c.crossesTerminals && c.rescuableByRemovingItt) {
    parts.push('and the inter-terminal transfer no longer fits inside the window');
  } else if (c.crossesTerminals) {
    parts.push(`and the boxes still have to cross from ${c.inbound.terminalLabel} to ${c.outbound.terminalLabel}`);
  } else {
    parts.push('and the connection window has closed too far to absorb it');
  }

  return `${parts.join(' ')}.`;
}

/**
 * The single case the screen is about.
 *
 * The previous landing opened on four counts over the captured fixtures. They
 * measured 61 of 63 on-screen lines saying nothing about shipping, and needed
 * a disclaimer underneath to stop "Served 2" reading as a performance claim.
 * Counts are navigation, not a headline — they moved below this card, next to
 * the queue they index, with the provenance note attached to them there.
 */
function HeadlineCase({ c, onOpen }: { c: ConnectionVM; onOpen: (id: string) => void }) {
  const awaitingDecision = c.approval?.actionable === true && c.gate?.status === 'awaiting';

  return (
    <section className="headline-case" data-tour="attention-queue">
      {/* One group, wrapping. Pinned to opposite edges the approval chip ended
          up a thousand pixels from the connection it refers to on a wide
          screen. */}
      <header className="headline-case-header">
        <SeverityBadge label={c.severityLabel} />
        <strong className="font-mono text-[13px] text-mist-100">{c.id}</strong>
        <span className="headline-case-route">
          {c.inbound.terminalLabel} → {c.outbound.terminalLabel}
        </span>
        {awaitingDecision && c.gate && (
          <span className="headline-case-gate">{c.gate.requiredRoleLabel} must approve</span>
        )}
      </header>

      <p className="headline-case-why">{whyAtRisk(c)}</p>

      <div className="headline-case-facts">
        <div>
          <span className="headline-fact-label">Cargo exposed</span>
          <strong className="tnum">{c.boxes} boxes</strong>
        </div>
        <div>
          <span className="headline-fact-label">Margin now</span>
          <strong className={`tnum ${c.slack.currentPlanHours < 0 ? 'text-risk-500' : 'text-safe-500'}`}>
            {signedHours(c.slack.currentPlanHours)}
          </strong>
        </div>
        <div>
          <span className="headline-fact-label">Without the transfer</span>
          <strong className="tnum text-safe-500">{signedHours(c.slack.noIttHours)}</strong>
        </div>
      </div>

      {/* The escalation sentence is the product in one line: nobody lowered the
          confidence, and the gate moved the decision to a named human on its
          own. It belongs on the landing screen, not three clicks in. */}
      {c.gate?.escalation && c.confidence && (
        <p className="headline-case-escalation">
          Confidence landed at <strong className="tnum">{c.confidence.value.toFixed(2)}</strong>, so
          the agent could not act alone — it escalated from{' '}
          <em>{c.gate.escalation.wouldHaveBeenLabel}</em> to{' '}
          <strong>{c.gate.escalation.becameLabel}</strong>.
        </p>
      )}

      <button type="button" className="button-primary headline-case-action" onClick={() => onOpen(c.id)}>
        Review this connection
      </button>
    </section>
  );
}

export function OverviewPage({
  connections,
  onOpen,
  onViewConnections,
}: {
  connections: ConnectionVM[];
  onOpen: (id: string) => void;
  onViewConnections: () => void;
}) {
  const live = connections.filter((c) => c.lifecycle === 'live');
  const needsAction = live.filter(
    (c) => c.approval?.actionable === true && c.gate?.status === 'awaiting',
  );
  const pendingOutcome = live.filter(
    (c) => !c.outcome && !needsAction.some((item) => item.id === c.id),
  );
  const served = connections.filter((c) => c.outcome?.serviceSuccess === true);
  const recent = connections.filter((c) => c.outcome).slice(0, 5);

  // The decision that cannot wait outranks work that is merely in flight.
  const headline = needsAction[0] ?? pendingOutcome[0] ?? null;
  const rest = live.filter((c) => c.id !== headline?.id);

  return (
    <main className="overview-page">
      <header className="landing-heading">
        <p className="landing-eyebrow">LATCH · Look-Ahead Transhipment Connection Handler</p>
        <h1>
          {spell(live.length)} connection{live.length === 1 ? '' : 's'}{' '}
          {live.length === 1 ? 'is' : 'are'} losing the slack {live.length === 1 ? 'it needs' : 'they need'}{' '}
          to make {live.length === 1 ? 'its' : 'their'} outbound ship.
        </h1>
        {needsAction.length > 0 ? (
          <p className="landing-sub">
            {spell(needsAction.length)} need{needsAction.length === 1 ? 's' : ''} a decision from you
            now. The rest are running.
          </p>
        ) : (
          <p className="landing-sub">
            None is waiting on a decision. {spell(pendingOutcome.length)}{' '}
            {pendingOutcome.length === 1 ? 'is' : 'are'} executing a released plan.
          </p>
        )}
      </header>

      {headline ? (
        <HeadlineCase c={headline} onOpen={onOpen} />
      ) : (
        <section className="headline-case headline-case-clear">
          <strong>Nothing is at risk right now.</strong>
          <p>Every captured connection has reached an outcome.</p>
          <button type="button" className="button-secondary" onClick={onViewConnections}>
            Browse connections
          </button>
        </section>
      )}

      <div className="landing-grid">
        <section className="product-panel" data-tour="connection-shortlist">
          <header className="product-panel-header">
            <div>
              <h2>Also open</h2>
              <p>Plans released and running, with no outcome recorded yet.</p>
            </div>
            <button type="button" className="text-action" onClick={onViewConnections}>
              View all {connections.length}
            </button>
          </header>

          <div>
            {rest.map((c) => (
              <button key={c.id} type="button" className="attention-row" onClick={() => onOpen(c.id)}>
                <span className="min-w-0">
                  <span className="flex items-center gap-2">
                    <SeverityBadge label={c.severityLabel} />
                    <strong className="truncate font-mono text-[12px] text-mist-100">{c.id}</strong>
                  </span>
                  <span className="mt-1 block text-[10px] text-mist-500">
                    {c.approval?.actionable && c.gate?.status === 'awaiting'
                      ? 'Decision required'
                      : 'Running · outcome pending'}
                  </span>
                </span>
                <span>
                  <strong className="tnum block text-[12px] text-mist-100">{c.boxes} boxes</strong>
                  <span className="text-[10px] text-mist-500">affected cargo</span>
                </span>
                <span
                  className={`tnum text-[12px] font-semibold ${
                    c.slack.currentPlanHours < 0 ? 'text-risk-500' : 'text-safe-500'
                  }`}
                >
                  {signedHours(c.slack.currentPlanHours)}
                </span>
                <span className="text-[11px] leading-snug text-mist-400">
                  {c.rescuableByRemovingItt
                    ? `Transfer is the constraint · ${c.slack.ittCostHours.toFixed(1)}h`
                    : c.triage.routeLabel}
                </span>
                <span className="text-right text-[16px] text-accent-500" aria-hidden>
                  ›
                </span>
              </button>
            ))}
            {rest.length === 0 && (
              <div className="attention-clear-state">
                <span aria-hidden>✓</span>
                <div>
                  <strong>Nothing else open</strong>
                  <p>No other connection is currently in flight.</p>
                </div>
              </div>
            )}
          </div>
        </section>

        <aside className="space-y-3">
          <section className="product-panel">
            <header className="product-panel-header">
              <div>
                <h2>Recent outcomes</h2>
                <p>How the last connections ended.</p>
              </div>
            </header>
            <div className="recent-list">
              {recent.map((c) => (
                <button key={c.id} type="button" onClick={() => onOpen(c.id)}>
                  <span className={`h-2 w-2 shrink-0 rounded-full ${OUTCOME_DOT[c.outcome!.tone]}`} />
                  <span className="min-w-0 flex-1 text-left">
                    <span className="block truncate font-mono text-[11px] text-mist-100">{c.id}</span>
                    <span className="mt-0.5 block truncate text-[10px] text-mist-500">
                      {c.outcome!.label}
                    </span>
                  </span>
                  <StateBadge label={c.stateLabel} />
                </button>
              ))}
            </div>
          </section>

          {/* The counts, demoted to what they are: an index of the queue. They
              led the page before, at a size that made four small integers read
              as measured results — which is why they needed a disclaimer to
              undo. The note stays, attached to the thing it qualifies. */}
          <section className="tally-panel">
            <div className="tally-row">
              <span>Awaiting a decision</span>
              <strong className="tnum text-risk-500">{needsAction.length}</strong>
            </div>
            <div className="tally-row">
              <span>Running</span>
              <strong className="tnum">{pendingOutcome.length}</strong>
            </div>
            <div className="tally-row">
              <span>Customer held a live decision</span>
              <strong className="tnum text-safe-500">{served.length}</strong>
            </div>
            <p className="tally-note">
              <span className="metrics-provenance-flag">Pending evaluation</span>
              Counts over the captured scenario fixtures, not measured performance. Detection rate
              and connections rescued are not shown because workstream A's historical evaluation has
              not run.
            </p>
          </section>
        </aside>
      </div>
    </main>
  );
}
