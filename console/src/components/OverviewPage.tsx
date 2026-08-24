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

function Metric({
  label,
  value,
  detail,
  tone = 'default',
}: {
  label: string;
  value: string | number;
  detail: string;
  tone?: 'default' | 'risk' | 'good';
}) {
  return (
    <div className="overview-metric">
      <div className="text-[12px] text-mist-500">{label}</div>
      <div className="mt-2 flex items-baseline gap-2">
        <span className="tnum text-[30px] font-semibold tracking-[-0.035em] text-mist-100">
          {value}
        </span>
        <span
          className={`text-[10px] ${
            tone === 'risk' ? 'text-risk-500' : tone === 'good' ? 'text-safe-500' : 'text-mist-500'
          }`}
        >
          {detail}
        </span>
      </div>
    </div>
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
  const attention = live.filter(
    (c) => needsAction.some((item) => item.id === c.id) || pendingOutcome.some((item) => item.id === c.id),
  ).slice(0, 5);
  const recent = connections.filter((c) => c.outcome).slice(0, 6);
  const top = attention[0];

  return (
    <main className="overview-page">
      <header className="page-heading">
        <div>
          <p className="page-kicker">PSA Singapore · Scenario workspace</p>
          <h1>Overview</h1>
          <p>Start with the connections that need an operator, then drill into the plan and decision.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {top && (
            <button type="button" className="button-secondary" onClick={() => onOpen(top.id)}>
              Review top priority
            </button>
          )}
          <button type="button" className="button-primary" onClick={onViewConnections}>
            View connections
          </button>
        </div>
      </header>

      <section className="overview-metrics" aria-label="Workspace summary">
        <Metric label="Needs action" value={needsAction.length} detail="operator decisions" tone="risk" />
        <Metric label="Pending outcome" value={pendingOutcome.length} detail="plans in execution" />
        <Metric label="Open" value={live.length} detail="active connections" />
        <Metric label="Served" value={served.length} detail="recorded outcomes" tone="good" />
      </section>

      {/* These four are counts over the captured fixtures. In a row styled like
          a metrics row they can read as measured results, and "Served 2" in
          particular reads as a claim about performance. It is not one: no
          evaluation has been run. Marking the absence is the honest move —
          reserving a slot for a number we do not have would imply we expect to
          fill it with a favourable one. */}
      <p className="metrics-provenance">
        <span className="metrics-provenance-flag">Pending evaluation</span>
        <span>
          Counts above describe the captured scenario fixtures, not measured performance.
          Detection rate and connections rescued are not shown because workstream A's
          historical evaluation has not run.
        </span>
      </p>

      <div className="overview-grid">
        <section className="product-panel attention-panel" data-tour="attention-queue">
          <header className="product-panel-header">
            <div>
              <h2>Open work</h2>
              <p>Decisions first, then connections awaiting an outcome.</p>
            </div>
            <button type="button" className="text-action" onClick={onViewConnections}>
              View all
            </button>
          </header>

          <div className="attention-table-header" aria-hidden>
            <span>Connection</span>
            <span>Exposure</span>
            <span>Margin</span>
            <span>Best next move</span>
            <span />
          </div>
          <div>
            {attention.map((c) => (
              <button key={c.id} type="button" className="attention-row" onClick={() => onOpen(c.id)}>
                <span className="min-w-0">
                  <span className="flex items-center gap-2">
                    <SeverityBadge label={c.severityLabel} />
                    <strong className="truncate font-mono text-[12px] text-mist-100">{c.id}</strong>
                  </span>
                  <span className="mt-1 block text-[10px] text-mist-500">
                    {c.lifecycle === 'live' && c.approval?.actionable && c.gate?.status === 'awaiting'
                      ? 'Decision required'
                      : 'Outcome pending'}
                  </span>
                </span>
                <span>
                  <strong className="tnum block text-[12px] text-mist-100">{c.boxes} boxes</strong>
                  <span className="text-[10px] text-mist-500">affected cargo</span>
                </span>
                <span className={`tnum text-[12px] font-semibold ${c.slack.currentPlanHours < 0 ? 'text-risk-500' : 'text-safe-500'}`}>
                  {signedHours(c.slack.currentPlanHours)}
                </span>
                <span className="text-[11px] leading-snug text-mist-400">
                  {c.approval?.actionable && c.gate?.status === 'awaiting'
                    ? c.rescuableByRemovingItt
                    ? `Remove transfer · restore ${c.slack.ittCostHours.toFixed(1)}h`
                      : c.triage.routeLabel
                    : 'Monitor execution · confirm service result'}
                </span>
                <span className="text-right text-[16px] text-accent-500" aria-hidden>›</span>
              </button>
            ))}
            {attention.length === 0 && (
              <div className="attention-clear-state">
                <span aria-hidden>✓</span>
                <div>
                  <strong>All caught up</strong>
                  <p>There are no open decisions or pending outcomes.</p>
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
                <p>Latest captured resolutions.</p>
              </div>
            </header>
            <div className="recent-list">
              {recent.map((c) => (
                <button key={c.id} type="button" onClick={() => onOpen(c.id)}>
                  <span className={`h-2 w-2 shrink-0 rounded-full ${OUTCOME_DOT[c.outcome!.tone]}`} />
                  <span className="min-w-0 flex-1 text-left">
                    <span className="block truncate font-mono text-[11px] text-mist-100">{c.id}</span>
                    <span className="mt-0.5 block truncate text-[10px] text-mist-500">{c.outcome!.label}</span>
                  </span>
                  <StateBadge label={c.stateLabel} />
                </button>
              ))}
            </div>
          </section>

          <section className="workspace-note">
            <strong>About this workspace</strong>
            <p>
              Vessel movement and derived arrival estimates use real source data. Connections,
              terminal assignments, cut-offs, and model responses are captured scenario fixtures.
            </p>
          </section>
        </aside>
      </div>
    </main>
  );
}
