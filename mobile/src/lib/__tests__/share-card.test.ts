import type { GameweekReview, LiveLeague, LiveView } from '@/lib/api';
import { leagueCard, liveCard, reviewCard } from '@/lib/share-card';

const player = (name: string, points: number, multiplier = 1) => ({
  player_id: 1, name, team: 'ARS', position: 'MID' as const, points, multiplier, contribution: points * multiplier, minutes: 90,
});

const review = (extra: Partial<GameweekReview> = {}): GameweekReview => ({
  gameweek: { id: 8, name: 'Gameweek 8', average: 45, highest: 120 },
  finished: true, points: 61, transfer_cost: 0, chip: null,
  gameweek_rank: 900_000, overall_rank: 1_200_000, previous_overall_rank: 1_500_000,
  best: [player('Salah', 12, 2)], worst: [], captain: { pick: player('Salah', 12, 2), best: null, missed: 0 },
  bench_points: 0, bench: [], auto_subs: [], advice: [], leagues: [], season: [],
  ...extra,
});

test('a review card: the points, how they compare, the star and the captain', () => {
  const card = reviewCard(review(), 'Gold FC');
  expect(card).toMatchObject({ eyebrow: 'Gameweek 8', team: 'Gold FC', big: '61 pts', sub: '16 above the average', slug: 'gw8-review' });
  expect(card.stats[2]).toEqual({ label: 'Overall rank', value: `${(1_200_000).toLocaleString()} ▲` });
  expect(card.lines).toEqual(['Star: Salah 24', 'Captain: Salah 24']);
});

test('a bad week says so plainly, with a proper minus sign', () => {
  const card = reviewCard(review({ points: -2, chip: '3xc', best: [], captain: { pick: player('Palmer', -1, 3), best: null, missed: 0 } }), 'X');
  expect(card.big).toBe('−2 pts');
  expect(card.sub).toBe('47 below the average');
  expect(card.eyebrow).toBe('Gameweek 8 · Triple Captain');
  expect(card.lines).toEqual(['Captain: Palmer −3']);
});

test('a live card', () => {
  const live = {
    gameweek: { id: 9, name: 'Gameweek 9', average: 30, highest: 80 }, in_play: true, finished: false,
    matches_done: 4, matches_total: 10, next_kickoff: null, points: 44, provisional_bonus: 3, transfer_cost: 0,
    players_left: 4, chip: null, captain: 'Haaland', armband: 'Haaland', auto_subs: [], total: 500, squad: [],
  } as LiveView;
  expect(liveCard(live, 'Gold FC')).toMatchObject({
    eyebrow: 'Gameweek 9 · live', big: '44 pts', sub: '4 still to play', lines: ['Includes 3 provisional bonus'],
  });
});

test('a league card leads with the ordinal rank', () => {
  const league = (rank: number, gap: number) => ({
    league: { id: 7, name: 'Mates', size: 12 }, gameweek: { id: 9, name: 'Gameweek 9' },
    in_play: true, finished: false, matches_done: 1, matches_total: 10, next_kickoff: null,
    managers_read: 12, partial: false, your_live_rank: rank, gap_to_leader: gap, gap_to_next: null, swing: null,
    standings: [{ entry: 1, team_name: 'Gold FC', manager_name: 'A', rank: 3, last_rank: 3, live_rank: rank, gameweek_points: 50,
                  total: 512, players_left: 2, captain: 'Salah', chip: null, is_you: true }],
  }) as LiveLeague;
  expect(leagueCard(league(1, 0), 'Gold FC')).toMatchObject({ big: '1st', sub: 'Top of the league', eyebrow: 'Gameweek 9 · Mates' });
  expect(leagueCard(league(2, 7), 'Gold FC')).toMatchObject({ big: '2nd', sub: '7 behind the leader' });
  expect(leagueCard(league(3, 9), 'Gold FC').big).toBe('3rd');
  expect(leagueCard(league(11, 9), 'Gold FC').big).toBe('11th');
  expect(leagueCard(league(22, 9), 'Gold FC').big).toBe('22nd');
});
