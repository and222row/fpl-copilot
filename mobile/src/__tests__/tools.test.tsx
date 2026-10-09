import { render, screen, userEvent, waitFor } from '@testing-library/react-native';

const mockRecord = jest.fn();
const mockBack = jest.fn();
const mockPush = jest.fn();
const mockRefresh = jest.fn();
const mockQueries: Record<string, unknown> = {};

jest.mock('react-native-safe-area-context', () => require('react-native-safe-area-context/jest/mock').default);
jest.mock('react-native-purchases', () => ({}));
jest.mock('expo-router', () => ({
  router: { back: () => mockBack(), push: (...a: unknown[]) => mockPush(...a) },
  useLocalSearchParams: () => mockQueries.params ?? {},
  Stack: { Screen: () => null },
}));
jest.mock('@/lib/api', () => ({
  ApiError: class ApiError extends Error {},
  api: { recordTransfers: (...a: unknown[]) => mockRecord(...a) },
}));
jest.mock('@/lib/query', () => ({
  useTeamId: () => 6727534,
  useRecommendation: () => mockQueries.recommendation,
  usePlayers: () => mockQueries.players,
  useLeagues: () => mockQueries.leagues,
  useLeague: () => mockQueries.league,
  useRival: () => mockQueries.rival,
  useChips: () => mockQueries.chips,
  useDreamTeam: () => mockQueries.dream,
  useTrackRecord: () => mockQueries.record,
  refreshSquadDerived: () => mockRefresh(),
}));

import Chips from '@/app/chips';
import DreamTeam from '@/app/dream-team';
import League from '@/app/league/[id]';
import Leagues from '@/app/leagues';
import RecordTransfers from '@/app/record-transfers';
import Rival from '@/app/rival/[id]';
import TrackRecord from '@/app/track-record';

const ok = (data: unknown) => ({ data, isPending: false, isError: false, isSuccess: true, isRefetching: false, refetch: jest.fn() });

const brief = (player_id: number, name: string, position: string, team: string, price: number) => ({
  player_id, name, position, team, price, xpts: 4, p_start: 0.9, status: 'a',
});

const SQUAD_XI = [
  brief(1, 'Raya', 'GKP', 'ARS', 5.5),
  brief(2, 'Gabriel', 'DEF', 'ARS', 6.0),
  brief(3, 'Saka', 'MID', 'ARS', 10.0),
  brief(4, 'Salah', 'MID', 'LIV', 13.0),
  brief(5, 'Haaland', 'FWD', 'MCI', 15.0),
];

beforeEach(() => {
  for (const k of Object.keys(mockQueries)) delete mockQueries[k];
  [mockRecord, mockBack, mockPush, mockRefresh].forEach((m) => m.mockReset());
  mockQueries.recommendation = ok({ bank: 5, free_transfers: 1, lineup: { starting: SQUAD_XI, bench: [] } });
});

describe('record transfers', () => {
  test('sell, pick an allowed replacement, and save the move', async () => {
    const user = userEvent.setup();
    mockQueries.players = {
      ...ok(undefined),
      data: { pages: [{ items: [
        { player_id: 9, name: 'Odegaard', team: 'ARS', position: 'MID', price: 8.0, xpts: 5.1 },
        { player_id: 10, name: 'Palmer', team: 'CHE', position: 'MID', price: 10.5, xpts: 6.2 },
        { player_id: 11, name: 'Mbeumo', team: 'MUN', position: 'MID', price: 7.5, xpts: 4.8 },
      ] }] },
      isFetching: false,
      hasNextPage: false,
    };
    mockRecord.mockResolvedValue({ free_transfers: 0 });

    await render(<RecordTransfers />);
    await user.press(screen.getByTestId('sell-4')); // Salah, LIV midfielder, £13.0m

    // A fourth Arsenal player is refused; Palmer is affordable (13.0 + 0.5).
    expect(screen.getByText(/Already 3 from ARS/)).toBeTruthy();
    await user.press(screen.getByTestId('buy-10'));

    expect(screen.getByText('Salah → Palmer')).toBeTruthy();
    expect(screen.getByText('£3.0m')).toBeTruthy(); // 0.5 + 13.0 − 10.5
    await user.press(screen.getByText('Save 1 transfer'));
    await waitFor(() => expect(mockBack).toHaveBeenCalled());
    expect(mockRecord).toHaveBeenCalledWith(6727534, [{ out: 4, in: 10 }]);
    expect(mockRefresh).toHaveBeenCalled();
  });

  test('a second transfer beyond the free one shows the hit', async () => {
    const user = userEvent.setup();
    mockQueries.players = {
      ...ok(undefined),
      data: { pages: [{ items: [
        { player_id: 10, name: 'Palmer', team: 'CHE', position: 'MID', price: 10.5, xpts: 6 },
        { player_id: 12, name: 'Isak', team: 'NEW', position: 'FWD', price: 9.0, xpts: 6 },
      ] }] },
      isFetching: false,
      hasNextPage: false,
    };
    await render(<RecordTransfers />);
    await user.press(screen.getByTestId('sell-4'));
    await user.press(screen.getByTestId('buy-10'));
    await user.press(screen.getByTestId('sell-5'));
    await user.press(screen.getByTestId('buy-12'));
    expect(screen.getByText('−4')).toBeTruthy();
  });
});

describe('mini-leagues', () => {
  test('your own leagues are listed with rank and movement', async () => {
    mockQueries.leagues = ok({ leagues: [
      { id: 911741, name: 'Hossam Hassan Ball', private: true, rank: 3, last_rank: 5, size: 11 },
      { id: 314, name: 'Overall', private: false, rank: 1576239, last_rank: 2402034, size: 10833601 },
    ] });
    await render(<Leagues />);
    expect(screen.getByText('Hossam Hassan Ball')).toBeTruthy();
    expect(screen.getByText('3 of 11 ▲')).toBeTruthy();
    expect(screen.getByText('FPL leagues')).toBeTruthy();
  });

  test('the league shows gaps, threats and the table', async () => {
    const user = userEvent.setup();
    mockQueries.params = { id: '911741' };
    mockQueries.league = ok({
      league: { id: 911741, name: 'Hossam Hassan Ball', private: true, size: 11 },
      your_rank: 3,
      gaps: { to_leader: 23, to_next: 13 },
      standings: [
        { rank: 1, last_rank: 2, entry: 4276486, team_name: 'Poehlerboyz', manager_name: 'Jonas', total: 358, gameweek_points: 57, is_you: false },
        { rank: 3, last_rank: 5, entry: 6727534, team_name: "Andrew's Team", manager_name: 'Andrew', total: 335, gameweek_points: 60, is_you: true },
      ],
      rivals_sampled: 10,
      squads_as_of_gameweek: 5,
      projections_for_gameweek: 6,
      threats: [{ player_id: 10, name: 'Palmer', team: 'CHE', position: 'MID', price: 10.5, xpts: 6.2, owned_by: 8 }],
      differentials: [],
      most_captained: [],
    });
    await render(<League />);
    expect(screen.getByText('−23')).toBeTruthy();
    expect(screen.getByText(/^Palmer/)).toBeTruthy();
    expect(screen.getByText('8/10')).toBeTruthy();
    expect(screen.getByText("Andrew's Team (you)")).toBeTruthy();
    await user.press(screen.getByTestId('standing-4276486'));
    expect(mockPush).toHaveBeenCalledWith({ pathname: '/rival/[id]', params: { id: '4276486', league: '911741' } });
  });

  test('head to head says who the differences favour', async () => {
    mockQueries.params = { id: '4276486', league: '911741' };
    mockQueries.rival = ok({
      league_id: 911741,
      rival: { entry: 4276486, team_name: 'Poehlerboyz', manager_name: 'Jonas', rank: 1, total: 358, gameweek_points: 57, captain: 'Haaland' },
      you: { rank: 3, total: 335, gameweek_points: 60, captain: 'Salah' },
      points_gap: 23,
      shared: [],
      only_yours: [{ player_id: 4, name: 'Salah', team: 'LIV', position: 'MID', price: 13, xpts: 7 }],
      only_theirs: [{ player_id: 10, name: 'Palmer', team: 'CHE', position: 'MID', price: 10.5, xpts: 6 }],
      edge_next_gameweek: 1.0,
      squads_as_of_gameweek: 5,
      projections_for_gameweek: 6,
    });
    await render(<Rival />);
    expect(screen.getByText('23 ahead')).toBeTruthy();
    expect(screen.getByText(/Your differences project 1\.0 points more/)).toBeTruthy();
    expect(screen.getByText('Only you have (1)')).toBeTruthy();
  });
});

test('chips are ordered by urgency with a plain verdict', async () => {
  mockQueries.chips = ok({
    manager_id: 6727534,
    target_gameweek: 6,
    horizon: [6, 7, 8],
    fixture_shape: { doubles: { '7': ['ARS', 'LIV'] }, blanks: {}, gameweeks_scheduled: 38, note: null },
    squad_this_gameweek: { playing: 15, doubling: 0, blank: 0 },
    chips: [
      { name: 'wildcard', label: 'Wildcard', available: true, used_in_gameweek: null, window: { start: 1, end: 19 }, weeks_remaining: 13, value_now: 4, best_value: 6, best_gameweek: 9, baseline: null, verdict: 'hold', confidence: 'low', reasons: ['Save it'] },
      { name: '3xc', label: 'Triple Captain', available: true, used_in_gameweek: null, window: { start: 1, end: 19 }, weeks_remaining: 13, value_now: 9, best_value: 9, best_gameweek: 6, baseline: null, verdict: 'use_now', confidence: 'medium', reasons: ['Haaland at home'] },
      { name: 'freehit', label: 'Free Hit', available: false, used_in_gameweek: 3, window: { start: 1, end: 19 }, weeks_remaining: 13, value_now: null, best_value: null, best_gameweek: null, baseline: null, verdict: 'used', confidence: 'high', reasons: [] },
    ],
    history_available: true,
    caveat: 'The valuations rest on the model.',
  });
  await render(<Chips />);
  expect(screen.getByText('Play this week')).toBeTruthy();
  expect(screen.getByText('Used in GW3')).toBeTruthy();
  expect(screen.getByText(/ARS, LIV/)).toBeTruthy();
  const labels = screen.getAllByText(/^(Wildcard|Triple Captain|Free Hit)$/).map((n) => n.props.children);
  expect(labels[0]).toBe('Triple Captain');
});

test('the dream team counts what you already own', async () => {
  const pick = (player_id: number, name: string, extra = {}) => ({
    player_id, name, team: 'X', position: 'MID', price: 6, photo: null, xpts: 5, gw_xpts: 5, p_start: 0.9,
    is_starting: true, is_captain: false, is_vice_captain: false, bench_order: null, reasons: ['Top projected'], ...extra,
  });
  mockQueries.dream = ok({
    solver_status: 'OPTIMAL', gameweeks: [6, 7, 8], horizon: 3, budget: 50.0, squad_cost: 49.5, money_left: 0.5,
    formation: '3-4-3', projected_next_gw: 60, projected_horizon: 170, captain: 'Haaland', vice_captain: 'Salah',
    starting: [pick(5, 'Haaland', { is_captain: true }), pick(4, 'Salah'), pick(20, 'Palmer')],
    bench: [], explanation_note: 'From the model.', proven_optimal: true,
  });
  await render(<DreamTeam />);
  expect(screen.getByText('2 of these 15 are already in your team, so a wildcard would change 13.')).toBeTruthy();
  expect(screen.getByText('Haaland (C)')).toBeTruthy();
});

describe('track record', () => {
  test('before anything is graded it says what is waiting', async () => {
    mockQueries.record = ok({
      summary: { manager_id: 1, gameweeks_scored: 0, categories: {} },
      history: [],
      pending: { count: 3, pending: [{ snapshot_id: 1, gameweek: 6, kind: 'captain', gameweek_finished: false }] },
    });
    await render(<TrackRecord />);
    expect(screen.getByText('Nothing graded yet')).toBeTruthy();
    expect(screen.getByText('Advice for GW6 is waiting to be graded')).toBeTruthy();
  });

  test('graded categories and gameweeks', async () => {
    mockQueries.record = ok({
      summary: {
        manager_id: 1, gameweeks_scored: 2,
        categories: { captain: { decisions: 2, hit_rate: 0.5, mean_error: 1, mean_absolute_error: 3, mean_regret: 4.5, follow_rate: 1, points_lost_by_overriding: 6 } },
      },
      history: [{ gameweek: 5, kind: 'captain', predicted: 12, actual: 18, error: 6, regret: 0, correct: true, followed: true, override_delta: 0, detail: null }],
      pending: { count: 0, pending: [] },
    });
    await render(<TrackRecord />);
    expect(screen.getByText('2 gameweeks graded')).toBeTruthy();
    expect(screen.getByText('50%')).toBeTruthy();
    expect(screen.getByText(/Following the advice would have gained you 6\.0 points/)).toBeTruthy();
    expect(screen.getByText('Right')).toBeTruthy();
  });
});
