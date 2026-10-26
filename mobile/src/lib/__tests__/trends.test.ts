import type { TrendPlayer } from '@/lib/api';
import { compact, ordinal } from '@/lib/format';
import { likelihoodWord, modelRatesHim, priceAdvice, priceLine, rankLine } from '@/lib/trends';

const player = (extra: Partial<TrendPlayer> = {}): TrendPlayer => ({
  player_id: 1, name: 'Isak', team: 'LIV', position: 'FWD', price: 9, kit: null, ownership: 15.1,
  transfers_in: 144_795, transfers_out: 2_000, net: 142_795, status: 'a', news: null,
  xpts_next: 4.5, xpts_horizon: 20.1, position_rank: 2, position_count: 79, price_move: null, ...extra,
});

test('compact counts and ordinals', () => {
  expect([950, 12_345, 397_922, 1_250_000, -239_752].map(compact)).toEqual(['950', '12.3k', '398k', '1.3m', '−240k']);
  expect([1, 2, 3, 4, 11, 12, 13, 21, 22, 101].map(ordinal)).toEqual(['1st', '2nd', '3rd', '4th', '11th', '12th', '13th', '21st', '22nd', '101st']);
});

test('price lines read FPL\'s forecast in words', () => {
  expect(priceLine({ direction: 'rise', when: 'tonight', offset: 0, likelihood: 5, progress: 90 })).toBe('Rises tonight (very likely)');
  expect(priceLine({ direction: 'fall', when: 'tomorrow', offset: 1, likelihood: 3, progress: -80 })).toBe('Falls tomorrow (possible)');
  expect([5, 4, 3, 2, null].map(likelihoodWord)).toEqual(['very likely', 'likely', 'possible', 'unlikely', '']);
});

test('the model rates the top fifth of a position', () => {
  expect(rankLine(player())).toBe('The model ranks him 2nd of 79 forwards');
  expect(modelRatesHim(player())).toBe(true);
  expect(modelRatesHim(player({ position_rank: 40 }))).toBe(false);
  expect(rankLine(player({ position_rank: null }))).toBeNull();
});

test('price advice is only for tonight, and only when it matters to you', () => {
  const tonight = (direction: 'rise' | 'fall') => ({ direction, when: 'tonight', offset: 0, likelihood: 5, progress: 95 });
  expect(priceAdvice(player({ price_move: tonight('fall') }), true)).toBe('You own him: selling before tonight saves £0.1m.');
  expect(priceAdvice(player({ price_move: tonight('fall') }), false)).toBeNull();
  expect(priceAdvice(player({ price_move: tonight('rise') }), false)).toBe('The model rates him: buying before tonight saves £0.1m.');
  expect(priceAdvice(player({ price_move: tonight('rise'), position_rank: 50 }), false)).toBeNull();
  expect(priceAdvice(player({ price_move: { ...tonight('rise'), offset: 1, when: 'tomorrow' } }), false)).toBeNull();
});
