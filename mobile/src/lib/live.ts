import type { LivePlayer, LiveStatus } from '@/lib/api';
import type { ThemeColor } from '@/constants/theme';

/** What a player has scored, as it counts for you: the armband's multiplier applied. */
export function shownPoints(p: LivePlayer): number {
  return p.multiplier > 1 ? p.points * p.multiplier : p.points;
}

/**
 * The line under a shirt on the live pitch: the fixture before kick-off, then
 * points, marked while their match is on.
 */
export function liveCaption(p: LivePlayer): string {
  if (p.state === 'to_play' && p.minutes === 0) {
    return p.fixtures && p.fixtures.length ? p.fixtures.join(', ') : 'No fixture';
  }
  const pts = shownPoints(p);
  return p.state === 'playing' ? `${pts} pts · live` : `${pts} pts`;
}

export function kickoff(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { weekday: 'short', hour: '2-digit', minute: '2-digit' });
}

/** Live, final, or when the next match kicks off. */
export function liveBadge(s: LiveStatus): { label: string; color: ThemeColor; soft: ThemeColor } {
  if (s.in_play) return { label: 'Live', color: 'danger', soft: 'dangerSoft' };
  if (s.finished) return { label: 'All matches played', color: 'highlight', soft: 'highlightSoft' };
  if (s.next_kickoff) return { label: `Next match ${kickoff(s.next_kickoff)}`, color: 'accent', soft: 'accentSoft' };
  return { label: `${s.matches_done} of ${s.matches_total} played`, color: 'accent', soft: 'accentSoft' };
}

/** How a team counts a player: "—", "owned", "captain" or "triple captain". */
export function role(multiplier: number): string {
  return ['—', 'owned', 'captain', 'triple captain'][multiplier] ?? `×${multiplier}`;
}

/** What each point a player scores moves you: "+1 per point", "−0.4 per point". */
export function perPoint(net: number): string {
  const n = Math.abs(net);
  const shown = Number.isInteger(n) ? String(n) : n.toFixed(1);
  return `${net >= 0 ? '+' : '−'}${shown} per point`;
}

export function chipName(chip: string | null): string | null {
  const names: Record<string, string> = { bboost: 'Bench Boost', '3xc': 'Triple Captain', freehit: 'Free Hit', wildcard: 'Wildcard' };
  return chip ? (names[chip] ?? chip) : null;
}
