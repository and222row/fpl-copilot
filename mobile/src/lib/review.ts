import type { ReviewAdvice } from '@/lib/api';

const WHAT: Record<ReviewAdvice['kind'], string> = { captain: 'captain pick', lineup: 'lineup', transfer: 'transfer advice' };

function pts(n: number): string {
  const v = Math.round(Math.abs(n) * 10) / 10;
  return `${v} ${v === 1 ? 'point' : 'points'}`;
}

/** One plain sentence on how a piece of advice turned out. */
export function adviceLine(a: ReviewAdvice): string {
  const what = WHAT[a.kind] ?? a.kind;
  if (a.followed) {
    return a.kind === 'captain' ? `You followed our captain pick. With the armband he scored ${a.actual}.` : `You followed our ${what}.`;
  }
  if (a.override_delta === null) return `You didn't follow our ${what}.`;
  if (a.override_delta < 0) return `Following our ${what} would have gained you ${pts(a.override_delta)}.`;
  if (a.override_delta > 0) return `Going your own way beat our ${what} by ${pts(a.override_delta)}.`;
  return `Going your own way on the ${what} made no difference.`;
}

/** Overall rank movement: up is good, so a smaller number reads as a rise. */
export function rankMove(before: number | null, now: number | null): { text: string; up: boolean } | null {
  if (!before || !now || before === now) return null;
  const up = now < before;
  return { text: `${up ? '▲' : '▼'} ${Math.abs(before - now).toLocaleString()}`, up };
}
