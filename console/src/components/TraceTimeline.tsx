/**
 * B's execution trace as a vertical timeline.
 *
 * Ordering is by `seq`, never by the `at` timestamp: B stamps wall clock at
 * record time, so every step of a captured run shares a millisecond and the
 * timestamps are not scenario time (CONTRACTS.md §12.3). Duration comes from
 * `latency_ms`, which is real.
 *
 * Errors and escalations are visually distinct because they are the steps a
 * viewer needs to find without being told where to look. Raw JSON is behind a
 * toggle and is never the primary view.
 */

import { useState } from 'react';

import type { TimelineEventVM, TimelineTone } from '../adapters/types';
import { latency, tokens, usd } from '../lib/format';

const TONE: Record<TimelineTone, { dot: string; rail: string; label: string; body: string }> = {
  normal: { dot: 'bg-mist-500', rail: 'bg-ink-900/15', label: 'text-mist-500', body: 'text-mist-200' },
  muted: { dot: 'bg-mist-600', rail: 'bg-ink-900/15', label: 'text-mist-600', body: 'text-mist-400' },
  decision: {
    dot: 'bg-flag-500 ring-4 ring-flag-900',
    rail: 'bg-ink-900/15',
    label: 'text-flag-500',
    body: 'text-mist-100 font-medium',
  },
  error: {
    dot: 'bg-risk-500 ring-4 ring-risk-900',
    rail: 'bg-risk-500/30',
    label: 'text-risk-500',
    body: 'text-risk-500 font-medium',
  },
  escalation: {
    dot: 'bg-watch-500 ring-4 ring-watch-900',
    rail: 'bg-watch-500/30',
    label: 'text-watch-500',
    body: 'text-watch-500 font-medium',
  },
  success: {
    dot: 'bg-safe-500 ring-2 ring-safe-900',
    rail: 'bg-ink-900/15',
    label: 'text-safe-500',
    body: 'text-mist-100',
  },
};

function StatusPill({ status }: { status: string }) {
  const tone =
    status === 'ok'
      ? 'border-safe-500/40 bg-safe-900 text-safe-500'
      : status === 'cached_fallback'
        ? 'border-watch-500/40 bg-watch-900 text-watch-500'
        : 'border-risk-500/40 bg-risk-900 text-risk-500';
  return (
    <span className={`rounded-lg border px-1.5 py-[1px] text-[9px] font-semibold uppercase tracking-wide ${tone}`}>
      {status.replace('_', ' ')}
    </span>
  );
}

function Event({ e, last, dimmed }: { e: TimelineEventVM; last: boolean; dimmed: boolean }) {
  const [open, setOpen] = useState(false);
  const t = TONE[e.tone];

  return (
    <div className={`relative pl-7 ${dimmed ? 'opacity-35' : 'fade-in'}`}>
      {!last && <span className={`absolute left-[7px] top-4 h-full w-[2px] ${t.rail}`} />}
      <span className={`absolute left-[3px] top-[7px] h-2.5 w-2.5 rounded-full ${t.dot}`} />

      <div className="pb-3">
        <div className="flex flex-wrap items-baseline gap-x-2">
          <span className="tnum text-[10px] text-mist-500">{String(e.seq).padStart(2, '0')}</span>
          <span className={`text-[10px] font-bold uppercase tracking-[0.12em] ${t.label}`}>
            {e.label}
          </span>
          {e.toolStatus && <StatusPill status={e.toolStatus} />}
          {e.latencyMs !== null && (
            <span
              className={`tnum text-[10px] ${e.latencyMs >= 5000 ? 'font-semibold text-risk-500' : 'text-mist-500'}`}
            >
              {latency(e.latencyMs)}
            </span>
          )}
          {e.tokens && (
            <span className="tnum ml-auto text-[10px] text-mist-500">
              {tokens(e.tokens.input)} in / {tokens(e.tokens.output)} out ·{' '}
              <span className="font-semibold text-mist-300">{usd(e.tokens.usd)}</span>
            </span>
          )}
        </div>

        <div className={`mt-0.5 text-[13px] leading-snug ${t.body}`}>{e.title}</div>

        {e.detail.map((d, i) => (
          <div key={i} className="mt-0.5 text-[11px] leading-relaxed text-mist-500">
            {d}
          </div>
        ))}

        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="mt-1 text-[10px] text-mist-500 transition hover:text-mist-300"
        >
          {open ? '− hide raw step' : '+ raw step'}
        </button>
        {open && (
          <pre className="mt-1 overflow-x-auto rounded-lg border border-ink-900/10 bg-ink-900/[0.055] p-2 font-mono text-[10px] leading-relaxed text-mist-400">
            {JSON.stringify(e.raw, null, 2)}
          </pre>
        )}
      </div>
    </div>
  );
}

export function TraceTimeline({
  events,
  allEvents,
  cost,
}: {
  events: TimelineEventVM[];
  /** Full trace when replaying, so unrevealed steps can be shown greyed. */
  allEvents?: TimelineEventVM[];
  cost: { usd: number; modelCalls: number };
}) {
  const [rawAll, setRawAll] = useState(false);
  const shown = allEvents ?? events;
  const revealed = events.length;

  return (
    <div className="rounded-2xl border border-ink-900/10 bg-ink-900/[0.025]">
      <header className="flex items-center justify-between gap-4 border-b border-ink-900/10 px-4 py-2.5">
        <div>
          <h2 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-mist-400">
            Execution trace
          </h2>
          <p className="mt-0.5 text-xs text-mist-500">
            {revealed} step{revealed === 1 ? '' : 's'} · {cost.modelCalls} model call
            {cost.modelCalls === 1 ? '' : 's'} · {usd(cost.usd)} total
          </p>
        </div>
        <button
          type="button"
          onClick={() => setRawAll((v) => !v)}
          className="rounded-lg border border-ink-900/15 px-2 py-1 text-[10px] uppercase tracking-wide text-mist-400 transition hover:border-ink-900/20 hover:text-mist-100"
        >
          {rawAll ? 'Timeline' : 'Raw JSON'}
        </button>
      </header>

      <div className="max-h-[560px] overflow-y-auto p-4">
        {rawAll ? (
          <pre className="overflow-x-auto font-mono text-[10px] leading-relaxed text-mist-400">
            {JSON.stringify(events.map((e) => e.raw), null, 2)}
          </pre>
        ) : shown.length === 0 ? (
          <p className="text-xs text-mist-500">No steps yet.</p>
        ) : (
          shown.map((e, i) => (
            <Event key={e.seq} e={e} last={i === shown.length - 1} dimmed={i >= revealed} />
          ))
        )}
      </div>

      <footer className="border-t border-ink-900/10 px-4 py-2 text-[10px] leading-relaxed text-mist-500">
        Ordered by sequence, not timestamp. B stamps wall clock at record time, so the `at` values
        in a captured run are not scenario time — durations above come from each step's own
        `latency_ms`.
      </footer>
    </div>
  );
}
