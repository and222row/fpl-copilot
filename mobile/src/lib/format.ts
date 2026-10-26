/** 1st, 2nd, 3rd, 4th … 11th, 12th, 13th … 21st. */
export function ordinal(n: number): string {
  const tens = n % 100;
  const suffix = tens >= 11 && tens <= 13 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' } as Record<number, string>)[n % 10] ?? 'th';
  return `${n}${suffix}`;
}

/** Transfer counts at a glance: 950, 12.3k, 398k, 1.2m. */
export function compact(n: number): string {
  const a = Math.abs(n);
  const sign = n < 0 ? '−' : '';
  if (a >= 1_000_000) return `${sign}${(a / 1_000_000).toFixed(1).replace(/\.0$/, '')}m`;
  if (a >= 100_000) return `${sign}${Math.round(a / 1000)}k`;
  if (a >= 1000) return `${sign}${(a / 1000).toFixed(1).replace(/\.0$/, '')}k`;
  return `${sign}${a}`;
}

/** "just now", "12 min ago", "3h ago", "2 days ago". */
export function timeAgo(iso: string, now: number = Date.now()): string {
  const minutes = Math.floor((now - new Date(iso).getTime()) / 60_000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days} day${days === 1 ? '' : 's'} ago`;
}
