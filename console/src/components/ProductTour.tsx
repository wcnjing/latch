import { useEffect, useMemo, useRef, useState } from 'react';
import type { CSSProperties } from 'react';

type TourBox = { top: number; left: number; width: number; height: number; right: number; bottom: number };
type TourStep = { selector?: string; eyebrow: string; title: string; body: string };

const STEPS: readonly TourStep[] = [
  {
    eyebrow: 'A clearer operating rhythm',
    title: 'Welcome to LATCH',
    body: 'See how a terminal controller can move from an urgent connection to a confident decision in under a minute.',
  },
  {
    selector: '[data-tour="attention-queue"]',
    eyebrow: 'Step 1',
    title: 'Start with what needs attention',
    body: 'The overview ranks connections by urgency, so the next job is obvious without reading every alert.',
  },
  {
    selector: '[data-tour="connection-queue"]',
    eyebrow: 'Step 2',
    title: 'Choose one connection',
    body: 'Each compact card shows the time pressure, cargo exposure, and whether the connection can still be recovered.',
  },
  {
    selector: '[data-tour="connection-detail"]',
    eyebrow: 'Step 3',
    title: 'Understand, compare, then review',
    body: 'Use Situation, Suggested plans, and Outcome in order. The controller sees operational facts—not AI internals.',
  },
  {
    selector: '[data-tour="operator-tools"]',
    eyebrow: 'Step 4',
    title: 'Make the operational decision',
    body: 'The final panel shows only who needs to decide, the plain-language consequence, and the available action.',
  },
];

function tooltipPosition(box: TourBox | null): CSSProperties {
  if (!box) return {};
  if (window.innerWidth < 768) {
    return { left: 12, right: 12, bottom: 12 };
  }

  const width = 330;
  const gap = 18;
  const top = Math.max(64, Math.min(box.top + 18, window.innerHeight - 330));
  if (box.right + width + gap < window.innerWidth) {
    return { left: box.right + gap, top, width };
  }
  return { left: Math.max(18, box.left - width - gap), top, width };
}

export function ProductTour({
  open,
  step,
  onStep,
  onClose,
}: {
  open: boolean;
  step: number;
  onStep: (step: number) => void;
  onClose: (completed: boolean) => void;
}) {
  const [box, setBox] = useState<TourBox | null>(null);
  const nextRef = useRef<HTMLButtonElement>(null);
  const current = STEPS[step] ?? STEPS[0]!;

  useEffect(() => {
    if (!open) return;
    let frame = 0;
    let timer = 0;

    const update = () => {
      if (!current.selector) {
        setBox(null);
        return;
      }
      const element = document.querySelector<HTMLElement>(current.selector);
      if (!element) {
        setBox(null);
        return;
      }
      const rect = element.getBoundingClientRect();
      setBox({
        top: rect.top,
        left: rect.left,
        width: rect.width,
        height: rect.height,
        right: rect.right,
        bottom: rect.bottom,
      });
    };

    timer = window.setTimeout(() => {
      const element = current.selector
        ? document.querySelector<HTMLElement>(current.selector)
        : null;
      element?.scrollIntoView({ block: 'center', behavior: 'smooth' });
      frame = window.requestAnimationFrame(update);
      nextRef.current?.focus();
    }, 180);

    window.addEventListener('resize', update);
    window.addEventListener('scroll', update, true);
    return () => {
      window.clearTimeout(timer);
      window.cancelAnimationFrame(frame);
      window.removeEventListener('resize', update);
      window.removeEventListener('scroll', update, true);
    };
  }, [current, open]);

  const cardStyle = useMemo(() => tooltipPosition(box), [box]);
  if (!open) return null;

  const first = step === 0;
  const last = step === STEPS.length - 1;

  return (
    <div className={`tour-layer ${first ? 'tour-layer-welcome' : ''}`}>
      {box ? (
        <div
          className="tour-spotlight"
          style={{
            top: Math.max(8, box.top - 6),
            left: Math.max(8, box.left - 6),
            width: Math.min(window.innerWidth - 16, box.width + 12),
            height: Math.min(window.innerHeight - 16, box.height + 12),
          }}
        />
      ) : (
        <div className="tour-backdrop" />
      )}

      <section
        className={`tour-card ${first || !box ? 'tour-card-welcome' : 'tour-card-anchored'}`}
        style={first ? undefined : cardStyle}
        role="dialog"
        aria-modal="true"
        aria-labelledby="tour-title"
      >
        <div className="tour-progress" aria-label={`${step} of ${STEPS.length - 1} walkthrough steps`}>
          {STEPS.slice(1).map((_, index) => (
            <span key={index} className={step > index ? 'tour-progress-active' : ''} />
          ))}
        </div>

        <button className="tour-close" type="button" onClick={() => onClose(false)} aria-label="Close walkthrough">
          ×
        </button>
        <span className="tour-eyebrow">{current.eyebrow}</span>
        <h2 id="tour-title">{current.title}</h2>
        <p>{current.body}</p>

        <footer className="tour-actions">
          {first ? (
            <button type="button" className="tour-text-button" onClick={() => onClose(false)}>
              Skip for now
            </button>
          ) : (
            <button type="button" className="tour-text-button" onClick={() => onStep(step - 1)}>
              Back
            </button>
          )}
          <button
            ref={nextRef}
            type="button"
            className="button-primary"
            onClick={() => (last ? onClose(true) : onStep(step + 1))}
          >
            {first ? 'Start walkthrough' : last ? 'Finish' : 'Next'}
          </button>
        </footer>
      </section>
    </div>
  );
}
