/**
 * Demo mode: scripted playback of a captured run.
 *
 * Playback reveals a real trace one step at a time — it does not simulate
 * anything on top. Deterministic, so the same take records identically twice,
 * and it never touches a live API.
 *
 * Pausing at the approval gate is the point of the whole thing: the operator
 * decides, and each of the three decisions continues into a separately captured
 * run of the same event.
 */

import type { ConnectionVM } from '../adapters/types';
import { SPEEDS, type Playback, type Speed } from '../store/useConsole';

interface Props {
  playback: Playback | null;
  connections: ConnectionVM[];
  demoId: string;
  totalSteps: number;
  onStart: (id: string, speed?: Speed) => void;
  onStop: () => void;
  onPlay: () => void;
  onPause: () => void;
  onRestart: () => void;
  onSpeed: (s: Speed) => void;
  onStep: (dir: 1 | -1) => void;
  cinema: boolean;
  onCinema: (v: boolean) => void;
}

function Btn({
  children,
  onClick,
  disabled,
  primary,
  title,
}: {
  children: React.ReactNode;
  onClick: () => void;
  disabled?: boolean;
  primary?: boolean;
  title?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`rounded border px-2.5 py-1 text-[11px] font-semibold transition disabled:cursor-not-allowed disabled:opacity-35 ${
        primary
          ? 'border-flag-500/60 bg-flag-900 text-flag-500 hover:bg-flag-500 hover:text-ink-900'
          : 'border-ink-600 bg-ink-800 text-mist-300 hover:border-ink-500 hover:text-mist-100'
      }`}
    >
      {children}
    </button>
  );
}

export function DemoBar({
  playback,
  connections,
  demoId,
  totalSteps,
  onStart,
  onStop,
  onPlay,
  onPause,
  onRestart,
  onSpeed,
  onStep,
  cinema,
  onCinema,
}: Props) {
  if (!playback) {
    return (
      <div className="flex flex-wrap items-center gap-3 border-b border-ink-700 bg-ink-850 px-4 py-2">
        <span className="text-[10px] font-bold uppercase tracking-[0.16em] text-mist-500">
          Demo
        </span>
        <Btn primary onClick={() => onStart(demoId, 4)}>
          ▶ Play the failure-injection run
        </Btn>
        <span className="text-[11px] text-mist-500">
          Slot lookup times out, falls back to stale cache, confidence drops, the gate escalates.
        </span>
        <div className="ml-auto flex items-center gap-2">
          <span className="text-[10px] uppercase tracking-wide text-mist-600">or replay</span>
          <select
            className="rounded border border-ink-600 bg-ink-800 px-2 py-1 text-[11px] text-mist-300"
            defaultValue=""
            onChange={(e) => {
              if (e.target.value) onStart(e.target.value, 4);
              e.target.value = '';
            }}
          >
            <option value="" disabled>
              any connection…
            </option>
            {connections.map((c) => (
              <option key={c.id} value={c.id}>
                {c.id} — {c.severityLabel}
              </option>
            ))}
          </select>
        </div>
      </div>
    );
  }

  const progress = totalSteps ? (playback.cursor / totalSteps) * 100 : 0;

  return (
    <div className="border-b border-ink-700 bg-ink-850">
      <div className="flex flex-wrap items-center gap-2 px-4 py-2">
        <span className="text-[10px] font-bold uppercase tracking-[0.16em] text-flag-500">
          Replaying
        </span>
        <code className="font-mono text-[11px] text-mist-100">{playback.id}</code>

        <div className="mx-2 flex items-center gap-1">
          <Btn onClick={() => onStep(-1)} disabled={playback.cursor === 0} title="Step back">
            ◀
          </Btn>
          {playback.playing ? (
            <Btn onClick={onPause} disabled={playback.awaiting} title="Pause">
              ❚❚
            </Btn>
          ) : (
            <Btn onClick={onPlay} disabled={playback.awaiting || playback.finished} title="Play">
              ▶
            </Btn>
          )}
          <Btn onClick={() => onStep(1)} disabled={playback.finished} title="Step forward">
            ▶❙
          </Btn>
          <Btn onClick={onRestart} title="Restart from the first step">
            ↺
          </Btn>
        </div>

        <div className="flex items-center gap-1">
          <span className="text-[10px] uppercase tracking-wide text-mist-600">speed</span>
          {SPEEDS.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => onSpeed(s)}
              className={`rounded border px-1.5 py-0.5 text-[10px] font-semibold transition ${
                playback.speed === s
                  ? 'border-flag-500/60 bg-flag-900 text-flag-500'
                  : 'border-ink-700 text-mist-500 hover:text-mist-300'
              }`}
            >
              {s}×
            </button>
          ))}
        </div>

        <span className="tnum text-[11px] text-mist-500">
          step {playback.cursor}/{totalSteps}
        </span>

        {playback.awaiting && (
          <span className="rounded border border-watch-500/60 bg-watch-900 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-watch-500">
            waiting for a decision
          </span>
        )}
        {playback.branch && (
          <span className="rounded border border-ink-600 bg-ink-800 px-2 py-0.5 text-[10px] uppercase tracking-wide text-mist-400">
            branch: {playback.branch}
          </span>
        )}

        <Btn
          onClick={() => onCinema(!cinema)}
          primary={cinema}
          title="Full-screen layout sized for a screen recording"
        >
          {cinema ? '▣ Cinema on' : '▢ Cinema'}
        </Btn>
        <Btn onClick={onStop}>Exit replay</Btn>
      </div>

      <div className="h-[3px] bg-ink-800">
        <div
          className="h-full bg-flag-500 transition-[width] duration-200 ease-linear"
          style={{ width: `${progress}%` }}
        />
      </div>
    </div>
  );
}
