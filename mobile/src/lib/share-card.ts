import type { GameweekReview, LiveLeague, LiveView } from '@/lib/api';
import { ordinal } from '@/lib/format';
import { chipName } from '@/lib/live';
import { rankMove } from '@/lib/review';

/** What a share card says: the same layout for every kind of card. */
export interface CardContent {
  eyebrow: string;
  team: string;
  big: string;
  sub: string;
  stats: { label: string; value: string }[];
  lines: string[];
  /** The file name, without extension. */
  slug: string;
}

function signed(n: number): string {
  return n >= 0 ? String(n) : `−${-n}`;
}

export function reviewCard(r: GameweekReview, team: string): CardContent {
  const avg = r.gameweek.average;
  const move = rankMove(r.previous_overall_rank, r.overall_rank);
  const best = r.best[0];
  const cap = r.captain.pick;
  const chip = chipName(r.chip);
  return {
    eyebrow: `${r.gameweek.name}${chip ? ` · ${chip}` : ''}`,
    team,
    big: `${signed(r.points)} pts`,
    sub: avg !== null ? (r.points >= avg ? `${r.points - avg} above the average` : `${avg - r.points} below the average`) : '',
    stats: [
      { label: 'Average', value: avg !== null ? String(avg) : '—' },
      { label: 'Highest', value: r.gameweek.highest !== null ? String(r.gameweek.highest) : '—' },
      { label: 'Overall rank', value: r.overall_rank ? `${r.overall_rank.toLocaleString()}${move ? ` ${move.text.split(' ')[0]}` : ''}` : '—' },
    ],
    lines: [
      best ? `Star: ${best.name} ${signed(best.contribution)}` : null,
      cap ? `Captain: ${cap.name} ${signed(cap.contribution)}` : null,
    ].filter((l): l is string => l !== null),
    slug: `gw${r.gameweek.id}-review`,
  };
}

export function liveCard(l: LiveView, team: string): CardContent {
  return {
    eyebrow: `${l.gameweek.name} · ${l.in_play ? 'live' : l.finished ? 'all matches played' : 'so far'}`,
    team,
    big: `${signed(l.points)} pts`,
    sub: l.players_left ? `${l.players_left} still to play` : 'Everyone has played',
    stats: [
      { label: 'Average', value: l.gameweek.average !== null ? String(l.gameweek.average) : '—' },
      { label: 'Highest', value: l.gameweek.highest !== null ? String(l.gameweek.highest) : '—' },
      { label: 'Captain', value: l.armband ?? '—' },
    ],
    lines: l.provisional_bonus ? [`Includes ${l.provisional_bonus} provisional bonus`] : [],
    slug: `gw${l.gameweek.id}-live`,
  };
}

export function leagueCard(l: LiveLeague, team: string): CardContent {
  const me = l.standings.find((s) => s.is_you);
  const rank = l.your_live_rank;
  return {
    eyebrow: `${l.gameweek.name} · ${l.league.name}`,
    team,
    big: rank ? ordinal(rank) : '—',
    sub: rank === 1 ? 'Top of the league' : l.gap_to_leader ? `${l.gap_to_leader} behind the leader` : '',
    stats: [
      { label: 'GW points', value: me ? signed(me.gameweek_points) : '—' },
      { label: 'Total', value: me ? me.total.toLocaleString() : '—' },
      { label: 'Managers', value: String(l.league.size ?? l.standings.length) },
    ],
    lines: me?.captain ? [`Captain: ${me.captain}`] : [],
    slug: `gw${l.gameweek.id}-league-${l.league.id}`,
  };
}
