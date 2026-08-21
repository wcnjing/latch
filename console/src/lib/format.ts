/** Formatting helpers. No library — two of these and a percentage. */

const TIME = new Intl.DateTimeFormat('en-SG', {
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
  timeZone: 'Asia/Singapore',
});

const DATETIME = new Intl.DateTimeFormat('en-SG', {
  day: '2-digit',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
  timeZone: 'Asia/Singapore',
});

export const hhmm = (iso: string) => TIME.format(new Date(iso));
export const stamp = (iso: string) => DATETIME.format(new Date(iso));

/** Signed hours, always with the sign — the sign is the whole point. */
export function signedHours(h: number): string {
  return `${h >= 0 ? '+' : '\u2212'}${Math.abs(h).toFixed(1)}h`;
}

export function hoursAndMinutes(h: number): string {
  const total = Math.round(Math.abs(h) * 60);
  const hh = Math.floor(total / 60);
  const mm = total % 60;
  const body = hh ? `${hh}h ${String(mm).padStart(2, '0')}m` : `${mm}m`;
  return h < 0 ? `${body} short` : body;
}

export function latency(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
}

export function usd(v: number): string {
  if (v === 0) return '$0.0000';
  return v < 0.01 ? `$${v.toFixed(4)}` : `$${v.toFixed(3)}`;
}

export function tokens(n: number): string {
  return n.toLocaleString('en-SG');
}

export function pct(fraction: number): string {
  return `${Math.round(fraction * 100)}%`;
}

export function minutesAgo(min: number): string {
  if (min < 1) return 'just now';
  if (min < 60) return `${Math.round(min)} min old`;
  return `${(min / 60).toFixed(1)}h old`;
}

/** mm:ss for the approval countdown. */
export function clock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
}
