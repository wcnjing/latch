/**
 * Cinema layout: the same console, sized for a screen recording.
 *
 * At normal density the confidence derivation and the gate transition are
 * legible on a monitor and marginal in a compressed video. This view drops the
 * queue, enlarges the two frames the submission turns on, and puts the current
 * trace step in large type at the top.
 *
 * Nothing here renders data the normal layout does not. The headline narration
 * is the title of the step B just recorded — the panels are the same
 * components, so the two views cannot drift apart in what they claim.
 */

import { useEffect, useRef } from 'react';

import type { ConnectionVM, TimelineEventVM } from '../adapters/types';
import { latency, signedHours, usd } from '../lib/format';
import type { Branch, Playback } from '../store/useConsole';
import { ApprovalPanel } from './ApprovalPanel';
import { ConfidencePanel } from './ConfidencePanel';
import { GateTransition } from './GateTransition';
import { SeverityBadge, StateBadge } from './ui';

const TONE_TEXT: Record<string, string> = {
  error: 'text-risk-500',
  escalation: 'text-watch-500',
  decision: 'text-flag-500',
  success: 'text-safe-500',
  normal: 'text-mist-100',
  muted: 'text-mist-400',
};

function Narration({ event }: { event: TimelineEventVM | undefined }) {
  if (!event) {
    return (
      <div className="min-h-[76px] text-2xl text-mist-600">Waiting for the first observation…</div>
    );
  }
  return (
    <div key={event.seq} className="fade-in min-h-[76px]">
      <div className="flex items-baseline gap-3">
        <span className="tnum text-sm text-mist-500">
          {String(event.seq).padStart(2, '0')}
        </span>
        <span
          className={`text-xs font-bold uppercase tracking-[0.2em] ${TONE_TEXT[event.tone] ?? 'text-mist-400'}`}
        >
          {event.label}
        </span>
        {event.toolStatus && (
          <span
            className={`rounded-lg border px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide ${
              event.toolStatus === 'ok'
                ? 'border-safe-500/40 bg-safe-900 text-safe-500'
                : event.toolStatus === 'cached_fallback'
                  ? 'border-watch-500/40 bg-watch-900 text-watch-500'
                  : 'border-risk-500/40 bg-risk-900 text-risk-500'
            }`}
          >
            {event.toolStatus.replace('_', ' ')}
          </span>
        )}
        {event.latencyMs !== null && (
          <span
            className={`tnum text-sm ${event.latencyMs >= 5000 ? 'font-semibold text-risk-500' : 'text-mist-500'}`}
          >
            {latency(event.latencyMs)}
          </span>
        )}
        {event.tokens && (
          <span className="tnum ml-auto text-sm text-mist-500">
            {event.tokens.model} · {usd(event.tokens.usd)}
          </span>
        )}
      </div>
      <div className={`mt-1 text-2xl leading-tight ${TONE_TEXT[event.tone] ?? 'text-mist-100'}`}>
        {event.title}
      </div>
      {event.detail[0] && (
        <div className="mt-1 text-base leading-snug text-mist-400">{event.detail[0]}</div>
      )}
    </div>
  );
}

function MiniTimeline({ events }: { events: TimelineEventVM[] }) {
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    end.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [events.length]);

  return (
    <div className="h-full overflow-y-auto pr-2">
      {events.map((e) => (
        <div key={e.seq} className="flex items-baseline gap-3 border-b border-ink-900/6 py-1.5">
          <span className="tnum w-6 text-xs text-mist-500">{String(e.seq).padStart(2, '0')}</span>
          <span
            className={`w-24 shrink-0 text-[11px] font-bold uppercase tracking-wider ${TONE_TEXT[e.tone] ?? 'text-mist-500'}`}
          >
            {e.label}
          </span>
          <span className={`text-sm leading-snug ${e.tone === 'muted' ? 'text-mist-500' : 'text-mist-200'}`}>
            {e.title}
          </span>
          {e.latencyMs !== null && (
            <span className="tnum ml-auto shrink-0 text-[11px] text-mist-500">
              {latency(e.latencyMs)}
            </span>
          )}
        </div>
      ))}
      <div ref={end} />
    </div>
  );
}

export function DemoStage({
  c,
  playback,
  onDecide,
}: {
  c: ConnectionVM;
  playback: Playback;
  onDecide: (b: Branch) => void;
}) {
  const current = c.timeline.at(-1);

  return (
    <div className="glass m-3 flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl">
      {/* --- headline ------------------------------------------------- */}
      <div className="border-b border-ink-900/10 bg-ink-900/[0.025] px-8 py-4">
        <div className="flex flex-wrap items-center gap-4">
          <SeverityBadge label={c.severityLabel} big />
          <h1 className="font-mono text-2xl font-bold text-mist-100">{c.id}</h1>
          <StateBadge label={c.stateLabel} />
          <div className="ml-auto flex items-center gap-8">
            <div className="text-right">
              <div className="text-[11px] uppercase tracking-wide text-mist-500">Boxes</div>
              <div className="tnum text-2xl font-bold text-mist-100">{c.boxes}</div>
            </div>
            <div className="text-right">
              <div className="text-[11px] uppercase tracking-wide text-mist-500">Slack</div>
              <div
                className={`tnum text-2xl font-bold ${c.slack.currentPlanHours < 0 ? 'text-risk-500' : 'text-safe-500'}`}
              >
                {signedHours(c.slack.currentPlanHours)}
              </div>
            </div>
            <div className="text-right">
              <div className="text-[11px] uppercase tracking-wide text-mist-500">Without the ITT</div>
              <div className="tnum text-2xl font-bold text-flag-500">
                {signedHours(c.slack.noIttHours)}
              </div>
            </div>
          </div>
        </div>

        <div className="mt-3 border-t border-ink-900/10 pt-3">
          <Narration event={current} />
        </div>
      </div>

      {/* --- stage ---------------------------------------------------- */}
      <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_620px]">
        <div className="min-h-0 overflow-hidden px-8 py-4">
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-[0.2em] text-mist-500">
            Execution trace · {c.timeline.length} step{c.timeline.length === 1 ? '' : 's'} ·{' '}
            {usd(c.cost.usd)}
          </h2>
          <div className="h-[calc(100%-2rem)]">
            <MiniTimeline events={c.timeline} />
          </div>
        </div>

        <div className="min-h-0 space-y-4 overflow-y-auto border-l border-ink-900/8 px-6 py-4">
          <ApprovalPanel
            approval={c.approval}
            gate={c.gate}
            awaiting={playback.awaiting}
            secondsLeft={playback.secondsLeft}
            decided={playback.branch}
            planLabel={null}
            onDecide={onDecide}
          />
          <GateTransition gate={c.gate} boxes={c.boxes} />
          <ConfidencePanel c={c.confidence} />
        </div>
      </div>

      {/* The data-honesty line stays on screen in cinema mode. It is exactly
          the frame most likely to be screenshotted out of context. */}
      <div className="border-t border-ink-900/10 bg-ink-900/[0.025] px-8 py-2 text-[11px] text-mist-500">
        {c.provenance.dataBasis}. Model responses scripted — no model was consulted.
      </div>
    </div>
  );
}
