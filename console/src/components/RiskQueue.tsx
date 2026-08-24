import { useMemo, useState } from 'react';

import type { ConnectionVM } from '../adapters/types';
import { hoursAndMinutes } from '../lib/format';

type Filter = 'all' | 'live' | 'risk' | 'rescuable';

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
  const tone =
    c.severity === 'AT_RISK' ? 'risk' : c.severity === 'WATCH' ? 'watch' : 'safe';

  return (
    <button
      type="button"
      onClick={onSelect}
      className={`queue-card queue-card-${tone} ${selected ? 'queue-card-selected' : ''}`}
      aria-label={`${c.id}, ${pressureLabel(c)}, ${c.boxes} boxes`}
    >
      <div className="queue-card-topline">
        <span className={`queue-status-dot queue-status-dot-${tone}`} aria-hidden />
        <strong className="queue-card-id">{c.id}</strong>
        {replaying && <span className="queue-live-badge">Live</span>}
        <span className="queue-card-state">{c.stateLabel}</span>
      </div>

      <div className="queue-card-impact">
        <strong className={c.slack.currentPlanHours < 0 ? 'queue-impact-late' : ''}>
          {pressureLabel(c)}
        </strong>
        <span aria-hidden>·</span>
        <span>{c.boxes} boxes</span>
      </div>

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

      <div className="queue-card-footline">
        {c.rescuableByRemovingItt ? (
          <>
            <span className="queue-recovery-badge">Recoverable</span>
            <span>Removing the transfer restores {c.slack.ittCostHours.toFixed(1)}h</span>
          </>
        ) : c.outcome ? (
          <>
            <span className="queue-recorded-badge">Recorded</span>
            <span className="truncate">{c.outcome.label}</span>
          </>
        ) : (
          <span>Review the suggested plans</span>
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
  const [filter, setFilter] = useState<Filter>('all');
  const [query, setQuery] = useState('');
  const live = connections.filter((c) => c.lifecycle === 'live');
  const atRisk = connections.filter((c) => c.severity === 'AT_RISK');
  const rescuable = connections.filter((c) => c.rescuableByRemovingItt);

  const shown = useMemo(() => {
    const filtered =
      filter === 'live'
        ? live
        : filter === 'risk'
          ? atRisk
          : filter === 'rescuable'
            ? rescuable
            : connections;
    const normalisedQuery = query.trim().toLowerCase();
    if (!normalisedQuery) return filtered;
    return filtered.filter((c) =>
      [c.id, c.inbound.name, c.outbound.name, c.inbound.terminalLabel, c.outbound.terminalLabel]
        .join(' ')
        .toLowerCase()
        .includes(normalisedQuery),
    );
  }, [atRisk, connections, filter, live, query, rescuable]);

  const filters = [
    { id: 'all' as const, label: 'All', count: connections.length },
    { id: 'live' as const, label: 'Live', count: live.length },
    { id: 'risk' as const, label: 'At risk', count: atRisk.length },
    { id: 'rescuable' as const, label: 'Recoverable', count: rescuable.length },
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
