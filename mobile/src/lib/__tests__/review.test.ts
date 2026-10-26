import type { ReviewAdvice } from '@/lib/api';
import { adviceLine, rankMove } from '@/lib/review';

const advice = (extra: Partial<ReviewAdvice>): ReviewAdvice => ({
  kind: 'transfer', followed: false, correct: null, predicted: 0, actual: 0, regret: 0, override_delta: null, ...extra,
});

test('advice lines say how it turned out', () => {
  expect(adviceLine(advice({ kind: 'captain', followed: true, actual: 16 }))).toBe(
    'You followed our captain pick. With the armband he scored 16.',
  );
  expect(adviceLine(advice({ followed: true }))).toBe('You followed our transfer advice.');
  expect(adviceLine(advice({ override_delta: -6 }))).toBe('Following our transfer advice would have gained you 6 points.');
  expect(adviceLine(advice({ kind: 'lineup', override_delta: 1 }))).toBe('Going your own way beat our lineup by 1 point.');
  expect(adviceLine(advice({ override_delta: 0 }))).toBe('Going your own way on the transfer advice made no difference.');
  expect(adviceLine(advice({}))).toBe("You didn't follow our transfer advice.");
});

test('rank movement: a smaller rank is a rise', () => {
  // Numbers follow the phone's locale, so the expectation does too.
  expect(rankMove(1_500_000, 1_200_000)).toEqual({ text: `▲ ${(300_000).toLocaleString()}`, up: true });
  expect(rankMove(3, 5)).toEqual({ text: '▼ 2', up: false });
  expect(rankMove(null, 5)).toBeNull();
  expect(rankMove(5, 5)).toBeNull();
});
