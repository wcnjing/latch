/**
 * Approve, decline, or let it lapse.
 *
 * The consequence of inaction is stated before the controls, not after them,
 * because that is the piece an operator under time pressure will not go looking
 * for.
 *
 * The countdown is this console's, and it says so. B carries no approval
 * deadline — `GateStep.latency_s` records how long an approval took, after the
 * fact, and there is no window constant for internal approvals the way there is
 * for the customer gate. See CONTRACTS.md §7 and REQUEST TO B #2.
 *
 * Rung 1 gets no approve control at all. It is advisory: it surfaces a number
 * to the planner who was already going to decide, and changes nothing about
 * this connection on its own. Offering an approve button there would imply an
 * authority the system does not claim.
 */

import type { ApprovalVM, GateVM } from '../adapters/types';
import { clock } from '../lib/format';
import type { Branch, Speed } from '../store/useConsole';
import { Panel } from './ui';

interface Props {
  approval: ApprovalVM | null;
  gate: GateVM | null;
  awaiting: boolean;
  secondsLeft: number | null;
  speed: Speed;
  decided: Branch | null;
  onDecide: (branch: Branch) => void;
}

const OUTCOME_COPY: Record<Branch, { label: string; body: string; tone: string }> = {
  approved: {
    label: 'Approved',
    body: 'The transfer was booked and the connection held.',
    tone: 'border-safe-500/50 bg-safe-900 text-safe-500',
  },
  declined: {
    label: 'Declined',
    body: 'The action was not taken. The default fired and the boxes rolled to the next service. B records this as INTERNALLY_DECLINED: a PSA decision, not the line’s.',
    tone: 'border-risk-500/50 bg-risk-900 text-risk-500',
  },
  lapsed: {
    label: 'Auto-declined — window closed',
    body: 'Nobody signed inside the window. The default action fired, and B recorded the outcome as APPROVAL_LAPSED — an internal lapse, kept distinct from a shipping line that never replied.',
    tone: 'border-risk-500/50 bg-risk-900 text-risk-500',
  },
};

function Countdown({ seconds, windowMin, speed }: { seconds: number; windowMin: number; speed: Speed }) {
  const total = windowMin * 60;
  const fraction = Math.max(0, Math.min(1, seconds / total));
  const urgent = fraction < 0.25;

  return (
    <div>
      <div className="flex items-baseline justify-between">
        <span className="text-[10px] uppercase tracking-[0.12em] text-mist-500">
          Auto-declines in
        </span>
        <span className={`tnum text-3xl font-bold ${urgent ? 'text-risk-500' : 'text-watch-500'}`}>
          {clock(seconds)}
        </span>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-ink-750">
        <div
          className={`h-full transition-[width] duration-1000 ease-linear ${urgent ? 'bg-risk-500' : 'bg-watch-500'}`}
          style={{ width: `${fraction * 100}%` }}
        />
      </div>
      <p className="mt-1.5 text-[10px] leading-relaxed text-mist-500">
        {windowMin}-minute window{speed > 1 && <> · running at {speed}×</>}. This countdown is
        rendered by the console — B records no approval deadline.
      </p>
    </div>
  );
}

export function ApprovalPanel({
  approval,
  gate,
  awaiting,
  secondsLeft,
  speed,
  decided,
  onDecide,
}: Props) {
  if (!approval || !gate) return null;

  /* --- Rung 1: hand off, never approve -------------------------------- */
  if (approval.handoff) {
    return (
      <Panel title="Advisory" subtitle="Rung 1 — nothing here can be executed by the agent">
        <div className="rounded border border-flag-500/40 bg-flag-900/40 p-3">
          <p className="text-sm text-mist-100">
            This is a notification for the{' '}
            <span className="font-semibold text-flag-500">{approval.roleLabel}</span>, not a request
            for permission.
          </p>
          <p className="mt-2 text-[11px] leading-relaxed text-mist-400">
            {approval.ifNothingHappens}
          </p>
        </div>
        <div className="mt-3 flex gap-2">
          <button
            type="button"
            className="rounded border border-ink-600 bg-ink-750 px-3 py-2 text-xs font-semibold text-mist-100 transition hover:border-flag-500/60 hover:bg-ink-700"
          >
            Acknowledge
          </button>
          <button
            type="button"
            className="rounded border border-flag-500/50 bg-flag-900 px-3 py-2 text-xs font-semibold text-flag-500 transition hover:bg-flag-900/70"
          >
            Hand off to {approval.roleLabel}
          </button>
        </div>
        <p className="mt-3 text-[11px] leading-relaxed text-mist-500">
          The most valuable rung is the least autonomous one. Removing the transfer entirely is
          worth more than booking it well — and it is the one action the agent cannot take.
        </p>
      </Panel>
    );
  }

  /* --- Rung 4: the decision leaves the building ------------------------ */
  if (approval.role === 'customer') {
    return (
      <Panel title="External gate" subtitle="Rung 4 — the shipping line owns this decision">
        <p className="text-sm text-mist-100">
          Ranked options have been released to the line. PSA cannot choose for them at any level of
          seniority.
        </p>
        <p className="mt-2 text-[11px] leading-relaxed text-mist-400">
          {approval.ifNothingHappens}
        </p>
        {approval.countdown && (
          <p className="mt-2 text-[11px] text-mist-500">{approval.countdown.note}</p>
        )}
      </Panel>
    );
  }

  /* --- Rung 3: a real signature ---------------------------------------- */
  const settled = decided ?? (gate.status === 'approved'
    ? 'approved'
    : gate.status === 'rejected'
      ? 'declined'
      : gate.status === 'lapsed'
        ? 'lapsed'
        : null);

  return (
    <Panel
      title="Approval required"
      subtitle={`Rung ${gate.rung.number} · ${gate.rung.name}`}
      tone={awaiting ? 'alert' : 'default'}
      right={
        <span className="rounded border border-watch-500/50 bg-watch-900 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-watch-500">
          {approval.roleLabel}
        </span>
      }
    >
      <div className="rounded border border-ink-700 bg-ink-800 px-3 py-2">
        <div className="text-[10px] uppercase tracking-[0.12em] text-mist-500">
          If nobody acts
        </div>
        <p className="mt-1 text-xs leading-relaxed text-mist-200">{approval.ifNothingHappens}</p>
      </div>

      {awaiting && secondsLeft !== null && approval.countdown && (
        <div className="mt-4">
          <Countdown
            seconds={secondsLeft}
            windowMin={approval.countdown.windowMin}
            speed={speed}
          />
        </div>
      )}

      {awaiting ? (
        <div className="mt-4 flex gap-2">
          <button
            type="button"
            onClick={() => onDecide('approved')}
            className="flex-1 rounded border border-safe-500/60 bg-safe-900 px-3 py-2.5 text-sm font-bold text-safe-500 transition hover:bg-safe-500 hover:text-ink-900"
          >
            Approve as {approval.roleLabel}
          </button>
          <button
            type="button"
            onClick={() => onDecide('declined')}
            className="flex-1 rounded border border-risk-500/60 bg-risk-900 px-3 py-2.5 text-sm font-bold text-risk-500 transition hover:bg-risk-500 hover:text-ink-900"
          >
            Decline
          </button>
        </div>
      ) : settled ? (
        <div className={`mt-4 rounded border px-3 py-2.5 ${OUTCOME_COPY[settled].tone}`}>
          <div className="text-[10px] font-bold uppercase tracking-[0.14em]">
            {OUTCOME_COPY[settled].label}
          </div>
          <p className="mt-1 text-[11px] leading-relaxed text-mist-300">
            {OUTCOME_COPY[settled].body}
          </p>
          {gate.latencyS ? (
            <p className="tnum mt-1 text-[10px] text-mist-500">
              Signature took {gate.latencyS.toFixed(0)}s
            </p>
          ) : null}
        </div>
      ) : (
        <p className="mt-4 text-xs text-mist-500">
          This run is complete. Replay it to take the decision yourself.
        </p>
      )}

      <p className="mt-3 text-[11px] leading-relaxed text-mist-500">
        Every branch of this decision is a recorded run of the same event — approve, decline and
        lapse were each captured from B's pipeline, so whichever you pick the console continues into
        a real trace rather than a description of one.
      </p>
    </Panel>
  );
}
