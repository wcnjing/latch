/**
 * The risk queue: every live connection, sorted by criticality.
 *
 * Rows update in place — the list is keyed on connection id, so a connection
 * moving from DELIBERATING to SUPERSEDED changes that row rather than adding
 * one. A resolved connection keeps its row and shows its outcome; it does not
 * disappear, because "what happened to the one I approved ten minutes ago" is a
 * question an operator asks constantly.
 */

import type { ConnectionVM, OutcomeTone } from '../adapters/types';
import { signedHours } from '../lib/format';
import { SeverityBadge, StateBadge } from './ui';

/** The queue dot and the detail badge read the same tone, so they cannot
    tell the operator two different things about one outcome. */
const DOT_TONE: Record<OutcomeTone, string> = {
  good: 'bg-safe-500',
  bad: 'bg-risk-500',
  fault: 'bg-risk-500 ring-1 ring-risk-500/50',
  neutral: 'bg-mist-500',
  gap: 'bg-transparent ring-1 ring-mist-500',
};

function ConfidencePip({ c }: { c: ConnectionVM['confidence'] }) {
  if (!c) {
    return <span className="tnum text-[11px] text-mist-600">—</span>;
  }
  const tone = c.belowThreshold ? 'text-risk-500' : c.value < 0.9 ? 'text-watch-500' : 'text-safe-500';
  return (
    <span className={`tnum text-[11px] font-semibold ${tone}`} title={c.derivation}>
      {c.value.toFixed(2)}
      {c.belowThreshold && <span className="ml-1 text-[9px] uppercase">esc</span>}
    </span>
  );
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
  const dim = c.lifecycle !== 'live';
  const severityBar =
    c.severity === 'AT_RISK'
      ? 'bg-risk-500'
      : c.severity === 'WATCH'
        ? 'bg-watch-500'
        : 'bg-safe-500';

  return (
    <button
      type="button"
      onClick={onSelect}
      className={`relative w-full border-b border-ink-800 px-3 py-2.5 text-left transition ${
        selected ? 'bg-ink-750' : 'hover:bg-ink-800'
      } ${dim && !selected ? 'opacity-70' : ''}`}
    >
      <span className={`absolute left-0 top-0 h-full w-[3px] ${severityBar}`} />

      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <SeverityBadge label={c.severityLabel} />
          <span className="truncate font-mono text-xs text-mist-100">{c.id}</span>
          {replaying && (
            <span className="rounded bg-flag-900 px-1.5 py-[1px] text-[9px] font-bold uppercase tracking-wide text-flag-500">
              live
            </span>
          )}
        </div>
        <ConfidencePip c={c.confidence} />
      </div>

      <div className="mt-1.5 flex items-center justify-between gap-2 text-[11px]">
        <div className="flex items-center gap-2 text-mist-400">
          <span className="tnum">
            <span
              className={
                c.slack.currentPlanHours < 0 ? 'font-semibold text-risk-500' : 'text-mist-200'
              }
            >
              {signedHours(c.slack.currentPlanHours)}
            </span>{' '}
            slack
          </span>
          <span className="text-ink-500">·</span>
          <span className="tnum">{c.boxes} boxes</span>
        </div>
        <StateBadge label={c.stateLabel} />
      </div>

      {/* The single most useful thing A sends: would removing the transfer save it. */}
      {c.rescuableByRemovingItt && (
        <div className="mt-1.5 flex items-center gap-1.5 rounded border border-flag-500/40 bg-flag-900/50 px-2 py-1">
          <span className="text-[11px] leading-none text-flag-500">⤳</span>
          <span className="text-[10px] font-semibold uppercase tracking-wide text-flag-500">
            Removing the transfer rescues this
          </span>
          <span className="tnum ml-auto text-[10px] text-mist-400">
            +{c.slack.ittCostHours.toFixed(1)}h back
          </span>
        </div>
      )}

      {c.lifecycle !== 'live' && c.outcome && (
        <div className="mt-1.5 flex items-center gap-1.5 text-[10px]">
          <span
            className={`inline-block h-1.5 w-1.5 rounded-full ${DOT_TONE[c.outcome.tone]}`}
          />
          <span className="text-mist-400">{c.outcome.label}</span>
        </div>
      )}
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
  const live = connections.filter((c) => c.lifecycle === 'live');
  const atRisk = connections.filter((c) => c.severity === 'AT_RISK');
  const rescuable = connections.filter((c) => c.rescuableByRemovingItt);

  return (
    <div className="flex h-full flex-col border-r border-ink-700 bg-ink-850">
      <header className="border-b border-ink-700 px-3 py-2.5">
        <div className="flex items-baseline justify-between">
          <h2 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-mist-400">
            Risk queue
          </h2>
          <span className="tnum text-[11px] text-mist-500">{connections.length} connections</span>
        </div>
        <div className="mt-1.5 flex gap-3 text-[10px] text-mist-500">
          <span>
            <span className="tnum font-semibold text-risk-500">{atRisk.length}</span> at risk
          </span>
          <span>
            <span className="tnum font-semibold text-flag-500">{rescuable.length}</span> ITT-rescuable
          </span>
          <span>
            <span className="tnum font-semibold text-mist-300">{live.length}</span> in flight
          </span>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto">
        {connections.map((c) => (
          <Row
            key={c.id}
            c={c}
            selected={c.id === selectedId}
            onSelect={() => onSelect(c.id)}
            replaying={c.id === replayingId}
          />
        ))}
      </div>

      <footer className="border-t border-ink-700 px-3 py-2 text-[10px] leading-relaxed text-mist-500">
        Sorted by criticality: in-flight first, then severity, then B's own priority
        (boxes ÷ remaining hours) — the same number the Lock Table arbitrates on.
      </footer>
    </div>
  );
}
