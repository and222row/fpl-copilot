import type { PlannerTeam } from '@/lib/api';
import { byEase, colours, DIFFICULTY_COLOURS, ownedByClub, step } from '@/lib/fixtures';
import { perPoint, role } from '@/lib/live';

test('model difficulty maps onto FPL\'s five colours', () => {
  expect([1, 1.7, 1.8, 2.6, 3.3, 4, 5].map(step)).toEqual([1, 1, 2, 3, 4, 5, 5]);
  expect(colours(1.2)).toBe(DIFFICULTY_COLOURS[0]);
  expect(colours(4.6)).toBe(DIFFICULTY_COLOURS[4]);
});

test('runs sort by ease for the chosen view, then by name', () => {
  const t = (team: string, overall: number, attack: number): PlannerTeam => ({
    team_id: 0, team, name: team, fixtures: [], ease: { overall, attack, defence: 0 }, doubles: [], blanks: [],
  });
  const teams = [t('BUR', 5, 9), t('ARS', 8, 1), t('CHE', 8, 4)];
  expect(byEase(teams, 'overall').map((x) => x.team)).toEqual(['ARS', 'CHE', 'BUR']);
  expect(byEase(teams, 'attack').map((x) => x.team)).toEqual(['BUR', 'CHE', 'ARS']);
});

test('your players are counted by club', () => {
  expect(ownedByClub([{ team: 'ARS' }, { team: 'LIV' }, { team: 'ARS' }])).toEqual({ ARS: 2, LIV: 1 });
});

test('swing wording', () => {
  expect([0, 1, 2, 3].map(role)).toEqual(['—', 'owned', 'captain', 'triple captain']);
  expect(perPoint(1)).toBe('+1 per point');
  expect(perPoint(-0.4)).toBe('−0.4 per point');
  expect(perPoint(1.35)).toBe('+1.4 per point');
});
