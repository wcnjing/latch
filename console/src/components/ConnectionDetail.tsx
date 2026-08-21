/**
 * One connection, in full: the two vessel legs and their timing, the slack
 * comparison the whole product turns on, why it is at risk in operator
 * English, and the options B ranked.
 */

import { CUT_RUNG } from '../adapters/toViewModel';
import type { ConnectionVM, OptionVM, Unverified } from '../adapters/types';
import { hhmm, hoursAndMinutes, pct, signedHours, stamp } from '../lib/format';
import { GapMarker, Note, Panel, Placeholder, SeverityBadge, StateBadge, Stat, UnverifiedMark } from './ui';

/* ---------------------------------------------------------------- legs -- */

function Leg({
  leg,
  role,
}: {
  leg: ConnectionVM['inbound'];
  role: 'Inbound' | 'Outbound';
}) {
  const late = leg.deviationMin > 0;
  return (
    <div className="flex-1 rounded border border-ink-700 bg-ink-800 p-3">
      <div className="text-[10px] uppercase tracking-[0.12em] text-mist-500">{role}</div>
      <div className="mt-1 truncate text-sm font-semibold text-mist-100" title={leg.name}>
        {leg.name}
      </div>
      <div className="mt-0.5 text-[11px] text-mist-400">{leg.terminalLabel}</div>

      <div className="mt-3 grid grid-cols-2 gap-2 text-[11px]">
        <div>
          <div className="text-[10px] uppercase tracking-wide text-mist-500">Planned</div>
          <div className="tnum mt-0.5 text-mist-300">{hhmm(leg.scheduled)}</div>
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-wide text-mist-500">Estimated</div>
          <div className={`tnum mt-0.5 ${late ? 'font-semibold text-risk-500' : 'text-mist-300'}`}>
            {hhmm(leg.estimated)}
          </div>
        </div>
      </div>

      {leg.deviationMin !== 0 && (
        <div
          className={`tnum mt-2 text-[11px] ${late ? 'text-risk-500' : 'text-safe-500'}`}
        >
          {late ? '+' : '−'}
          {Math.abs(leg.deviationMin)} min {late ? 'late' : 'early'}
        </div>
      )}
    </div>
  );
}

/* -------------------------------------------------------------- slack --- */

function SlackCompare({ c }: { c: ConnectionVM }) {
  const scale = Math.max(
    Math.abs(c.slack.currentPlanHours),
    Math.abs(c.slack.noIttHours),
    1,
  );
  const bar = (h: number) => `${(Math.abs(h) / scale) * 50}%`;

  const Row = ({ label, hours, hint }: { label: string; hours: number; hint: string }) => (
    <div className="py-2">
      <div className="flex items-baseline justify-between">
        <span className="text-xs text-mist-300">{label}</span>
        <span
          className={`tnum text-lg font-bold ${hours < 0 ? 'text-risk-500' : 'text-safe-500'}`}
        >
          {signedHours(hours)}
        </span>
      </div>
      {/* Centre line is zero: left of it is short, right of it is margin. */}
      <div className="relative mt-1.5 h-3 rounded bg-ink-800">
        <span className="absolute left-1/2 top-0 h-full w-[2px] -translate-x-1/2 bg-ink-600" />
        <div
          className={`absolute top-0 h-full ${hours < 0 ? 'rounded-l bg-risk-500' : 'rounded-r bg-safe-500'}`}
          style={
            hours < 0
              ? { right: '50%', width: bar(hours) }
              : { left: '50%', width: bar(hours) }
          }
        />
      </div>
      <div className="mt-1 text-[10px] text-mist-500">{hint}</div>
    </div>
  );

  return (
    <div>
      <Row
        label="Slack under the current plan"
        hours={c.slack.currentPlanHours}
        hint={
          c.slack.currentPlanHours < 0
            ? `${hoursAndMinutes(c.slack.currentPlanHours)} — the boxes miss the cut-off as planned`
            : `${hoursAndMinutes(c.slack.currentPlanHours)} of margin as planned`
        }
      />
      <Row
        label="Slack without the inter-terminal transfer"
        hours={c.slack.noIttHours}
        hint="Margin if the transfer requirement were removed entirely"
      />

      <div className="mt-2 flex items-center justify-between rounded border border-ink-700 bg-ink-800 px-3 py-2">
        <span className="text-[11px] text-mist-400">The transfer is costing</span>
        <span className="tnum text-base font-bold text-flag-500">
          {c.slack.ittCostHours.toFixed(1)}h
        </span>
      </div>

      {c.rescuableByRemovingItt ? (
        <div className="mt-2 rounded border border-flag-500/50 bg-flag-900/50 px-3 py-2">
          <div className="text-[10px] font-bold uppercase tracking-[0.14em] text-flag-500">
            Removing the transfer rescues this connection
          </div>
          <p className="mt-1 text-[11px] leading-relaxed text-mist-300">
            Negative margin with the transfer, positive without it. Rung 1 is a live option here,
            not advisory noise — co-locating the two vessels would eliminate the problem rather than
            manage it.
          </p>
        </div>
      ) : (
        <p className="mt-2 text-[11px] leading-relaxed text-mist-500">
          {c.crossesTerminals
            ? 'The cargo does cross terminals, but removing the transfer would not by itself save the connection — the margin is negative either way.'
            : 'Both legs work the same terminal. No inter-terminal transfer is involved.'}
        </p>
      )}
    </div>
  );
}

/* ------------------------------------------------------------- options -- */

const STATUS_STYLE: Record<OptionVM['status'], string> = {
  chosen: 'border-safe-500/50 bg-safe-900/40',
  advisory: 'border-flag-500/40 bg-flag-900/30',
  ruled_out: 'border-ink-700 bg-ink-800/60',
};

const STATUS_LABEL: Record<OptionVM['status'], string> = {
  chosen: 'Chosen',
  advisory: 'Advisory — not the action',
  ruled_out: 'Ruled out in code, before the model saw it',
};

function Options({
  options,
  unverified,
}: {
  options: OptionVM[];
  /** Empty when every input was a first-attempt live read. */
  unverified: Unverified[];
}) {
  if (options.length === 0) {
    return <p className="text-xs text-mist-500">No options were enumerated on this run.</p>;
  }

  return (
    <div className="space-y-2">
      {options.map((o) => (
        <div key={o.id} className={`rounded border p-3 ${STATUS_STYLE[o.status]}`}>
          <div className="flex flex-wrap items-baseline gap-x-2">
            <span className="rounded border border-ink-600 bg-ink-850 px-1.5 py-[1px] text-[10px] font-bold uppercase tracking-wide text-mist-300">
              Rung {o.rung.number} · {o.rung.name}
            </span>
            <span
              className={`text-[10px] font-semibold uppercase tracking-wide ${
                o.status === 'chosen'
                  ? 'text-safe-500'
                  : o.status === 'advisory'
                    ? 'text-flag-500'
                    : 'text-mist-500'
              }`}
            >
              {STATUS_LABEL[o.status]}
            </span>
            {o.confidence !== null && (
              <span className="ml-auto flex items-baseline text-[11px] text-mist-400">
                <span className="tnum">conf {o.confidence.toFixed(4)}</span>
                {/* The mark belongs at the number, not in a footnote: this
                    plan's score rests on an input nobody could verify. */}
                {unverified.length > 0 && <UnverifiedMark why={unverified[0]} />}
              </span>
            )}
          </div>

          {o.rationale && (
            <p className="mt-1.5 text-xs leading-relaxed text-mist-200">{o.rationale}</p>
          )}
          {o.exclusionReason && (
            <p className="mt-1.5 text-[11px] leading-relaxed text-mist-400">{o.exclusionReason}</p>
          )}

          <div className="mt-2 flex gap-5 border-t border-ink-700/60 pt-2 text-[11px]">
            <div>
              <span className="text-[10px] uppercase tracking-wide text-mist-500">Cost </span>
              <GapMarker value={o.costSgd} className="tnum text-mist-200" />
            </div>
            <div>
              <span className="text-[10px] uppercase tracking-wide text-mist-500">Emissions </span>
              <GapMarker value={o.emissionsKgCo2e} className="tnum text-mist-200" />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

/* --------------------------------------------------------------- ladder -- */

function LadderRail({ active }: { active: number | null }) {
  return (
    <div className="space-y-1.5">
      {[1, 2, 3, 4].map((n) => {
        if (n === 2) {
          return (
            <div
              key={n}
              className="rounded border border-dashed border-ink-600 bg-ink-900/60 px-3 py-2"
            >
              <div className="flex items-baseline gap-2">
                <span className="tnum text-xs font-bold text-ink-500">2</span>
                <span className="text-[11px] font-semibold uppercase tracking-wide text-ink-500 line-through">
                  {CUT_RUNG.name}
                </span>
                <span className="ml-auto text-[9px] font-bold uppercase tracking-wider text-ink-500">
                  cut
                </span>
              </div>
              <p className="mt-1 text-[10px] leading-relaxed text-mist-600">{CUT_RUNG.whyCut}</p>
            </div>
          );
        }
        const meta =
          n === 1
            ? { name: 'PREVENT', does: 'Reassign the berth so both vessels work one terminal', who: 'Berth Planner — advisory only' }
            : n === 3
              ? { name: 'MOVE', does: 'Book the inter-terminal transfer slot', who: 'Vessel Operations' }
              : { name: 'OFFER', does: 'Put ranked options to the shipping line', who: 'The line decides' };
        const on = active === n;
        return (
          <div
            key={n}
            className={`rounded border px-3 py-2 ${
              on ? 'border-flag-500/60 bg-flag-900/40' : 'border-ink-700 bg-ink-800'
            }`}
          >
            <div className="flex items-baseline gap-2">
              <span className={`tnum text-xs font-bold ${on ? 'text-flag-500' : 'text-mist-500'}`}>
                {n}
              </span>
              <span
                className={`text-[11px] font-semibold uppercase tracking-wide ${on ? 'text-flag-500' : 'text-mist-300'}`}
              >
                {meta.name}
              </span>
              {on && (
                <span className="ml-auto text-[9px] font-bold uppercase tracking-wider text-flag-500">
                  taken
                </span>
              )}
            </div>
            <p className="mt-0.5 text-[10px] leading-relaxed text-mist-500">{meta.does}</p>
            <p className="mt-0.5 text-[10px] text-mist-600">{meta.who}</p>
          </div>
        );
      })}
      <p className="pt-1 text-[10px] leading-relaxed text-mist-500">
        Autonomy is inversely proportional to value: the rung that would help most is the one the
        agent may not take.
      </p>
    </div>
  );
}

/* -------------------------------------------------------------- detail -- */

export function ConnectionDetail({ c }: { c: ConnectionVM }) {
  const activeRung = c.options.find((o) => o.status === 'chosen')?.rung.number ?? null;

  return (
    <div className="space-y-4">
      {/* --- header ---------------------------------------------------- */}
      <div className="rounded-lg border border-ink-700 bg-ink-850 p-4">
        <div className="flex flex-wrap items-center gap-3">
          <SeverityBadge label={c.severityLabel} big />
          <h1 className="font-mono text-lg font-semibold text-mist-100">{c.id}</h1>
          <StateBadge label={c.stateLabel} />
          <span className="ml-auto font-mono text-[11px] text-mist-500">{c.ucid}</span>
        </div>

        {c.stateNote && (
          <p className="mt-2 rounded border border-ink-700 bg-ink-800 px-3 py-2 text-[11px] leading-relaxed text-mist-300">
            {c.stateNote}
          </p>
        )}

        <div className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Stat
            label="Boxes at risk"
            value={c.boxes}
            hint={c.boxes > 40 ? 'over the 40-box auto-approve limit' : 'inside the volume limit'}
            tone={c.boxes > 40 ? 'warn' : 'default'}
          />
          <Stat
            label="Slack remaining"
            value={signedHours(c.slack.currentPlanHours)}
            hint={`${pct(c.slack.consumedPct)} of the window consumed`}
            tone={c.slack.currentPlanHours < 0 ? 'bad' : 'default'}
          />
          <Stat
            label="Priority"
            value={Math.round(c.priority)}
            hint="boxes ÷ remaining hours"
          />
          <Stat
            label="Detected"
            value={<span className="text-sm">{stamp(c.detectedAt)}</span>}
            hint="SGT"
          />
        </div>
      </div>

      {/* --- vessels ---------------------------------------------------- */}
      <Panel title="Vessel timing" subtitle="Arrival estimates derived from real AIS observations">
        <div className="flex flex-col gap-3 sm:flex-row">
          <Leg leg={c.inbound} role="Inbound" />
          <div className="flex items-center justify-center px-1">
            <div className="text-center">
              <div className="text-lg leading-none text-mist-500">→</div>
              {c.crossesTerminals && (
                <div className="mt-1 whitespace-nowrap rounded border border-flag-500/40 bg-flag-900 px-1.5 py-[1px] text-[9px] font-bold uppercase tracking-wide text-flag-500">
                  ITT
                </div>
              )}
            </div>
          </div>
          <Leg leg={c.outbound} role="Outbound" />
        </div>
      </Panel>

      {/* --- slack ------------------------------------------------------ */}
      <Panel
        title="Margin"
        subtitle="Current plan against the same connection without the transfer"
      >
        <SlackCompare c={c} />
      </Panel>

      {/* --- reasons ---------------------------------------------------- */}
      <Panel title="Why it is at risk">
        <div className="space-y-2">
          {c.reasons.map((r) => (
            <div key={r.code} className="rounded border border-ink-700 bg-ink-800 px-3 py-2">
              <div className="flex items-baseline gap-2">
                <span className="text-xs font-semibold text-mist-100">{r.title}</span>
                {!r.emittedByWatcher && (
                  <span
                    className="rounded border border-ink-600 px-1.5 py-[1px] text-[9px] uppercase tracking-wide text-mist-500"
                    title="Declared in the enum but never emitted by the live Watcher — see CONTRACTS.md §5"
                  >
                    not emitted by the live Watcher
                  </span>
                )}
              </div>
              <p className="mt-0.5 text-[11px] leading-relaxed text-mist-400">{r.detail}</p>
            </div>
          ))}
        </div>

        <div className="mt-3 rounded border border-ink-700 bg-ink-800 px-3 py-2">
          <div className="text-[10px] uppercase tracking-[0.12em] text-mist-500">Triage</div>
          <p className="mt-1 text-xs text-mist-200">{c.triage.routeLabel}</p>
          <p className="mt-0.5 text-[11px] leading-relaxed text-mist-400">{c.triage.reason}</p>
          {c.triage.decidedFree && (
            <p className="mt-1 text-[10px] text-safe-500">
              Decided deterministically — no model was spent on this one.
            </p>
          )}
        </div>
      </Panel>

      {/* --- ladder and options ----------------------------------------- */}
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_260px]">
        <Panel
          title="Options B ranked"
          subtitle="Code enumerates; the model only ranks. It cannot book a slot that does not exist."
        >
          <Options options={c.options} unverified={c.confidence?.unverifiedFields ?? []} />
          <Note>
            Cost and emissions are computed by B during deliberation and put in the model's prompt,
            but no serialiser exists for a Plan, so neither reaches the trace. The console shows the
            gap rather than recomputing the figures and attributing them to the agent —
            CONTRACTS.md REQUEST TO B #1.
          </Note>
        </Panel>

        <Panel title="The ladder">
          <LadderRail active={activeRung} />
        </Panel>
      </div>

      {/* --- contested resources ---------------------------------------- */}
      {c.locks.length > 0 && (
        <Panel
          title="Contested resources"
          subtitle="Arbitrated on boxes ÷ remaining slack, never on who asked first"
        >
          <div className="space-y-2">
            {c.locks.map((l, i) => (
              <div
                key={`${l.resource}-${i}`}
                className={`rounded border p-3 ${
                  l.held ? 'border-safe-500/40 bg-safe-900/30' : 'border-risk-500/40 bg-risk-900/30'
                }`}
              >
                <div className="flex flex-wrap items-baseline gap-x-2">
                  <code className="font-mono text-xs text-mist-100">{l.resource}</code>
                  <span
                    className={`text-[10px] font-bold uppercase tracking-wide ${
                      l.held ? 'text-safe-500' : 'text-risk-500'
                    }`}
                  >
                    {l.held ? 'held' : 'lost'}
                  </span>
                  <span className="tnum ml-auto text-[11px] text-mist-400">
                    priority {Math.round(l.ourPriority)}
                    {l.winnerPriority !== null && (
                      <>
                        {' '}
                        vs{' '}
                        <span className={l.held ? 'text-safe-500' : 'text-risk-500'}>
                          {Math.round(l.winnerPriority)}
                        </span>
                      </>
                    )}
                  </span>
                </div>
                <p className="mt-1 text-xs text-mist-200">{l.outcome}</p>
                {l.consequence && (
                  <p className="mt-1 text-[11px] leading-relaxed text-mist-400">{l.consequence}</p>
                )}
              </div>
            ))}
          </div>
        </Panel>
      )}

      {/* --- outcome ---------------------------------------------------- */}
      {c.outcome && (
        <Panel
          title="Outcome"
          right={
            <span
              className={`rounded border px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ${
                c.outcome.decidedInternally
                  ? 'border-ink-500 bg-ink-800 text-mist-400'
                  : c.outcome.serviceSuccess
                    ? 'border-safe-500/50 bg-safe-900 text-safe-500'
                    : 'border-risk-500/50 bg-risk-900 text-risk-500'
              }`}
              title={
                c.outcome.decidedInternally
                  ? 'B’s metric value for this run. The customer took no part in it.'
                  : undefined
              }
            >
              {/* When the customer was never involved, the badge describes what
                  B's metric counts rather than asserting the customer was
                  served — the two are not the same thing here. */}
              {c.outcome.decidedInternally
                ? c.outcome.serviceSuccess
                  ? 'counted as served'
                  : 'counted as failed'
                : c.outcome.serviceSuccess
                  ? 'customer served'
                  : 'service failure'}
            </span>
          }
        >
          <div className="text-base font-semibold text-mist-100">{c.outcome.label}</div>
          <p className="mt-1 text-xs text-mist-200">{c.outcome.what}</p>
          <p className="mt-2 text-[11px] leading-relaxed text-mist-400">{c.outcome.why}</p>

          {c.outcome.customerGate && (
            <div className="mt-3 rounded border border-ink-700 bg-ink-800 px-3 py-2 text-[11px] text-mist-400">
              <span className="tnum text-mist-100">{c.outcome.customerGate.optionsSent}</span>{' '}
              option{c.outcome.customerGate.optionsSent === 1 ? '' : 's'} released to the line on a{' '}
              <span className="tnum text-mist-100">{c.outcome.customerGate.windowMin}</span>-minute
              window
              {c.outcome.decisionLeadTimeH !== null && (
                <>
                  {' '}
                  ·{' '}
                  <span className="tnum text-mist-100">
                    {c.outcome.decisionLeadTimeH.toFixed(1)}h
                  </span>{' '}
                  from detection to options reaching them
                </>
              )}
            </div>
          )}

          {c.outcome.metricCaveat && <div className="mt-3"><Note tone="warn">{c.outcome.metricCaveat}</Note></div>}

          {c.outcome.excludedFromMetric && (
            <p className="mt-3 text-[11px] leading-relaxed text-mist-500">
              Excluded from the north-star denominator rather than counted as a failure.
            </p>
          )}
        </Panel>
      )}

      {/* --- cost ------------------------------------------------------- */}
      <Panel title="What this decision cost" subtitle="Per decision, not a run average">
        <div className="space-y-1.5">
          {c.cost.perDecision.length === 0 ? (
            <p className="text-xs text-safe-500">
              No model was spent on this connection at all.
            </p>
          ) : (
            c.cost.perDecision.map((d) => (
              <div
                key={d.seq}
                className="flex flex-wrap items-baseline gap-x-3 rounded border border-ink-700 bg-ink-800 px-3 py-1.5 text-[11px]"
              >
                <code className="font-mono text-mist-100">{d.model}</code>
                <span className="text-mist-500">{d.purpose}</span>
                <span className="tnum ml-auto text-mist-400">
                  {d.input.toLocaleString()} in / {d.output.toLocaleString()} out
                </span>
                <span className="tnum w-16 text-right font-semibold text-mist-100">
                  ${d.usd.toFixed(4)}
                </span>
              </div>
            ))
          )}
        </div>
        <div className="mt-3 flex items-baseline justify-between border-t border-ink-700 pt-2">
          <span className="text-[11px] text-mist-400">Total for this connection</span>
          <span className="tnum text-base font-semibold text-mist-100">
            ${c.cost.usd.toFixed(4)}
          </span>
        </div>
        <Note>
          Token counts come from a scripted model seam — no model was consulted on this run — and
          are priced at B's frozen `config.PRICING` rates. Cost per rescued connection:{' '}
          <Placeholder what="A's evaluation has not run." />
        </Note>
      </Panel>
    </div>
  );
}
