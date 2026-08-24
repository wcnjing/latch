import { useEffect, useMemo, useState } from 'react';

import type { ConnectionVM } from '../adapters/types';
import { hoursAndMinutes } from '../lib/format';

type Filter = 'open' | 'action' | 'pending' | 'history';

function needsDecision(c: ConnectionVM) {
  return c.lifecycle === 'live' && c.approval?.actionable === true && c.gate?.status === 'awaiting';
}

function isPendingOutcome(c: ConnectionVM) {
  return c.lifecycle === 'live' && !c.outcome && !needsDecision(c);
}

function pressureFor(c: ConnectionVM) {
  if (c.slack.currentPlanHours < 0) {
    return Math.min(100, 58 + Math.abs(c.slack.currentPlanHours) * 14);
  }
  return Math.max(10, 54 - c.slack.currentPlanHours * 4.5);
}

function pressureLabel(c: ConnectionVM) {
  if (c.slack.currentPlanHours < 0) {
    return `${hoursAndMinutes(c.slack.currentPlanHours).replace(' short', '')} late`;
  }
  return `${hoursAndMinutes(c.slack.currentPlanHours)} margin`;
}

function Row({
  c,
  selected,
  onSelect,
  replaying,
}: {
  c: ConnectionVM;
  selected: boolean;
  onSelect: () => void;
  replaying: boolean;
}) {
  const pressure = pressureFor(c);
  const decisionNeeded = needsDecision(c);
  const outcomePending = isPendingOutcome(c);
  const showTimePressure = c.lifecycle === 'live' && !outcomePending;
  const tone =
    c.severity === 'AT_RISK' ? 'risk' : c.severity === 'WATCH' ? 'watch' : 'safe';

  return (
    <button
      type="button"
      onClick={onSelect}
      className={`queue-card queue-card-${tone} ${selected ? 'queue-card-selected' : ''}`}
      aria-label={`${c.id}, ${c.lifecycle === 'live' ? pressureLabel(c) : c.stateLabel}, ${c.boxes} boxes`}
    >
      <div className="queue-card-topline">
        <span className={`queue-status-dot queue-status-dot-${tone}`} aria-hidden />
        <strong className="queue-card-id">{c.id}</strong>
        {replaying && <span className="queue-live-badge">Live</span>}
        <span className={`queue-card-state ${decisionNeeded || outcomePending ? 'queue-card-state-action' : ''}`}>
          {decisionNeeded ? 'Decision needed' : outcomePending ? 'Outcome pending' : c.stateLabel}
        </span>
      </div>

      <div className="queue-card-impact">
        {c.lifecycle === 'live' ? (
          <>
            <strong className={c.slack.currentPlanHours < 0 ? 'queue-impact-late' : ''}>
              {pressureLabel(c)}
            </strong>
            <span aria-hidden>·</span>
            <span>{c.boxes} boxes</span>
          </>
        ) : (
          <>
            <strong>{c.boxes} boxes</strong>
            <span aria-hidden>·</span>
            <span className="truncate">{c.outcome?.label ?? c.stateLabel}</span>
          </>
        )}
      </div>

      {showTimePressure && (
        <>
          <div className="queue-pressure-heading">
            <span>Time pressure</span>
            <span>{Math.round(pressure)}%</span>
          </div>
          <div
            className="queue-pressure-track"
            role="progressbar"
            aria-label="Connection time pressure"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(pressure)}
          >
            <span className={`queue-pressure-fill queue-pressure-fill-${tone}`} style={{ width: `${pressure}%` }} />
          </div>
        </>
      )}

      {outcomePending && (
        <>
          <div className="queue-pressure-heading">
            <span>Operational status</span>
            <span>In progress</span>
          </div>
          <div className="queue-outcome-track" role="status" aria-label="Waiting for operational outcome">
            <span />
          </div>
        </>
      )}

      <div className="queue-card-footline">
        {decisionNeeded ? (
          <>
            <span className="queue-action-badge">Action required</span>
            <span>Review and decide on the recommended plan</span>
          </>
        ) : outcomePending ? (
          <>
            <span className="queue-pending-badge">Pending outcome</span>
            <span>Plan released · awaiting service confirmation</span>
          </>
        ) : c.outcome ? (
          <>
            <span className="queue-recorded-badge">Recorded</span>
            <span className="truncate">{c.outcome.label}</span>
          </>
        ) : c.lifecycle === 'live' && c.rescuableByRemovingItt ? (
          <>
            <span className="queue-recovery-badge">Recoverable</span>
            <span>Removing the transfer restores {c.slack.ittCostHours.toFixed(1)}h</span>
          </>
        ) : (
          <span>{c.stateNote ?? 'Review the suggested plans'}</span>
        )}
      </div>
    </button>
  );
}

export function RiskQueue({
  connections,
  selectedId,
  onSelect,
  replayingId,
}: {
  connections: ConnectionVM[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  replayingId: string | null;
}) {
  const [filter, setFilter] = useState<Filter>('open');
  const [query, setQuery] = useState('');
  const open = connections.filter((c) => c.lifecycle === 'live');
  const needsAction = open.filter(needsDecision);
  const pendingOutcome = open.filter(isPendingOutcome);
  const history = connections.filter((c) => c.lifecycle !== 'live');

  useEffect(() => {
    const selected = connections.find((c) => c.id === selectedId);
    if (selected?.lifecycle !== 'live') setFilter('history');
  }, [connections, selectedId]);

  const shown = useMemo(() => {
    const filtered =
      filter === 'action'
          ? needsAction
          : filter === 'pending'
            ? pendingOutcome
          : filter === 'history'
            ? history
            : open;
    const normalisedQuery = query.trim().toLowerCase();
    if (!normalisedQuery) return filtered;
    return filtered.filter((c) =>
      [c.id, c.inbound.name, c.outbound.name, c.inbound.terminalLabel, c.outbound.terminalLabel]
        .join(' ')
        .toLowerCase()
        .includes(normalisedQuery),
    );
  }, [filter, history, needsAction, open, pendingOutcome, query]);

  const filters = [
    { id: 'open' as const, label: 'Open', count: open.length },
    { id: 'action' as const, label: 'Needs action', count: needsAction.length },
    { id: 'pending' as const, label: 'Pending', count: pendingOutcome.length },
    { id: 'history' as const, label: 'History', count: history.length },
  ];

  return (
    <section className="queue-shell" data-tour="connection-queue" aria-label="Connection queue">
      <header className="queue-header">
        <div className="queue-heading">
          <div>
            <h2>Connections</h2>
            <p>Sorted by urgency</p>
          </div>
          <span>{shown.length} shown</span>
        </div>

        <label className="queue-search">
          <svg viewBox="0 0 20 20" width="14" height="14" aria-hidden>
            <circle cx="8.5" cy="8.5" r="4.5" fill="none" stroke="currentColor" strokeWidth="1.6" />
            <path d="m12 12 4 4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          </svg>
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search connections"
            aria-label="Search connections"
          />
        </label>

        <div className="queue-filters" role="tablist" aria-label="Filter connections">
          {filters.map((item) => (
            <button
              key={item.id}
              type="button"
              role="tab"
              aria-selected={filter === item.id}
              onClick={() => setFilter(item.id)}
              className={`queue-filter ${filter === item.id ? 'queue-filter-active' : ''}`}
            >
              <span>{item.label}</span>
              <span className="queue-filter-count">{item.count}</span>
            </button>
          ))}
        </div>
      </header>

      <div className="queue-list">
        {shown.map((c) => (
          <Row
            key={c.id}
            c={c}
            selected={c.id === selectedId}
            onSelect={() => onSelect(c.id)}
            replaying={c.id === replayingId}
          />
        ))}
        {shown.length === 0 && (
          <div className="queue-empty">
            <strong>No matching connections</strong>
            <span>Try another search or filter.</span>
          </div>
        )}
      </div>
    </section>
  );
}
