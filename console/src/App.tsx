/** LATCH operations console. */

import { useEffect, useState } from 'react';

import { ApprovalPanel } from './components/ApprovalPanel';
import { ConnectionDetail, type PlanSelection } from './components/ConnectionDetail';
import { ProductTour } from './components/ProductTour';
import { RiskQueue } from './components/RiskQueue';
import { useConsole } from './store/useConsole';

function Topbar({ onGuide }: { onGuide: () => void }) {
  return (
    <header className="topbar">
      <span className="wordmark">LATCH</span>

      <button type="button" className="guide-button" onClick={onGuide}>
        <span aria-hidden>?</span>
        Guide
      </button>

      <div className="hidden items-center gap-2 text-[11px] md:flex">
        <span className="font-medium text-mist-300">PSA Singapore</span>
      </div>
    </header>
  );
}

export default function App() {
  const console_ = useConsole();
  const { connections, selected, selectedId, playback, select } = console_;
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
  const open = connections.filter((c) => c.lifecycle === 'live');
  const needsAction = open.filter(
    (c) => c.approval?.actionable === true && c.gate?.status === 'awaiting',
  );
  const pending = open.length - needsAction.length;
  const tourDecisionId = needsAction[0]?.id ?? null;
  const showOperatorTools = Boolean(
    selected?.lifecycle === 'live' &&
    selected.approval &&
    selected.gate &&
    !(selected.state === 'executing' && !selected.outcome),
  );

  useEffect(() => {
    setWorkspaceLoading(true);
    const finish = window.setTimeout(() => setWorkspaceLoading(false), 320);
    return () => window.clearTimeout(finish);
  }, [selectedId]);

  useEffect(() => setPlanSelection(null), [selectedId]);

  useEffect(() => {
    if (!tourOpen) return;
    if (tourStep >= 2 && tourDecisionId && selectedId !== tourDecisionId) select(tourDecisionId);
    setFocusDetail(tourStep >= 2);
  }, [selectedId, select, tourDecisionId, tourOpen, tourStep]);

  const closeTour = (completed: boolean) => {
    try {
      window.localStorage.setItem('latch-operator-tour-v1', 'seen');
    } catch {
      // The walkthrough remains available from Guide when storage is unavailable.
    }
    setTourOpen(false);
    if (completed) setFocusDetail(true);
  };

  return (
    <div className="app-shell flex min-h-full flex-col">
      <div className="ground" aria-hidden />
      <Topbar
        onGuide={() => {
          setTourStep(0);
          setTourOpen(true);
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
              <p>
                {needsAction.length > 0
                  ? `${needsAction.length} needs your decision`
                  : 'No decisions needed'}
                {pending > 0 ? ` · ${pending} in progress` : ''}
              </p>
              </div>
            </div>
            <span className="text-[11px] text-mist-500">
              {open.length} open · Singapore time
            </span>
          </header>

          <div className={`console-grid ${showOperatorTools ? '' : 'console-grid-no-tools'} ${focusDetail ? 'mobile-detail' : 'mobile-list'} grid min-h-0 flex-1 gap-3 p-4 pt-3`}>
            <div className="connection-list-pane min-h-0">
              <RiskQueue
                connections={connections}
                selectedId={selectedId}
                onSelect={(id) => {
                  select(id);
                  setFocusDetail(true);
                }}
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

            {showOperatorTools && selected && selected.approval && selected.gate && (
              <aside className="insight-column min-h-0 space-y-3 overflow-y-auto pr-1" data-tour="operator-tools">
                <ApprovalPanel
                  approval={selected.approval}
                  gate={selected.gate}
                  awaiting={playback?.awaiting === true && playback.id === selected.id}
                  secondsLeft={playback?.secondsLeft ?? null}
                  decided={playback?.id === selected.id ? (playback?.branch ?? null) : null}
                  planLabel={planSelection?.connectionId === selected.id ? planSelection.label : null}
                  onDecide={console_.decide}
                />
              </aside>
            )}
          </div>
        </div>
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
