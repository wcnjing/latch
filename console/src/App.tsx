/** LATCH operations console. */

import { useEffect, useState } from 'react';

import { ApprovalPanel } from './components/ApprovalPanel';
import { ConnectionDetail, type PlanSelection } from './components/ConnectionDetail';
import { OverviewPage } from './components/OverviewPage';
import { ProductTour } from './components/ProductTour';
import { RiskQueue } from './components/RiskQueue';
import { useConsole } from './store/useConsole';

type Page = 'overview' | 'connections';

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
  const [workspaceLoading, setWorkspaceLoading] = useState(true);
  const [planSelection, setPlanSelection] = useState<(PlanSelection & { connectionId: string }) | null>(null);
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
    const finish = window.setTimeout(() => setWorkspaceLoading(false), 320);
    return () => window.clearTimeout(finish);
  }, [page, selectedId]);

  useEffect(() => setPlanSelection(null), [selectedId]);

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
      // The walkthrough remains available from Guide when storage is unavailable.
    }
    setTourOpen(false);
    if (completed) {
      setPage('connections');
      setFocusDetail(true);
    }
  };

  const openConnection = (id: string) => {
    console_.select(id);
    setFocusDetail(true);
    setPage('connections');
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

      <div className="workspace-content">
        {page === 'overview' && (
          <OverviewPage
            connections={connections}
            onOpen={openConnection}
            onViewConnections={() => setPage('connections')}
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
                <ConnectionDetail
                  c={selected}
                  selectedPlanKey={planSelection?.connectionId === selected.id ? planSelection.key : null}
                  selectedPlanLabel={planSelection?.connectionId === selected.id ? planSelection.label : null}
                  onPlanSelect={(selection) => setPlanSelection({ ...selection, connectionId: selected.id })}
                />
              ) : (
                <p className="text-sm text-mist-500">Select a connection.</p>
              )}
            </main>

            <aside className="insight-column min-h-0 space-y-3 overflow-y-auto pr-1" data-tour="operator-tools">
              {selected && (
                selected.lifecycle === 'live' && selected.state === 'executing' && !selected.outcome ? (
                  <section className="product-panel p-4">
                    <h2 className="text-[14px] font-semibold text-mist-100">Outcome pending</h2>
                    <p className="mt-2 text-[11px] leading-relaxed text-mist-500">
                      The plan is in execution. No operator decision is currently required; monitor the Outcome tab for service confirmation.
                    </p>
                  </section>
                ) : selected.lifecycle === 'live' && selected.approval && selected.gate ? (
                  <ApprovalPanel
                    approval={selected.approval}
                    gate={selected.gate}
                    awaiting={playback?.awaiting === true && playback.id === selected.id}
                    secondsLeft={playback?.secondsLeft ?? null}
                    speed={playback?.speed ?? 1}
                    decided={playback?.id === selected.id ? (playback?.branch ?? null) : null}
                    planLabel={planSelection?.connectionId === selected.id ? planSelection.label : null}
                    onDecide={console_.decide}
                  />
                ) : selected.outcome ? (
                  <section className="product-panel p-4">
                    <h2 className="text-[14px] font-semibold text-mist-100">Recorded outcome</h2>
                    <p className="mt-2 text-[11px] leading-relaxed text-mist-500">
                      This connection is complete. Its decision, cargo result, and operational follow-up are captured in the Outcome tab.
                    </p>
                  </section>
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

      </div>

      <ProductTour
        open={tourOpen}
        step={tourStep}
        onStep={setTourStep}
        onClose={closeTour}
      />
    </div>
  );
}
