import type { PlayerBrief, Position, Recommendation } from '@/lib/api';
import {
  availabilityLabel, benchLabels, betterSide, marketVerdict, money, pitchRows, signed, verdictFor,
} from '@/lib/squad';

const brief = (player_id: number, position: Position = 'MID'): PlayerBrief => ({
  player_id, name: `P${player_id}`, team: 'ARS', position, price: 5, xpts: 4, p_start: 0.9, status: 'a',
});
const move = (player_id: number) => ({
  player_id, name: '', team: '', position: 'MID', price: 5, horizon_xpts: 10, status: 'a' as const,
});

const rec = {
  lineup: { starting: [brief(1), brief(2)], bench: [{ ...brief(3), bench_order: 0 }] },
  transfer: { plan: { out: [move(2)], in: [move(9)] } },
} as unknown as Recommendation;

test('the optimiser decides every verdict', () => {
  expect(verdictFor(1, rec)).toBe('START');
  expect(verdictFor(3, rec)).toBe('BENCH');
  expect(verdictFor(2, rec)).toBe('SELL'); // a starter being sold reads SELL, not START
  expect(verdictFor(9, rec)).toBe('BUY');
  expect(verdictFor(42, rec)).toBeNull();
  expect(verdictFor(1, undefined)).toBeNull();
});

test('on the player screen an owned, unchanged player is HOLD', () => {
  expect(marketVerdict(1, rec)).toBe('HOLD');
  expect(marketVerdict(3, rec)).toBe('HOLD');
  expect(marketVerdict(2, rec)).toBe('SELL');
  expect(marketVerdict(9, rec)).toBe('BUY');
});

test('availability labels prefer the percentage for doubts', () => {
  expect(availabilityLabel('a', null)).toBeNull();
  expect(availabilityLabel('d', 75)).toBe('75%');
  expect(availabilityLabel('d', null)).toBe('Doubt');
  expect(availabilityLabel('i', 0)).toBe('Injured');
  expect(availabilityLabel('s', null)).toBe('Suspended');
});

test('pitch rows run keeper to forwards and skip empty lines', () => {
  const rows = pitchRows([brief(1, 'FWD'), brief(2, 'GKP'), brief(3, 'DEF'), brief(4, 'DEF')]);
  expect(rows.map((r) => r.map((p) => p.player_id))).toEqual([[2], [3, 4], [1]]);
});

test('bench labels number outfield subs after the reserve keeper', () => {
  expect(benchLabels([{ position: 'GKP' }, { position: 'DEF' }, { position: 'MID' }, { position: 'FWD' }]))
    .toEqual(['GK', '1', '2', '3']);
});

test('comparison highlights the better side in the right direction', () => {
  expect(betterSide('high', 8, 6)).toBe('left');
  expect(betterSide('high', 6, 8)).toBe('right');
  expect(betterSide('low', 8.5, 6.0)).toBe('right'); // cheaper wins on price
  expect(betterSide('low', 2.1, 3.4)).toBe('left'); // easier fixtures win
  expect(betterSide('high', 5, 5)).toBeNull();
  expect(betterSide(null, 40, 10)).toBeNull(); // ownership has no "better"
});

test('formatting', () => {
  expect(money(15)).toBe('£1.5m');
  expect(signed(6.44)).toBe('+6.4');
  expect(signed(-4)).toBe('−4.0');
});
