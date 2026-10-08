import type { PlayerBrief, PlayerStatus, Position, Recommendation } from '@/lib/api';

export type Verdict = 'START' | 'BENCH' | 'SELL' | 'BUY' | 'HOLD';

// Every verdict is read off the optimiser's output; the app adds no judgement
// of its own.
export function verdictFor(playerId: number, rec: Recommendation | undefined): Verdict | null {
  if (!rec) return null;
  const plan = rec.transfer.plan;
  if (plan.out.some((p) => p.player_id === playerId)) return 'SELL';
  if (plan.in.some((p) => p.player_id === playerId)) return 'BUY';
  if (rec.lineup.starting.some((p) => p.player_id === playerId)) return 'START';
  if (rec.lineup.bench.some((p) => p.player_id === playerId)) return 'BENCH';
  return null;
}

/** For the player screen, where "start" and "bench" read oddly: owned and unchanged is HOLD. */
export function marketVerdict(playerId: number, rec: Recommendation | undefined): Verdict | null {
  const v = verdictFor(playerId, rec);
  return v === 'START' || v === 'BENCH' ? 'HOLD' : v;
}

export function availabilityLabel(status: PlayerStatus, chance: number | null | undefined): string | null {
  switch (status) {
    case 'a':
      return null;
    case 'd':
      return chance != null ? `${chance}%` : 'Doubt';
    case 'i':
      return 'Injured';
    case 's':
      return 'Suspended';
    case 'u':
      return 'Unavailable';
    case 'n':
      return 'Left club';
  }
}

const ORDER: Position[] = ['GKP', 'DEF', 'MID', 'FWD'];

/** Starting XI as pitch rows, goalkeeper first. */
export function pitchRows(starting: PlayerBrief[]): PlayerBrief[][] {
  return ORDER.map((pos) => starting.filter((p) => p.position === pos)).filter((r) => r.length > 0);
}

/** FPL bench labels: the reserve keeper, then outfield subs in autosub order. */
export function benchLabels(bench: { position: Position }[]): string[] {
  let n = 0;
  return bench.map((p) => (p.position === 'GKP' ? 'GK' : String(++n)));
}

/** Which side of a comparison wins, or null for a tie or a stat with no "better". */
export function betterSide(better: 'high' | 'low' | null, left: number, right: number): 'left' | 'right' | null {
  if (better === null || left === right) return null;
  return (better === 'high') === left > right ? 'left' : 'right';
}

export function money(tenths: number): string {
  return `£${(tenths / 10).toFixed(1)}m`;
}

export function signed(value: number, digits = 1): string {
  return `${value >= 0 ? '+' : '−'}${Math.abs(value).toFixed(digits)}`;
}
