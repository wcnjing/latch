import { useEffect, useMemo, useRef, useState } from 'react';
import type { CSSProperties } from 'react';

type TourBox = { top: number; left: number; width: number; height: number; right: number; bottom: number };
type TourStep = {
  selector?: string;
  placement?: 'side' | 'below';
  maxSpotlightHeight?: number;
  eyebrow: string;
  title: string;
  body: string;
};

const STEPS: readonly TourStep[] = [
  {
    eyebrow: 'A clearer operating rhythm',
    title: 'Welcome to LATCH',
    body: 'See what needs attention, compare the plans, and make a decision.',
  },
  {
    selector: '[data-tour="connection-queue"]',
    eyebrow: 'Step 1',
    title: 'Choose a connection',
    body: 'Decision needed, in progress, and closed records are kept in one list.',
  },
  {
    selector: 'section[data-tour="connection-summary"]',
    maxSpotlightHeight: 190,
    eyebrow: 'Step 2',
    title: 'See the operational picture',
    body: 'Start with the time margin, affected containers, and when the risk was detected.',
  },
  {
    selector: '[data-tour="connection-workflow"]',
    placement: 'below',
    eyebrow: 'Step 3',
    title: 'Understand, choose, then act',
    body: 'Use Situation, Plans, and Actions to move the connection from risk to execution.',
  },
  {
    selector: '[data-tour="operator-tools"]',
    eyebrow: 'Step 4',
    title: 'Make the operational decision',
    body: 'Choose a plan, understand what happens if you wait, then approve or decline.',
  },
];

function tooltipPosition(box: TourBox | null, placement: TourStep['placement'] = 'side'): CSSProperties {
  if (!box) return {};
  if (window.innerWidth < 768) {
    return { left: 12, right: 12, bottom: 12 };
  }

  const width = 330;
  const gap = 18;
  if (placement === 'below') {
    return {
      left: Math.max(18, Math.min(box.left + box.width / 2 - width / 2, window.innerWidth - width - 18)),
      top: Math.min(box.bottom + 14, window.innerHeight - 330),
      width,
    };
  }
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
      const visibleTop = Math.max(8, rect.top);
      const visibleBottom = Math.min(window.innerHeight - 8, rect.bottom);
      const visibleHeight = Math.max(0, visibleBottom - visibleTop);
      const height = Math.min(visibleHeight, current.maxSpotlightHeight ?? visibleHeight);
      setBox({
        top: visibleTop,
        left: rect.left,
        width: rect.width,
        height,
        right: rect.right,
        bottom: visibleTop + height,
      });
    };

    const scheduleUpdate = () => {
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(update);
    };

    const resizeObserver = new ResizeObserver(scheduleUpdate);

    timer = window.setTimeout(() => {
      const element = current.selector
        ? document.querySelector<HTMLElement>(current.selector)
        : null;
      if (element) resizeObserver.observe(element);
      element?.scrollIntoView({ block: 'center', behavior: 'smooth' });
      scheduleUpdate();
      nextRef.current?.focus();
    }, 180);

    window.addEventListener('resize', scheduleUpdate);
    window.addEventListener('scroll', scheduleUpdate, true);
    return () => {
      window.clearTimeout(timer);
      window.cancelAnimationFrame(frame);
      resizeObserver.disconnect();
      window.removeEventListener('resize', scheduleUpdate);
      window.removeEventListener('scroll', scheduleUpdate, true);
    };
  }, [current, open]);

  const cardStyle = useMemo(() => tooltipPosition(box, current.placement), [box, current.placement]);
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
            width: Math.min(window.innerWidth - Math.max(8, box.left - 6) - 8, box.width + 12),
            height: Math.min(window.innerHeight - Math.max(8, box.top - 6) - 8, box.height + 12),
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
