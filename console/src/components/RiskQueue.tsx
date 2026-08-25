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
}: {
  c: ConnectionVM;
  selected: boolean;
  onSelect: () => void;
}) {
  const pressure = pressureFor(c);
  const decisionNeeded = needsDecision(c);
  const outcomePending = isPendingOutcome(c);
  const showTimePressure = c.lifecycle === 'live' && !outcomePending;
  const tone =
    c.lifecycle !== 'live'
      ? 'closed'
      : c.severity === 'AT_RISK'
        ? 'risk'
        : c.severity === 'WATCH'
          ? 'watch'
          : 'safe';

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
        <span className={`queue-card-state ${decisionNeeded ? 'queue-card-state-action' : ''}`}>
          {decisionNeeded ? 'Decision needed' : outcomePending ? 'In progress' : c.outcome ? 'Closed' : c.stateLabel}
        </span>
      </div>

      <div className="queue-card-impact">
        {c.lifecycle === 'live' ? (
          <>
            <strong>{c.boxes} boxes</strong>
            <span aria-hidden>·</span>
            <span className={c.slack.currentPlanHours < 0 ? 'queue-impact-late' : ''}>{pressureLabel(c)}</span>
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
            <span>Decision window</span>
            <span>{Math.round(pressure)}% used</span>
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
            <span>Waiting for service confirmation</span>
          </div>
          <div className="queue-outcome-track" role="status" aria-label="Waiting for operational outcome">
            <span />
          </div>
        </>
      )}

    </button>
  );
}

export function RiskQueue({
  connections,
  selectedId,
  onSelect,
}: {
  connections: ConnectionVM[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const [filter, setFilter] = useState<Filter>('open');
  const [query, setQuery] = useState('');
  const open = connections.filter((c) => c.lifecycle === 'live');
  const needsAction = open.filter(needsDecision);
  const pendingOutcome = open.filter(isPendingOutcome);
  const history = connections.filter((c) => c.lifecycle !== 'live');
  const selectedLifecycle = connections.find((c) => c.id === selectedId)?.lifecycle ?? null;
  const searching = query.trim().length > 0;

  useEffect(() => {
    if (selectedLifecycle && selectedLifecycle !== 'live') setFilter('history');
  }, [selectedId, selectedLifecycle]);

  const shown = useMemo(() => {
    const normalisedQuery = query.trim().toLowerCase();
    if (normalisedQuery) {
      return connections.filter((c) =>
        [c.id, c.inbound.name, c.outbound.name, c.inbound.terminalLabel, c.outbound.terminalLabel]
          .join(' ')
          .toLowerCase()
          .includes(normalisedQuery),
      );
    }
    const filtered =
      filter === 'action'
          ? needsAction
          : filter === 'pending'
            ? pendingOutcome
          : filter === 'history'
            ? history
            : open;
    return filtered;
  }, [connections, filter, history, needsAction, open, pendingOutcome, query]);

  const filters = [
    { id: 'open' as const, label: 'Open', count: open.length },
    { id: 'action' as const, label: 'Needs action', count: needsAction.length },
    { id: 'pending' as const, label: 'Pending', count: pendingOutcome.length },
    { id: 'history' as const, label: 'History', count: history.length },
  ];
  const queueTitle = searching
    ? 'Search results'
    : filter === 'history'
      ? 'Recent records'
      : filter === 'pending'
        ? 'In progress'
        : filter === 'action'
          ? 'Needs your decision'
          : 'Most urgent first';

  return (
    <section className="queue-shell" data-tour="connection-queue" aria-label="Connection queue">
      <header className="queue-header">
        <div className="queue-heading">
          <div>
            <h2>{queueTitle}</h2>
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
            placeholder="Search all connections"
            aria-label="Search connections"
          />
        </label>

        <div className="queue-filters" role="tablist" aria-label="Filter connections">
          {filters.map((item) => (
            <button
              key={item.id}
              type="button"
              role="tab"
              aria-selected={!searching && filter === item.id}
              onClick={() => {
                setQuery('');
                setFilter(item.id);
              }}
              className={`queue-filter ${!searching && filter === item.id ? 'queue-filter-active' : ''}`}
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
