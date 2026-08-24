/**
 * Approve, decline, or let it lapse.
 *
 * The consequence of inaction is stated before the controls, not after them,
 * because that is the piece an operator under time pressure will not go looking
 * for.
 *
 * The countdown states whose it is. B now records `window_min` and
 * `expires_at` on the gate step at the moment the approval is requested
 * (REQUEST TO B #2, landed), so on a current trace the clock is policy. On an
 * older trace it falls back to a console-side timer and says so instead —
 * the label follows the data, and is never decoration.
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

function inactionCopy(approval: ApprovalVM, gate: GateVM) {
  if (approval.handoff) {
    return 'If the vessels remain in different terminals, operations must manage the transfer risk another way.';
  }
  if (gate.needsCustomer || approval.role === 'customer') {
    return 'If the shipping line does not respond before the window closes, no onward option is selected.';
  }
  return 'If this plan is not approved before the window closes, nothing is booked and the boxes move to the next available service.';
}

const OUTCOME_COPY: Record<Branch, { label: string; body: string; tone: string }> = {
  approved: {
    label: 'Approved',
    body: 'The transfer was booked and the connection held.',
    tone: 'border-safe-500/50 bg-safe-900 text-safe-500',
  },
  declined: {
    label: 'Declined',
    body: 'The recovery plan was not taken. Nothing was booked and the boxes moved to the next available service.',
    tone: 'border-risk-500/50 bg-risk-900 text-risk-500',
  },
  lapsed: {
    label: 'Auto-declined — window closed',
    body: 'No decision was recorded before the window closed. Nothing was booked and the boxes moved to the next available service.',
    tone: 'border-risk-500/50 bg-risk-900 text-risk-500',
  },
};

function Countdown({
  seconds,
  windowMin,
  speed,
  source,
}: {
  seconds: number;
  windowMin: number;
  speed: Speed;
  source: 'policy' | 'console-timer';
}) {
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
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-ink-900/[0.05]">
        <div
          className={`h-full transition-[width] duration-1000 ease-linear ${urgent ? 'bg-risk-500' : 'bg-watch-500'}`}
          style={{ width: `${fraction * 100}%` }}
        />
      </div>
      <p className="mt-1.5 text-[10px] leading-relaxed text-mist-500">
        {windowMin}-minute window{speed > 1 && <> · running at {speed}×</>}.{' '}
        {source === 'policy'
          ? 'Deadline recorded when approval was requested.'
          : 'This captured run did not include a recorded approval deadline.'}
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
      <Panel title="Planner review" subtitle={`${approval.roleLabel} owns this recommendation`}>
        <div className="rounded-lg border border-flag-500/40 bg-flag-900/40 p-3">
          <p className="text-sm text-mist-100">
            This is a notification for the{' '}
            <span className="font-semibold text-flag-500">{approval.roleLabel}</span>, not a request
            for permission.
          </p>
          <p className="mt-2 text-[11px] leading-relaxed text-mist-400">
            {inactionCopy(approval, gate)}
          </p>
        </div>
        <p className="mt-3 text-[11px] leading-relaxed text-mist-500">
          Share the recommendation with {approval.roleLabel}; no booking is made from this screen.
        </p>
      </Panel>
    );
  }

  /* --- Rung 4: the decision leaves the building ------------------------ */
  if (approval.role === 'customer') {
    return (
      <Panel title="Shipping line decision" subtitle="The customer owns the final choice">
        <p className="text-sm text-mist-100">
          Ranked options have been released to the line. PSA cannot choose for them at any level of
          seniority.
        </p>
        <p className="mt-2 text-[11px] leading-relaxed text-mist-400">
          {inactionCopy(approval, gate)}
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
      subtitle={`${approval.roleLabel} must approve the recommended plan`}
      tone={awaiting ? 'alert' : 'default'}
      right={
        <span className="rounded-lg border border-watch-500/50 bg-watch-900 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-watch-500">
          {approval.roleLabel}
        </span>
      }
    >
      <div className="rounded-lg border border-ink-900/10 bg-ink-900/[0.025] px-3 py-2">
        <div className="text-[10px] uppercase tracking-[0.12em] text-mist-500">
          If no decision is made
        </div>
        <p className="mt-1 text-xs leading-relaxed text-mist-200">{inactionCopy(approval, gate)}</p>
      </div>

      {awaiting && secondsLeft !== null && approval.countdown && (
        <div className="mt-4">
          <Countdown
            seconds={secondsLeft}
            windowMin={approval.countdown.windowMin}
            source={approval.countdown.source}
            speed={speed}
          />
        </div>
      )}

      {awaiting ? (
        <div className="mt-4 flex gap-2">
          <button
            type="button"
            onClick={() => onDecide('approved')}
            className="flex-1 rounded-lg border border-accent-500 bg-accent-500 px-3 py-2.5 text-sm font-semibold text-white transition hover:bg-accent-600"
          >
            Approve plan
          </button>
          <button
            type="button"
            onClick={() => onDecide('declined')}
            className="flex-1 rounded-lg border border-risk-500/35 bg-white px-3 py-2.5 text-sm font-semibold text-risk-500 transition hover:bg-risk-900"
          >
            Decline
          </button>
        </div>
      ) : settled ? (
        <div className={`mt-4 rounded-lg border px-3 py-2.5 ${OUTCOME_COPY[settled].tone}`}>
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

    </Panel>
  );
}
