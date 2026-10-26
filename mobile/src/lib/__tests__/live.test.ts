import type { LivePlayer } from '@/lib/api';
import { chipName, liveBadge, liveCaption, shownPoints } from '@/lib/live';

const player = (extra: Partial<LivePlayer> = {}): LivePlayer => ({
  player_id: 1, name: 'Salah', team: 'LIV', position: 'MID', price: 13, xpts: 7, kit: null, fixtures: ['ARS (H)'],
  slot: 1, starting: true, is_captain: false, is_vice_captain: false, you_own: false,
  points: 5, provisional_bonus: 0, multiplier: 1, minutes: 90, state: 'done', subbed_in: false, subbed_out: false,
  ...extra,
});

test('the armband multiplies the points shown', () => {
  expect(shownPoints(player({ multiplier: 2 }))).toBe(10);
  expect(shownPoints(player({ multiplier: 3 }))).toBe(15);
  expect(shownPoints(player({ multiplier: 0 }))).toBe(5); // the bench shows what they scored
});

test('captions: the fixture before kick-off, then points, marked while playing', () => {
  expect(liveCaption(player({ state: 'to_play', minutes: 0, points: 0 }))).toBe('ARS (H)');
  expect(liveCaption(player({ state: 'to_play', minutes: 0, points: 0, fixtures: [] }))).toBe('No fixture');
  expect(liveCaption(player({ state: 'playing', multiplier: 2 }))).toBe('10 pts · live');
  expect(liveCaption(player())).toBe('5 pts');
  // A double: played the first match, the second still to come.
  expect(liveCaption(player({ state: 'to_play', minutes: 90 }))).toBe('5 pts');
});

test('the badge says live, final, or when the next match is', () => {
  const base = { in_play: false, finished: false, matches_done: 4, matches_total: 10, next_kickoff: null };
  expect(liveBadge({ ...base, in_play: true }).label).toBe('Live');
  expect(liveBadge({ ...base, finished: true }).label).toBe('All matches played');
  expect(liveBadge({ ...base, next_kickoff: '2026-10-31T15:00:00Z' }).label).toMatch(/^Next match /);
  expect(liveBadge(base).label).toBe('4 of 10 played');
});

test('chip names', () => {
  expect(chipName('bboost')).toBe('Bench Boost');
  expect(chipName(null)).toBeNull();
  expect(chipName('manager')).toBe('manager');
});
