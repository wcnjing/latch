/** LATCH operations console. */

import { useEffect, useMemo, useState } from 'react';

import { toViewModel } from './adapters/toViewModel';
import { ApprovalPanel } from './components/ApprovalPanel';
import { ConnectionDetail } from './components/ConnectionDetail';
import { DemoBar } from './components/DemoBar';
import { DemoStage } from './components/DemoStage';
import { OverviewPage } from './components/OverviewPage';
import { ProductTour } from './components/ProductTour';
import { RiskQueue } from './components/RiskQueue';
import { BUNDLES, DEMO_BUNDLE, DEMO_DECLINED_BUNDLE, DEMO_LAPSED_BUNDLE } from './data/fixtures';
import { useConsole } from './store/useConsole';

type Page = 'overview' | 'connections' | 'replay';

function Topbar({
  page,
  onPage,
  onGuide,
}: {
  page: Page;
  onPage: (page: Page) => void;
  onGuide: () => void;
}) {
  return (
    <header className="topbar">
      <button type="button" className="wordmark" onClick={() => onPage('overview')}>
        LATCH
      </button>
      <span className="hidden h-4 w-px bg-ink-900/12 sm:block" />
      <span className="hidden text-[12px] text-mist-500 sm:inline">Operations Console</span>

      <nav className="primary-nav" aria-label="Primary navigation">
        {([
          ['overview', 'Overview'],
          ['connections', 'Connections'],
          ['replay', 'Replay'],
        ] as const).map(([id, label]) => (
          <button
            key={id}
            type="button"
            aria-current={page === id ? 'page' : undefined}
            onClick={() => onPage(id)}
            className={page === id ? 'primary-nav-active' : ''}
          >
            {label}
          </button>
        ))}
      </nav>

      <button type="button" className="guide-button" onClick={onGuide}>
        <span aria-hidden>?</span>
        Guide
      </button>

      <div className="hidden items-center gap-2 text-[11px] md:flex">
        <span className="font-medium text-mist-300">PSA Singapore</span>
        <span className="text-mist-600">·</span>
        <span className="text-mist-500">Scenario data</span>
      </div>
    </header>
  );
}

export default function App() {
  const console_ = useConsole();
  const { connections, selected, selectedId, playback } = console_;
  const [page, setPage] = useState<Page>('overview');
  const [focusDetail, setFocusDetail] = useState(false);
  const [cinema, setCinema] = useState(false);
  const [workspaceLoading, setWorkspaceLoading] = useState(true);
  const [tourStep, setTourStep] = useState(0);
  const [tourOpen, setTourOpen] = useState(() => {
    try {
      return window.localStorage.getItem('latch-operator-tour-v1') !== 'seen';
    } catch {
      return true;
    }
  });

  useEffect(() => {
    setWorkspaceLoading(true);
    const finish = window.setTimeout(() => setWorkspaceLoading(false), 720);
    return () => window.clearTimeout(finish);
  }, [page, selectedId]);

  useEffect(() => {
    if (!tourOpen) return;
    if (tourStep <= 1) {
      setPage('overview');
      setFocusDetail(false);
      return;
    }
    setPage('connections');
    setFocusDetail(tourStep >= 3);
  }, [tourOpen, tourStep]);

  const closeTour = (completed: boolean) => {
    try {
      window.localStorage.setItem('latch-operator-tour-v1', 'seen');
    } catch {
      // The walkthrough remains replayable from Guide when storage is unavailable.
    }
    setTourOpen(false);
    if (completed) {
      setPage('connections');
      setFocusDetail(true);
    }
  };

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
  const openConnection = (id: string) => {
    console_.select(id);
    setFocusDetail(true);
    setPage('connections');
  };
  const startFailureReplay = () => {
    setPage('replay');
    console_.startPlayback(console_.demoId, 4);
  };

  return (
    <div className="app-shell flex min-h-full flex-col">
      <div className="ground" aria-hidden />
      <Topbar
        page={page}
        onGuide={() => {
          setTourStep(0);
          setTourOpen(true);
        }}
        onPage={(next) => {
          setPage(next);
          if (next === 'connections') setFocusDetail(false);
        }}
      />

      <div
        className={`workspace-loading-bar ${workspaceLoading ? 'workspace-loading-bar-active' : ''}`}
        role="progressbar"
        aria-label="Loading workspace"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuetext={workspaceLoading ? 'Loading' : 'Complete'}
      >
        <span />
      </div>

      <div className={`workspace-content ${workspaceLoading ? 'workspace-content-loading' : ''}`}>
        {page === 'overview' && (
          <OverviewPage
            connections={connections}
            onOpen={openConnection}
            onViewConnections={() => setPage('connections')}
            onReplay={startFailureReplay}
          />
        )}

        {page === 'connections' && (
          <div className="flex min-h-0 flex-1 flex-col">
          <header className="workspace-heading">
            <div className="flex items-start gap-3">
              {focusDetail && (
                <button
                  type="button"
                  className="mobile-back-button"
                  onClick={() => setFocusDetail(false)}
                  aria-label="Back to connections"
                >
                  ‹
                </button>
              )}
              <div>
              <h1>Connections</h1>
              <p>Select a connection, understand the risk, review the suggested plans, then take the required decision.</p>
              </div>
            </div>
            <span className="text-[11px] text-mist-500">
              {connections.length} captured connections · SGT
            </span>
          </header>

          <div className={`console-grid ${focusDetail ? 'mobile-detail' : 'mobile-list'} grid min-h-0 flex-1 gap-3 p-4 pt-3`}>
            <div className="connection-list-pane min-h-0">
              <RiskQueue
                connections={connections}
                selectedId={selectedId}
                onSelect={(id) => {
                  console_.select(id);
                  setFocusDetail(true);
                }}
                replayingId={playback?.id ?? null}
              />
            </div>

            <main className="detail-column min-h-0 overflow-y-auto pr-1">
              {selected ? (
                <ConnectionDetail c={selected} />
              ) : (
                <p className="text-sm text-mist-500">Select a connection.</p>
              )}
            </main>

            <aside className="insight-column min-h-0 space-y-3 overflow-y-auto pr-1" data-tour="operator-tools">
              {selected && (
                selected.approval && selected.gate ? (
                  <ApprovalPanel
                    approval={selected.approval}
                    gate={selected.gate}
                    awaiting={playback?.awaiting === true && playback.id === selected.id}
                    secondsLeft={playback?.secondsLeft ?? null}
                    speed={playback?.speed ?? 1}
                    decided={playback?.id === selected.id ? (playback?.branch ?? null) : null}
                    onDecide={console_.decide}
                  />
                ) : (
                  <section className="product-panel p-4">
                    <h2 className="text-[14px] font-semibold text-mist-100">No operator decision required</h2>
                    <p className="mt-2 text-[11px] leading-relaxed text-mist-500">
                      This connection has no pending approval. Review its situation or recorded outcome.
                    </p>
                  </section>
                )
              )}
            </aside>
          </div>
          </div>
        )}

        {page === 'replay' && (
          <div className="replay-page flex min-h-0 flex-1 flex-col">
          <header className="workspace-heading">
            <div>
              <h1>Replay</h1>
              <p>Walk through a captured agent run, inspect each step, and take the approval decision.</p>
            </div>
          </header>
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

          {playback && selected && selected.id === playback.id ? (
            <DemoStage c={selected} playback={playback} onDecide={console_.decide} />
          ) : (
            <section className="replay-empty">
              <span className="replay-empty-icon" aria-hidden>▶</span>
              <h2>Choose a captured run</h2>
              <p>
                The failure-injection scenario shows a tool timeout, stale fallback, confidence
                downgrade, policy escalation, and operator approval.
              </p>
            </section>
          )}
          </div>
        )}
      </div>

      <ProductTour
        open={tourOpen && !workspaceLoading}
        step={tourStep}
        onStep={setTourStep}
        onClose={closeTour}
      />
    </div>
  );
}
