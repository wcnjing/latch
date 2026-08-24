/**
 * The gate, and the autonomy it granted or took away.
 *
 * When policy escalates because confidence fell, this renders the transition
 * explicitly: what the autonomy level would have been, what it became, and the
 * criterion that moved it. That is the frame the demo video is built around, so
 * it is sized and paced to be read off a screen recording rather than
 * inspected.
 *
 * The Gate Controller takes no model client and has no way to obtain one. That
 * is the structural argument and the panel says so, because a viewer who does
 * not know it will assume the agent chose its own supervision.
 */

import { ROLE_LABEL } from '../adapters/toViewModel';
import type { GateVM } from '../adapters/types';
import { Panel } from './ui';

function RoleChip({
  role,
  state,
}: {
  role: string;
  state: 'was' | 'now' | 'unused';
}) {
  const style =
    state === 'now'
      ? 'border-watch-500 bg-watch-900 text-watch-500 font-semibold'
      : state === 'was'
        ? 'border-ink-900/15 bg-ink-900/[0.025] text-mist-500 line-through decoration-mist-600'
        : 'border-ink-900/10 bg-ink-900/[0.025] text-mist-600';
  return (
    <span className={`inline-flex items-center rounded-lg border px-2.5 py-1 text-xs ${style}`}>
      {role}
    </span>
  );
}

function Ladder({ gate }: { gate: GateVM }) {
  const ladder = gate.escalation?.ladder ?? [gate.requiredRole];
  const from = gate.escalation?.wouldHaveBeen ?? gate.requiredRole;
  return (
    <div className="flex flex-wrap items-center gap-2">
      {ladder.map((role, i) => (
        <span key={role} className="flex items-center gap-2">
          {i > 0 && <span className="text-mist-600">→</span>}
          <RoleChip
            role={ROLE_LABEL[role]}
            state={role === gate.requiredRole ? 'now' : role === from ? 'was' : 'unused'}
          />
        </span>
      ))}
    </div>
  );
}

export function GateTransition({ gate, boxes }: { gate: GateVM | null; boxes: number }) {
  if (!gate) {
    return (
      <Panel title="Gate" subtitle="No gate was evaluated on this run">
        <p className="text-xs text-mist-400">
          The case never reached a plan, so there was nothing for policy to authorise.
        </p>
      </Panel>
    );
  }

  const e = gate.escalation;

  return (
    <Panel
      title="Gate Controller"
      subtitle="Policy decides permissions. The agent proposes; it never sets its own approval level."
      tone={gate.escalated ? 'alert' : 'default'}
      right={
        <span
          className={`rounded-lg border px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ${
            gate.autoApproved
              ? 'border-safe-500/50 bg-safe-900 text-safe-500'
              : 'border-watch-500/50 bg-watch-900 text-watch-500'
          }`}
        >
          Rung {gate.rung.number} · {gate.rung.name}
        </span>
      }
    >
      {e ? (
        <div
          className={`rounded-2xl border-2 border-watch-500/60 bg-watch-900/40 p-4 ${
            e.triggeredByConfidence ? 'escalation-pulse' : ''
          }`}
        >
          <div className="text-[11px] font-bold uppercase tracking-[0.2em] text-watch-500">
            Autonomy downgraded
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2">
            <div>
              <div className="text-[10px] uppercase tracking-wide text-mist-500">
                Would have been
              </div>
              <div className="mt-1 text-xl font-semibold text-mist-500 line-through decoration-mist-600 decoration-2">
                {e.wouldHaveBeenLabel}
              </div>
            </div>
            <div className="self-end pb-1.5 text-3xl leading-none text-watch-500">→</div>
            <div>
              <div className="text-[10px] uppercase tracking-wide text-watch-500">Now requires</div>
              <div className="mt-1 text-xl font-bold text-watch-500">{e.becameLabel}</div>
            </div>
          </div>

          <div className="mt-4 border-t border-watch-500/30 pt-3">
            <div className="text-[10px] uppercase tracking-wide text-mist-400">
              Triggered by {e.reasons.length === 1 ? 'this criterion' : 'these criteria'}
            </div>
            <ul className="mt-1.5 space-y-1">
              {e.reasons.map((r, i) => (
                <li key={i} className="flex items-start gap-2 text-sm text-mist-100">
                  <span className="mt-[3px] text-watch-500">▸</span>
                  <span>
                    {r}
                    {/confidence/i.test(r) && (
                      <span className="ml-2 rounded-lg bg-risk-900 px-1.5 py-[1px] text-[10px] font-semibold uppercase tracking-wide text-risk-500">
                        confidence
                      </span>
                    )}
                  </span>
                </li>
              ))}
            </ul>
            <p className="mt-2 text-[11px] leading-relaxed text-mist-400">
              {e.steps === 1 ? 'One criterion tripped, so the gate moved one step' : `${e.reasons.length} criteria tripped, so the gate moved ${e.steps} steps`}{' '}
              up the ladder for this rung. Nobody chose to escalate — the number fell out of the run
              and policy responded to it.
            </p>
          </div>
        </div>
      ) : (
        <div className="rounded-2xl border border-ink-900/10 bg-ink-900/[0.025] p-4">
          <div className="text-[11px] font-bold uppercase tracking-[0.2em] text-mist-400">
            No escalation
          </div>
          <div className="mt-2 text-xl font-semibold text-mist-100">{gate.requiredRoleLabel}</div>
          <p className="mt-2 text-[11px] leading-relaxed text-mist-400">
            {gate.rung.advisoryOnly
              ? 'Rung 1 is advisory and never blocks. Volume, cost and confidence are all skipped for it — escalating an advisory would train people to ignore the gate.'
              : `Nothing tripped: ${boxes} boxes is inside the 40-box limit, cost is inside the SGD 8,000 limit, and confidence is at or above 0.70.`}
          </p>
        </div>
      )}

      <div className="mt-4">
        <div className="text-[10px] uppercase tracking-[0.12em] text-mist-500">
          Escalation ladder for Rung {gate.rung.number}
        </div>
        <div className="mt-2">
          <Ladder gate={gate} />
        </div>
        <p className="mt-2 text-[11px] text-mist-500">{gate.rung.authority}.</p>
      </div>

      {gate.needsCustomer && (
        <p className="mt-4 rounded-lg border border-flag-500/40 bg-flag-900/40 px-3 py-2 text-[11px] leading-relaxed text-mist-300">
          This gate leaves the building. No level of internal seniority can decide for the shipping
          line — the ladder above is who releases the options, not who chooses between them.
        </p>
      )}
    </Panel>
  );
}
