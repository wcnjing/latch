/**
 * Console state: the queue, the selection, and trace playback.
 *
 * Playback is the mechanism behind both Step 4 (live behaviour) and Step 5
 * (demo mode). A connection being "live" is modelled as its trace revealed up
 * to a cursor: truncate the steps, hand the shortened bundle to the adapter,
 * and the view model comes back describing the connection as it was at that
 * moment. Nothing is simulated on top — the states, the confidence and the
 * gate all appear exactly when B recorded them.
 *
 * That is also why connections update in place rather than appending: the
 * queue is keyed on connection id, and a replay replaces the entry under the
 * same key.
 *
 * The approval pause is the one point where playback waits for a human. Three
 * branches were captured for that decision (approve / decline / let it lapse),
 * each a real run of the same event, so whichever the operator picks the
 * console continues into a recorded trace rather than a narrated one.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { byCriticality, toViewModel } from '../adapters/toViewModel';
import type { RiskState, StateChangeStep } from '../contracts/latch';
import type { ConnectionVM, FixtureBundle } from '../adapters/types';
import {
  BUNDLES,
  DEMO_BUNDLE,
  DEMO_DECLINED_BUNDLE,
  DEMO_LAPSED_BUNDLE,
} from '../data/fixtures';

/** config.py has no internal approval window. This is the console's, and the UI says so. */
export const APPROVAL_WINDOW_MIN = 15;

export const SPEEDS = [1, 4, 12, 60] as const;
export type Speed = (typeof SPEEDS)[number];

export type Branch = 'approved' | 'declined' | 'lapsed';

const BRANCH_BUNDLE: Record<Branch, FixtureBundle> = {
  approved: DEMO_BUNDLE,
  declined: DEMO_DECLINED_BUNDLE,
  lapsed: DEMO_LAPSED_BUNDLE,
};

export interface Playback {
  /** Connection id being replayed. */
  id: string;
  /** How many trace steps are revealed. */
  cursor: number;
  playing: boolean;
  speed: Speed;
  /** Paused at an approval gate, waiting for a person. */
  awaiting: boolean;
  /** Seconds left on the console-side window. Null when not awaiting. */
  secondsLeft: number | null;
  /** Which recorded branch we are in. Null until the operator decides. */
  branch: Branch | null;
  /** True once the cursor has reached the end. */
  finished: boolean;
}

/* -------------------------------------------------------------------------
 * Truncation
 * ---------------------------------------------------------------------- */

const hasGate = (b: FixtureBundle, upTo: number) =>
  b.trace.steps.slice(0, upTo).some((s) => s.type === 'gate');

/**
 * A bundle as it stood after `n` steps.
 *
 * The outcome and the captured `GateDecision` are withheld until the steps
 * that produce them have been revealed, so nothing on screen runs ahead of the
 * trace. State comes from the last `state_change`, which is how B records it.
 */
function truncate(bundle: FixtureBundle, n: number): FixtureBundle {
  const steps = bundle.trace.steps.slice(0, n);
  const complete = n >= bundle.trace.steps.length;
  const lastStateChange = [...steps]
    .reverse()
    .find((s): s is StateChangeStep => s.type === 'state_change');

  return {
    ...bundle,
    trace: {
      ...bundle.trace,
      steps,
      outcome: complete
        ? bundle.trace.outcome
        : { ...bundle.trace.outcome, resolution: null, service_success: null },
    },
    result: complete
      ? bundle.result
      : {
          state: (lastStateChange?.to_state ?? 'detected') as RiskState,
          resolution: null,
          service_success: null,
        },
    gate: hasGate(bundle, n) ? bundle.gate : null,
  };
}

/**
 * Pacing. Deliberate rather than uniform: a tool timing out and a confidence
 * score landing are the beats a viewer needs time to read, and a state change
 * is scaffolding. Fixed values, so two recordings of the same take match.
 */
function stepDelayMs(kind: string): number {
  switch (kind) {
    case 'error':
    case 'confidence':
      return 2200;
    case 'gate':
    case 'decision':
      return 1800;
    case 'tool_call':
    case 'external_gate':
      return 1100;
    case 'observation':
      return 900;
    case 'model_call':
      return 700;
    default:
      return 550;
  }
}

/** True when the next step is the gate resolving — the moment to hand over. */
function pausesBefore(bundle: FixtureBundle, cursor: number): boolean {
  const next = bundle.trace.steps[cursor];
  if (!next) return false;
  if (next.type === 'gate') {
    const status = (next as { status: string }).status;
    return status === 'approved' || status === 'rejected' || status === 'lapsed';
  }
  // The lapsed branch moves state before it writes the gate step.
  return next.type === 'state_change' && (next as { to_state: string }).to_state === 'lapsed';
}

/* -------------------------------------------------------------------------
 * The hook
 * ---------------------------------------------------------------------- */

export interface ConsoleState {
  connections: ConnectionVM[];
  selected: ConnectionVM | null;
  selectedId: string | null;
  select: (id: string) => void;

  playback: Playback | null;
  /** The bundle currently being replayed, at full length. */
  startPlayback: (id: string, speed?: Speed) => void;
  stopPlayback: () => void;
  play: () => void;
  pause: () => void;
  restart: () => void;
  setSpeed: (s: Speed) => void;
  stepForward: () => void;
  stepBack: () => void;
  decide: (branch: Branch) => void;

  /** Connection ids that can be replayed (every captured trace). */
  replayable: string[];
  demoId: string;
}

export function useConsole(): ConsoleState {
  const baseline = useMemo(() => BUNDLES.map(toViewModel), []);
  const [selectedId, setSelectedId] = useState<string | null>(
    () => [...baseline].sort(byCriticality)[0]?.id ?? null,
  );
  const [playback, setPlayback] = useState<Playback | null>(null);

  const bundleFor = useCallback(
    (id: string, branch: Branch | null): FixtureBundle | null => {
      if (id === DEMO_BUNDLE.event.connection_id) {
        return BRANCH_BUNDLE[branch ?? 'approved'];
      }
      return BUNDLES.find((b) => b.event.connection_id === id) ?? null;
    },
    [],
  );

  /* --- the queue, with the replayed connection swapped in place ---------- */

  const connections = useMemo(() => {
    if (!playback) return [...baseline].sort(byCriticality);
    const bundle = bundleFor(playback.id, playback.branch);
    if (!bundle) return [...baseline].sort(byCriticality);
    const live = toViewModel(truncate(bundle, playback.cursor));
    return baseline.map((c) => (c.id === playback.id ? live : c)).sort(byCriticality);
  }, [baseline, playback, bundleFor]);

  const selected = useMemo(
    () => connections.find((c) => c.id === selectedId) ?? null,
    [connections, selectedId],
  );

  /* --- advancing the cursor --------------------------------------------- */

  const timer = useRef<number | null>(null);

  useEffect(() => {
    if (timer.current !== null) {
      window.clearTimeout(timer.current);
      timer.current = null;
    }
    if (!playback?.playing || playback.awaiting || playback.finished) return;

    const bundle = bundleFor(playback.id, playback.branch);
    if (!bundle) return;

    const next = bundle.trace.steps[playback.cursor];
    if (!next) {
      setPlayback((p) => (p ? { ...p, playing: false, finished: true } : p));
      return;
    }

    const delay = stepDelayMs(next.type) / playback.speed;
    timer.current = window.setTimeout(() => {
      setPlayback((p) => {
        if (!p) return p;
        const b = bundleFor(p.id, p.branch);
        if (!b) return p;
        const cursor = p.cursor + 1;
        const finished = cursor >= b.trace.steps.length;
        const awaiting = !finished && p.branch === null && pausesBefore(b, cursor);
        return {
          ...p,
          cursor,
          finished,
          awaiting,
          secondsLeft: awaiting ? APPROVAL_WINDOW_MIN * 60 : null,
          playing: !finished,
        };
      });
    }, delay);

    return () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    };
  }, [playback, bundleFor]);

  /* --- the approval countdown ------------------------------------------- */

  useEffect(() => {
    if (!playback?.awaiting || playback.secondsLeft === null) return;
    const id = window.setInterval(() => {
      setPlayback((p) => {
        if (!p || !p.awaiting || p.secondsLeft === null) return p;
        const secondsLeft = p.secondsLeft - p.speed;
        if (secondsLeft > 0) return { ...p, secondsLeft };
        // Nobody signed. Auto-decline into the recorded lapsed branch.
        return { ...p, branch: 'lapsed', awaiting: false, secondsLeft: 0, playing: true };
      });
    }, 1000);
    return () => window.clearInterval(id);
  }, [playback?.awaiting, playback?.secondsLeft === null, playback?.speed]);

  /* --- controls ---------------------------------------------------------- */

  const startPlayback = useCallback(
    (id: string, speed: Speed = 4) => {
      setSelectedId(id);
      setPlayback({
        id,
        cursor: 0,
        playing: true,
        speed,
        awaiting: false,
        secondsLeft: null,
        branch: null,
        finished: false,
      });
    },
    [],
  );

  const stopPlayback = useCallback(() => setPlayback(null), []);
  const play = useCallback(
    () => setPlayback((p) => (p && !p.awaiting ? { ...p, playing: true } : p)),
    [],
  );
  const pause = useCallback(() => setPlayback((p) => (p ? { ...p, playing: false } : p)), []);
  const restart = useCallback(
    () =>
      setPlayback((p) =>
        p
          ? {
              ...p,
              cursor: 0,
              playing: true,
              awaiting: false,
              secondsLeft: null,
              branch: null,
              finished: false,
            }
          : p,
      ),
    [],
  );
  const setSpeed = useCallback((speed: Speed) => setPlayback((p) => (p ? { ...p, speed } : p)), []);

  const stepForward = useCallback(() => {
    setPlayback((p) => {
      if (!p) return p;
      const b = bundleFor(p.id, p.branch);
      if (!b) return p;
      const cursor = Math.min(p.cursor + 1, b.trace.steps.length);
      const finished = cursor >= b.trace.steps.length;
      const awaiting = !finished && p.branch === null && pausesBefore(b, cursor);
      return {
        ...p,
        cursor,
        finished,
        playing: false,
        awaiting,
        secondsLeft: awaiting ? APPROVAL_WINDOW_MIN * 60 : null,
      };
    });
  }, [bundleFor]);

  const stepBack = useCallback(() => {
    setPlayback((p) =>
      p
        ? {
            ...p,
            cursor: Math.max(p.cursor - 1, 0),
            playing: false,
            finished: false,
            awaiting: false,
            secondsLeft: null,
          }
        : p,
    );
  }, []);

  const decide = useCallback((branch: Branch) => {
    setPlayback((p) =>
      p ? { ...p, branch, awaiting: false, secondsLeft: null, playing: true } : p,
    );
  }, []);

  return {
    connections,
    selected,
    selectedId,
    select: setSelectedId,
    playback,
    startPlayback,
    stopPlayback,
    play,
    pause,
    restart,
    setSpeed,
    stepForward,
    stepBack,
    decide,
    replayable: BUNDLES.map((b) => b.event.connection_id),
    demoId: DEMO_BUNDLE.event.connection_id,
  };
}
