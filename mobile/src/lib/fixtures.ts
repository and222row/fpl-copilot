import type { FixtureView, PlannerTeam } from '@/lib/api';

// FPL's own five fixture colours, so the grid reads the way players expect.
export const DIFFICULTY_COLOURS = [
  { bg: '#257D5A', fg: '#FFFFFF' },
  { bg: '#00FF86', fg: '#1A0B1F' },
  { bg: '#EBEBE4', fg: '#1A0B1F' },
  { bg: '#FF005A', fg: '#FFFFFF' },
  { bg: '#861D46', fg: '#FFFFFF' },
] as const;

/** The model's 1-5 difficulty (fractional) as one of FPL's five steps, 1 easiest. */
export function step(difficulty: number): 1 | 2 | 3 | 4 | 5 {
  if (difficulty < 1.75) return 1;
  if (difficulty < 2.5) return 2;
  if (difficulty < 3.25) return 3;
  if (difficulty < 4) return 4;
  return 5;
}

export function colours(difficulty: number) {
  return DIFFICULTY_COLOURS[step(difficulty) - 1];
}

/** Easiest run first for the chosen view. */
export function byEase(teams: PlannerTeam[], view: FixtureView): PlannerTeam[] {
  return [...teams].sort((a, b) => b.ease[view] - a.ease[view] || a.team.localeCompare(b.team));
}

/** How many of your players each club has, by short name. */
export function ownedByClub(players: { team: string }[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const p of players) out[p.team] = (out[p.team] ?? 0) + 1;
  return out;
}
