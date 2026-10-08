import type { PlanPlayer, PlanStep } from '@/lib/api';
import { timeAgo } from '@/lib/format';
import { alternativesAt, pairByPosition, priceRisks } from '@/lib/planner';

const step = (id: number, parent_id: number | null, cumulative: number, remaining: number, extra: Partial<PlanStep> = {}): PlanStep => ({
  id, parent_id, gameweek: 8, depth: 1, action: 'Roll', transfers: 0, hit: 0, in: [], out: [],
  bank: 0, free_transfers: 1, gw_xpts: 50, cumulative_xpts: cumulative, remaining_value: remaining,
  pruned: false, on_best_path: false, ...extra,
});
const player = (player_id: number, position: number, price_change_percent = 0): PlanPlayer => ({
  player_id, name: `P${player_id}`, team: 'ARS', position, price: 6, price_change_percent,
});

test('alternatives are the siblings at the same decision, best first', () => {
  const chosen = step(2, 0, 55, 200);
  const tree = [
    step(0, null, 0, 250),
    step(1, 0, 52, 199), // roll: 4.0 worse
    chosen,
    step(3, 0, 51, 205), // a hit that pays off later: 256 vs 255, so 1.0 better overall
    step(4, 2, 110, 150), // a child, not a sibling
  ];
  const alts = alternativesAt(chosen, tree);
  expect(alts.map((a) => [a.step.id, a.delta])).toEqual([[3, 1], [1, -4]]);
});

test('transfers pair like-for-like by position', () => {
  const pairs = pairByPosition([player(1, 2), player(2, 4)], [player(3, 4), player(4, 2)]);
  expect(pairs.map(([o, i]) => [o.player_id, i.player_id])).toEqual([[1, 4], [2, 3]]);
});

test('price risk only applies to buys planned for later gameweeks', () => {
  const s = step(5, 2, 0, 0, { in: [player(9, 3, 72), player(10, 3, 20), player(11, 3, -60)] });
  expect(priceRisks(s, 0)).toEqual([]); // buying now locks today's price
  expect(priceRisks(s, 2).map((p) => p.player_id)).toEqual([9]); // falls are not a risk to a buyer
});

test('timeAgo', () => {
  const now = Date.parse('2026-10-08T12:00:00Z');
  expect(timeAgo('2026-10-08T11:59:40Z', now)).toBe('just now');
  expect(timeAgo('2026-10-08T11:48:00Z', now)).toBe('12 min ago');
  expect(timeAgo('2026-10-08T09:00:00Z', now)).toBe('3h ago');
  expect(timeAgo('2026-10-07T11:00:00Z', now)).toBe('1 day ago');
  expect(timeAgo('2026-10-05T12:00:00Z', now)).toBe('3 days ago');
});
