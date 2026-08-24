/**
 * LATCH operations console.
 *
 * Three columns: what is at risk, what is happening to the selected
 * connection, and how much to trust the agent about it. The right-hand column
 * is deliberately the widest thing after the detail pane — confidence is the
 * argument, not a decoration on it.
 */

import type { ReactNode } from 'react';
import { useMemo, useState } from 'react';

import { toViewModel } from './adapters/toViewModel';
import { ApprovalPanel } from './components/ApprovalPanel';
import { ConfidencePanel } from './components/ConfidencePanel';
import { ConnectionDetail } from './components/ConnectionDetail';
import { DemoBar } from './components/DemoBar';
import { DemoStage } from './components/DemoStage';
import { GateTransition } from './components/GateTransition';
import { RiskQueue } from './components/RiskQueue';
import { TraceTimeline } from './components/TraceTimeline';
import { Placeholder } from './components/ui';
import { BUNDLES, DEMO_BUNDLE, DEMO_DECLINED_BUNDLE, DEMO_LAPSED_BUNDLE } from './data/fixtures';
import { useConsole } from './store/useConsole';

const DATA_BASIS =
  'real vessel movement data + derived arrival estimates + synthetic transhipment connections';

/** One headline figure as its own inset tile, matching the reference's readouts. */
function HeadlineStat({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="glass-inset rounded-xl px-3 py-1.5">
      <div className="text-[10px] uppercase tracking-wide text-mist-500">{label}</div>
      <div className="mt-0.5 flex h-5 items-center">{children}</div>
    </div>
  );
}

function Header({ connections }: { connections: ReturnType<typeof useConsole>['connections'] }) {
  // `=== true` / `=== false` rather than truthiness: these are now tri-state,
  // and an outcome B could not classify must not quietly land in either column
  // of a headline metric.
  const served = connections.filter((c) => c.outcome?.serviceSuccess === true).length;
  const closed = connections.filter((c) => c.outcome?.excludedFromMetric === false).length;
  const spend = connections.reduce((sum, c) => sum + c.cost.usd, 0);

  return (
    <header className="glass m-3 mb-0 rounded-2xl">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 px-5 py-3.5">
        <div>
          <h1 className="text-base font-bold tracking-[0.22em] text-mist-100">LATCH</h1>
          <p className="text-[10px] uppercase tracking-[0.14em] text-mist-500">
            Transhipment connection resolution · PSA Singapore
          </p>
        </div>

        <div className="flex flex-wrap gap-2">
          <HeadlineStat label="Served / at risk">
            <span className="tnum text-sm font-semibold text-mist-100">
              {served}/{closed}
            </span>
            <span className="ml-2 text-[10px] font-normal text-mist-500">this session</span>
          </HeadlineStat>
          <HeadlineStat label="Detection rate">
            <Placeholder what="A's evaluation has not run." />
          </HeadlineStat>
          <HeadlineStat label="Connections rescued">
            <Placeholder what="A's evaluation has not run." />
          </HeadlineStat>
          <HeadlineStat label="Agent spend">
            <span className="tnum text-sm font-semibold text-mist-100">${spend.toFixed(4)}</span>
          </HeadlineStat>
        </div>
      </div>

      {/* The data-honesty statement. Full sentence, always, never abbreviated. */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-white/8 px-5 py-2 text-[10px] leading-relaxed">
        <span className="rounded-full border border-watch-500/50 bg-watch-500/18 px-2 py-[2px] font-bold uppercase tracking-wider text-watch-500">
          Data basis
        </span>
        <span className="text-mist-400">{DATA_BASIS}.</span>
        <span className="text-mist-600">
          Container connections, terminal assignments, box counts and loading cut-offs are
          simulated. Model responses in these runs are scripted — no model was consulted.
        </span>
      </div>
    </header>
  );
}

export default function App() {
  const console_ = useConsole();
  const { connections, selected, selectedId, playback } = console_;
  const [cinema, setCinema] = useState(false);

  /* The full trace of whatever is being replayed, so the timeline can show the
     steps that have not been revealed yet as greyed rather than absent. */
  const fullTimeline = useMemo(() => {
    if (!playback || !selected || selected.id !== playback.id) return undefined;
    const bundle =
      playback.id === DEMO_BUNDLE.event.connection_id
        ? playback.branch === 'declined'
          ? DEMO_DECLINED_BUNDLE
          : playback.branch === 'lapsed'
            ? DEMO_LAPSED_BUNDLE
            : DEMO_BUNDLE
        : BUNDLES.find((b) => b.event.connection_id === playback.id);
    return bundle ? toViewModel(bundle).timeline : undefined;
  }, [playback, selected]);

  const totalSteps = fullTimeline?.length ?? selected?.timeline.length ?? 0;

  return (
    <div className="flex h-full flex-col">
      {/* The lit ground every glass surface refracts. Fixed and behind
          everything, so scrolling a column does not drag the light with it. */}
      <div className="ground" aria-hidden />

      <Header connections={connections} />

      <DemoBar
        playback={playback}
        connections={connections}
        demoId={console_.demoId}
        totalSteps={totalSteps}
        onStart={console_.startPlayback}
        onStop={console_.stopPlayback}
        onPlay={console_.play}
        onPause={console_.pause}
        onRestart={console_.restart}
        onSpeed={console_.setSpeed}
        onStep={(dir) => (dir === 1 ? console_.stepForward() : console_.stepBack())}
        cinema={cinema}
        onCinema={setCinema}
      />

      {cinema && playback && selected && selected.id === playback.id ? (
        <DemoStage c={selected} playback={playback} onDecide={console_.decide} />
      ) : (
      <div className="grid min-h-0 flex-1 grid-cols-[300px_minmax(0,1fr)_440px] gap-3 p-3">
        <RiskQueue
          connections={connections}
          selectedId={selectedId}
          onSelect={console_.select}
          replayingId={playback?.id ?? null}
        />

        <main className="min-h-0 overflow-y-auto pr-1">
          {selected ? (
            <ConnectionDetail c={selected} />
          ) : (
            <p className="text-sm text-mist-500">Select a connection.</p>
          )}
        </main>

        <aside className="min-h-0 space-y-3 overflow-y-auto pr-1">
          {selected && (
            <>
              <ApprovalPanel
                approval={selected.approval}
                gate={selected.gate}
                awaiting={playback?.awaiting === true && playback.id === selected.id}
                secondsLeft={playback?.secondsLeft ?? null}
                speed={playback?.speed ?? 1}
                decided={playback?.id === selected.id ? (playback?.branch ?? null) : null}
                onDecide={console_.decide}
              />
              <ConfidencePanel c={selected.confidence} />
              <GateTransition gate={selected.gate} boxes={selected.boxes} />
              <TraceTimeline
                events={selected.timeline}
                allEvents={fullTimeline}
                cost={{ usd: selected.cost.usd, modelCalls: selected.cost.modelCalls }}
              />

              {/* Provenance sits at the bottom of the rail rather than in a
                  modal: it is context, but it must always be reachable. */}
              <div className="glass-raised rounded-2xl p-4 text-[11px] leading-relaxed text-mist-500">
                <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-mist-400">
                  Provenance
                </div>
                <p className="mt-2">{selected.provenance.dataBasis}.</p>
                <p className="mt-1.5">
                  Terminal assignment:{' '}
                  <span className="text-mist-300">
                    {selected.provenance.terminalResolutionLabel}
                  </span>
                  . This field feeds the confidence calculation directly, so the synthetic origin
                  lowers the agent's own certainty rather than being a caption.
                </p>
                {selected.provenance.anySynthetic && (
                  <p className="mt-1.5">
                    Simulated here: {selected.provenance.syntheticFields.join(', ')}.
                  </p>
                )}
                <p className="mt-1.5">{selected.provenance.transferScenario}.</p>
                {selected.provenance.authored && (
                  <p className="mt-2 rounded border border-watch-500/40 bg-watch-900/40 px-2 py-1.5 text-watch-500">
                    <span className="font-semibold uppercase tracking-wide">Authored fixture. </span>
                    {selected.provenance.authoredBecause}
                  </p>
                )}
                <p className="mt-2 text-mist-600">{selected.provenance.modelDisclosure}</p>
              </div>
            </>
          )}
        </aside>
      </div>
      )}
    </div>
  );
}
