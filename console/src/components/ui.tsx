/** Shared primitives. Deliberately few — the console is mostly bespoke panels. */

import type { ReactNode } from 'react';
import type { MaybeMissing, Unverified } from '../adapters/types';
import { isMissing } from '../adapters/types';
import { minutesAgo } from '../lib/format';

export function Panel({
  title,
  subtitle,
  right,
  children,
  tone = 'default',
  className = '',
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  right?: ReactNode;
  children: ReactNode;
  tone?: 'default' | 'alert';
  className?: string;
}) {
  const border = tone === 'alert' ? 'border-watch-500/50' : 'border-ink-700';
  return (
    <section className={`rounded-lg border ${border} bg-ink-850 ${className}`}>
      {title && (
        <header className="flex items-start justify-between gap-4 border-b border-ink-700 px-4 py-2.5">
          <div>
            <h2 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-mist-400">
              {title}
            </h2>
            {subtitle && <p className="mt-0.5 text-xs text-mist-500">{subtitle}</p>}
          </div>
          {right}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

const SEVERITY_STYLE: Record<string, string> = {
  SAFE: 'bg-safe-900 text-safe-500 border-safe-500/40',
  WATCH: 'bg-watch-900 text-watch-500 border-watch-500/40',
  'AT RISK': 'bg-risk-900 text-risk-500 border-risk-500/40',
};

export function SeverityBadge({ label, big = false }: { label: string; big?: boolean }) {
  const style = SEVERITY_STYLE[label] ?? 'bg-ink-750 text-mist-300 border-ink-600';
  return (
    <span
      className={`inline-flex items-center rounded border font-semibold uppercase tracking-wider ${style} ${
        big ? 'px-2.5 py-1 text-xs' : 'px-1.5 py-0.5 text-[10px]'
      }`}
    >
      {label}
    </span>
  );
}

const STATE_STYLE: Record<string, string> = {
  Superseded: 'bg-flag-900 text-flag-500 border-flag-500/40',
  Stale: 'bg-watch-900 text-watch-500 border-watch-500/40',
  Lapsed: 'bg-risk-900 text-risk-500 border-risk-500/40',
  'Lost the slot': 'bg-risk-900 text-risk-500 border-risk-500/40',
  Resolved: 'bg-ink-750 text-mist-400 border-ink-600',
  Dismissed: 'bg-ink-800 text-mist-500 border-ink-700',
};

export function StateBadge({ label }: { label: string }) {
  const style = STATE_STYLE[label] ?? 'bg-ink-750 text-mist-300 border-ink-600';
  return (
    <span
      className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-medium ${style}`}
    >
      {label}
    </span>
  );
}

/** A number the trace does not carry. Never a blank, never a zero. */
export function GapMarker({ value, className = '' }: { value: MaybeMissing<number>; className?: string }) {
  if (!isMissing(value)) return <span className={className}>{value}</span>;
  return (
    <span
      className={`inline-flex cursor-help items-center gap-1 text-mist-500 ${className}`}
      title={`${value.label} — ${value.request}`}
    >
      <span className="text-mist-600">—</span>
      <span className="text-[10px] uppercase tracking-wide">{value.label}</span>
    </span>
  );
}

/**
 * Marks a value as unverified at the value itself. The brief is explicit that
 * this must not be a footnote, so it is an inline glyph with the reason on it.
 */
export function UnverifiedMark({ why }: { why: Unverified }) {
  const age = why.ageMin > 0 ? `, ${minutesAgo(why.ageMin)}` : '';
  return (
    <span
      className="ml-1 inline-flex translate-y-[-1px] cursor-help items-center rounded border border-watch-500/50 bg-watch-900 px-1 py-[1px] text-[9px] font-bold uppercase tracking-wide text-watch-500 align-middle"
      title={`UNVERIFIED — ${why.reason}${age}`}
    >
      unverified
    </span>
  );
}

export function Stat({
  label,
  value,
  hint,
  tone = 'default',
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: 'default' | 'good' | 'warn' | 'bad';
}) {
  const colour =
    tone === 'good'
      ? 'text-safe-500'
      : tone === 'warn'
        ? 'text-watch-500'
        : tone === 'bad'
          ? 'text-risk-500'
          : 'text-mist-100';
  return (
    <div>
      <div className="text-[10px] uppercase tracking-[0.12em] text-mist-500">{label}</div>
      <div className={`tnum mt-0.5 text-lg font-semibold ${colour}`}>{value}</div>
      {hint && <div className="mt-0.5 text-[11px] leading-snug text-mist-500">{hint}</div>}
    </div>
  );
}

/** A visible stand-in where a measured figure belongs and A's evaluation has not run. */
export function Placeholder({ what }: { what: string }) {
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded border border-dashed border-ink-500 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-mist-500"
      title={`No measured value. ${what}`}
    >
      placeholder
    </span>
  );
}

export function Note({ children, tone = 'default' }: { children: ReactNode; tone?: 'default' | 'warn' }) {
  const style =
    tone === 'warn'
      ? 'border-watch-500/40 bg-watch-900/50 text-watch-500'
      : 'border-ink-700 bg-ink-800 text-mist-400';
  return (
    <p className={`rounded border px-3 py-2 text-[11px] leading-relaxed ${style}`}>{children}</p>
  );
}
