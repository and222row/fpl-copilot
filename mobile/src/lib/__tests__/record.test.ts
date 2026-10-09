import { bankAfter, blockedReason, hitCost, squadAfter, type Pick } from '@/lib/record';

const p = (player_id: number, position: Pick['position'], team: string, price: number): Pick => ({
  player_id,
  name: `P${player_id}`,
  team,
  position,
  price,
});

const SQUAD = [p(1, 'MID', 'ARS', 8.0), p(2, 'MID', 'LIV', 6.5), p(3, 'DEF', 'ARS', 5.0), p(4, 'FWD', 'ARS', 7.0)];

test('bank moves by the price difference, rounded to £0.1m', () => {
  expect(bankAfter(1.5, [{ out: SQUAD[0], in: p(10, 'MID', 'CHE', 9.2) }])).toBe(0.3);
  expect(bankAfter(0.0, [])).toBe(0.0);
});

test('hits only for transfers beyond the free ones', () => {
  expect(hitCost(1, 1)).toBe(0);
  expect(hitCost(3, 1)).toBe(8);
  expect(hitCost(2, 5)).toBe(0);
});

test('the squad after the moves swaps players in place of those sold', () => {
  const after = squadAfter(SQUAD, [{ out: SQUAD[1], in: p(10, 'MID', 'CHE', 6.0) }]);
  expect(after.map((x) => x.player_id).sort()).toEqual([1, 10, 3, 4]);
});

describe('which players can come in', () => {
  const out = SQUAD[1]; // a £6.5m LIV midfielder

  test('like for like and affordable is allowed', () => {
    expect(blockedReason(p(10, 'MID', 'CHE', 7.0), out, SQUAD, [], 0.5)).toBeNull();
  });

  test('another position is not', () => {
    expect(blockedReason(p(10, 'DEF', 'CHE', 5.0), out, SQUAD, [], 1)).toBe('Not a MID');
  });

  test('a fourth player from one club is not', () => {
    expect(blockedReason(p(10, 'MID', 'ARS', 6.0), out, SQUAD, [], 1)).toBe('Already 3 from ARS');
  });

  test('selling an Arsenal player frees a place for another', () => {
    expect(blockedReason(p(10, 'MID', 'ARS', 8.0), SQUAD[0], SQUAD, [], 0)).toBeNull();
  });

  test('more than the bank plus the sale is not affordable', () => {
    expect(blockedReason(p(10, 'MID', 'CHE', 7.1), out, SQUAD, [], 0.5)).toBe('Not enough in the bank');
  });

  test('someone already in the squad is not offered', () => {
    expect(blockedReason(SQUAD[0], out, SQUAD, [], 9)).toBe('Already in your squad');
  });

  test('earlier moves in the same session count', () => {
    const moves = [{ out: SQUAD[3], in: p(11, 'FWD', 'CHE', 7.0) }];
    // Selling the Arsenal forward made room for an Arsenal midfielder.
    expect(blockedReason(p(10, 'MID', 'ARS', 6.0), out, SQUAD, moves, 1)).toBeNull();
  });
});
