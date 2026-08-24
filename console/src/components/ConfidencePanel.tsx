/**
 * Confidence, as a derivation rather than a badge.
 *
 * The number alone invites exactly the question the design exists to answer —
 * why should I trust that? So the panel shows the value, the band, and the
 * whole waterfall down from 1.0: what each factor was, what it multiplied by,
 * and what it cost. B emits a `derivation` string designed to be shown
 * verbatim, and it is, immediately under the number.
 *
 * Below that: which tool failed, what was used instead, how stale it was, and
 * which specific inputs the engine could not verify — each marked at the value,
 * not in a footnote.
 */

import type { ConfidenceVM } from '../adapters/types';
import { latency, minutesAgo } from '../lib/format';
import { Note, Panel, UnverifiedMark } from './ui';

function Dial({ c }: { c: ConfidenceVM }) {
  const pctValue = Math.max(0, Math.min(1, c.value)) * 100;
  const thresholdPct = c.threshold * 100;
  const tone = c.belowThreshold ? 'text-risk-500' : 'text-safe-500';
  const barTone = c.belowThreshold ? 'bg-risk-500' : 'bg-safe-500';

  return (
    <div>
      <div className="flex items-end gap-3">
        <div className={`tnum text-6xl font-bold leading-none ${tone}`}>{c.value.toFixed(4)}</div>
        <div className="pb-1">
          <div
            className={`inline-flex items-center rounded-lg border px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ${
              c.belowThreshold
                ? 'border-risk-500/50 bg-risk-900 text-risk-500'
                : 'border-safe-500/50 bg-safe-900 text-safe-500'
            }`}
          >
            {c.belowThreshold ? 'below threshold' : 'within policy'}
          </div>
          <div className="mt-1 text-[11px] text-mist-500">
            policy threshold {c.threshold.toFixed(2)}
          </div>
        </div>
      </div>

      {/* The bar exists to place the value against the threshold, which is the
          only comparison that changes anything. */}
      <div className="relative mt-3 h-2.5 overflow-hidden rounded-full bg-white/[0.08]">
        <div className={`h-full ${barTone}`} style={{ width: `${pctValue}%` }} />
        <div
          className="absolute top-0 h-full w-[2px] bg-mist-100"
          style={{ left: `${thresholdPct}%` }}
          title={`Escalation threshold ${c.threshold}`}
        />
      </div>
      <div className="relative mt-1 h-4 text-[10px] text-mist-500">
        <span className="absolute left-0">0.00</span>
        <span
          className="absolute -translate-x-1/2 whitespace-nowrap text-mist-300"
          style={{ left: `${thresholdPct}%` }}
        >
          {c.threshold.toFixed(2)} gate
        </span>
        <span className="absolute right-0">1.00</span>
      </div>
    </div>
  );
}

function Waterfall({ c }: { c: ConfidenceVM }) {
  const rows = [
    { label: 'Start', detail: 'every plan starts fully trusted', running: 1, cost: 0, factor: 1, kind: 'start' as const },
    ...c.waterfall,
  ];

  return (
    <div className="mt-1">
      <div className="grid grid-cols-[1fr_auto_auto] gap-x-4 border-b border-white/10 pb-1 text-[10px] uppercase tracking-[0.12em] text-mist-500">
        <span>Factor</span>
        <span className="text-right">Applied</span>
        <span className="text-right">Running</span>
      </div>

      {rows.map((r, i) => {
        const width = Math.max(0, Math.min(1, r.running)) * 100;
        const isStart = r.kind === 'start';
        return (
          <div key={i} className="border-b border-white/6 py-2 last:border-0">
            <div className="grid grid-cols-[1fr_auto_auto] items-baseline gap-x-4">
              <div>
                <span className={isStart ? 'text-mist-500' : 'font-medium text-mist-100'}>
                  {r.label}
                </span>
                <span className="ml-2 text-[11px] text-mist-500">{r.detail}</span>
              </div>
              <span className="tnum text-right text-[11px] text-mist-400">
                {isStart ? '—' : r.kind === 'multiply' ? `× ${r.factor.toFixed(4)}` : `− ${r.factor.toFixed(2)}`}
              </span>
              <span className="tnum text-right font-semibold text-mist-100">
                {r.running.toFixed(4)}
              </span>
            </div>
            <div className="mt-1.5 flex items-center gap-2">
              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/[0.05]">
                <div
                  className={`h-full ${isStart ? 'bg-mist-500' : r.running < c.threshold ? 'bg-risk-500' : 'bg-safe-500'}`}
                  style={{ width: `${width}%` }}
                />
              </div>
              {!isStart && r.cost > 0 && (
                <span className="tnum w-16 text-right text-[10px] text-risk-500">
                  −{r.cost.toFixed(4)}
                </span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function ConfidencePanel({ c }: { c: ConfidenceVM | null }) {
  if (!c) {
    return (
      <Panel title="Confidence" subtitle="Not computed on this run">
        <Note tone="warn">
          No confidence score exists for this connection. B computes it from the provenance of the
          tool calls that produced a plan — with no plan, there is nothing to score. A plan resting
          on nothing we can name is not a confident plan.
        </Note>
      </Panel>
    );
  }

  return (
    <Panel
      title="Confidence"
      subtitle="Computed from provenance by policy. The model may reason about its certainty; it may never set this number."
      tone={c.belowThreshold ? 'alert' : 'default'}
    >
      <Dial c={c} />

      {/* B emits this string to be shown verbatim beside the number. */}
      <div className="glass-inset mt-4 rounded-xl px-3 py-2">
        <div className="text-[10px] uppercase tracking-[0.12em] text-mist-500">
          Derivation, as recorded
        </div>
        <code className="mt-1 block font-mono text-[11px] leading-relaxed text-mist-300">
          {c.derivation}
        </code>
      </div>

      <h3 className="mt-5 text-[11px] font-semibold uppercase tracking-[0.14em] text-mist-400">
        How it got there
      </h3>
      <Waterfall c={c} />

      {/* --- why: the degradations that actually moved the number --------- */}
      {c.degradations.length > 0 && (
        <>
          <h3 className="mt-5 text-[11px] font-semibold uppercase tracking-[0.14em] text-mist-400">
            What went wrong
          </h3>
          <div className="mt-2 space-y-2">
            {c.degradations.map((d, i) => (
              <div key={i} className="rounded-lg border border-risk-500/40 bg-risk-900/40 px-3 py-2">
                <div className="flex flex-wrap items-baseline gap-x-2">
                  <code className="font-mono text-xs font-semibold text-risk-500">{d.tool}</code>
                  <span className="text-xs text-mist-300">{d.what}</span>
                  <span className="text-[11px] text-mist-500">
                    · {d.attempts} attempt{d.attempts === 1 ? '' : 's'}
                    {d.latencyMs ? ` · ${latency(d.latencyMs)} spent` : ''}
                  </span>
                </div>
                <div className="mt-1 text-[11px] text-mist-400">
                  Fell back to: <span className="text-mist-100">{d.fallback}</span>
                  {d.servedStale && (
                    <span className="ml-2 rounded-lg border border-watch-500/50 bg-watch-900 px-1.5 py-[1px] text-[10px] font-semibold uppercase tracking-wide text-watch-500">
                      {minutesAgo(d.ageMin)}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      {/* --- which specific fields are unverified -------------------------- */}
      <h3 className="mt-5 text-[11px] font-semibold uppercase tracking-[0.14em] text-mist-400">
        Inputs the engine could not verify
      </h3>

      {c.unverifiedCount === 0 ? (
        <p className="mt-2 text-xs text-safe-500">
          None. All {c.inputCount ?? '—'} inputs were first-attempt live reads.
        </p>
      ) : c.unverifiedFieldsReconciled ? (
        <div className="mt-2 space-y-1.5">
          {c.unverifiedFields.map((f) => (
            <div
              key={f.field}
              className="flex flex-wrap items-baseline gap-x-2 rounded-lg border border-white/10 bg-white/[0.05] px-3 py-2"
            >
              <code className="font-mono text-xs text-mist-100">{f.field}</code>
              <UnverifiedMark why={f} />
              <span className="text-[11px] text-mist-400">{f.reason}</span>
            </div>
          ))}
          <p className="pt-1 text-[11px] text-mist-500">
            {c.unverifiedCount} of {c.inputCount} inputs, costing{' '}
            <span className="tnum text-mist-300">
              {(c.unverifiedCount * 0.05).toFixed(2)}
            </span>{' '}
            at the frozen per-input penalty.
          </p>
        </div>
      ) : (
        <Note tone="warn">
          B counted <span className="tnum">{c.unverifiedCount}</span> unverified input
          {c.unverifiedCount === 1 ? '' : 's'}, but this console could not establish which ones from
          the trace. `Provenance` is not serialised (CONTRACTS.md §6), so the field names are
          reconstructed — and when the reconstruction disagrees with B's own count, the count is
          shown and the names are not guessed.
        </Note>
      )}

      <div className="mt-4 grid grid-cols-3 gap-3 border-t border-white/10 pt-3 text-[11px]">
        <div>
          <div className="text-[10px] uppercase tracking-wide text-mist-500">Weakest source</div>
          <div className="mt-0.5 font-mono text-mist-100">{c.weakestSource}</div>
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-wide text-mist-500">Oldest input</div>
          <div className="tnum mt-0.5 text-mist-100">{minutesAgo(c.oldestInputMin)}</div>
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-wide text-mist-500">Worst tool outcome</div>
          <div className="mt-0.5 font-mono text-mist-100">{c.worstToolOutcome}</div>
        </div>
      </div>

      <p className="mt-3 text-[11px] leading-relaxed text-mist-500">
        Each factor is taken from the <em>weakest</em> input in the plan, not the average. A plan is
        only as trustworthy as the worst thing it rests on.
      </p>
    </Panel>
  );
}
