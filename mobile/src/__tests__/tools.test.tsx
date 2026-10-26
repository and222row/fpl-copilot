import { render, screen, userEvent, waitFor, within } from '@testing-library/react-native';

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
  useLive: () => mockQueries.live,
  useLiveLeague: () => mockQueries.liveLeague,
  useReview: () => mockQueries.review,
  useTransferTrends: () => mockQueries.trends,
  useMe: () => ({ data: { fpl_accounts: [{ team_name: "Andrew's Team" }] } }),
  useFixturePlanner: (weeks: number) => (mockQueries.planner as (...a: number[]) => unknown)(weeks),
  refreshSquadDerived: () => mockRefresh(),
}));
jest.mock('expo-image', () => ({ Image: () => null }));
const mockCapture = jest.fn(async (..._a: unknown[]) => 'file:///tmp/card.png');
const mockShare = jest.fn(async (..._a: unknown[]) => undefined);
jest.mock('react-native-view-shot', () => ({ captureRef: (...a: unknown[]) => mockCapture(...a) }));
jest.mock('expo-sharing', () => ({ isAvailableAsync: async () => true, shareAsync: (...a: unknown[]) => mockShare(...a) }));
jest.mock('@/lib/monitoring', () => ({ reportError: jest.fn() }));

import Chips from '@/app/chips';
import DreamTeam from '@/app/dream-team';
import FixturePlannerScreen from '@/app/fixture-planner';
import League from '@/app/league/[id]';
import Leagues from '@/app/leagues';
import Live from '@/app/live';
import LiveLeagueScreen from '@/app/live-league/[id]';
import RecordTransfers from '@/app/record-transfers';
import Review from '@/app/review';
import TransferTrendsScreen from '@/app/transfer-trends';
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
      squad: [
        { player_id: 1, name: 'Raya', team: 'ARS', position: 'GKP', price: 5.5, xpts: 3.8, kit: 'https://kit/shirt_3_1-110.png', fixtures: ['LEE (H)'], slot: 1, starting: true, is_captain: false, is_vice_captain: false, you_own: false },
        { player_id: 5, name: 'Haaland', team: 'MCI', position: 'FWD', price: 15, xpts: 8, kit: 'https://kit/shirt_43-110.png', fixtures: ['LIV (A)'], slot: 11, starting: true, is_captain: true, is_vice_captain: false, you_own: true },
        { player_id: 7, name: 'Dubravka', team: 'BUR', position: 'GKP', price: 4, xpts: 2, kit: null, fixtures: [], slot: 12, starting: false, is_captain: false, is_vice_captain: false, you_own: false },
      ],
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

    // Their team on a pitch, as the FPL app shows it.
    expect(screen.getByTestId('kit-pitch')).toBeTruthy();
    expect(screen.getByLabelText('Haaland, MCI, LIV (A), captain, you own him too')).toBeTruthy();
    expect(screen.getByText('No fixture')).toBeTruthy(); // the benched keeper blanks
    expect(screen.getByLabelText('Their bench')).toBeTruthy();
  });
});

describe('live gameweek', () => {
  const slot = (player_id: number, name: string, position: string, extra = {}) => ({
    player_id, name, team: 'ARS', position, price: 6, xpts: 4, kit: null, fixtures: ['LIV (A)'], slot: player_id,
    starting: true, is_captain: false, is_vice_captain: false, you_own: false,
    points: 2, provisional_bonus: 0, multiplier: 1, minutes: 90, state: 'done', subbed_in: false, subbed_out: false, ...extra,
  });
  const status = { in_play: true, finished: false, matches_done: 6, matches_total: 10, next_kickoff: null };

  test('your points, the armband, projected subs and points on the pitch', async () => {
    mockQueries.leagues = ok({ leagues: [{ id: 911741, name: 'Hossam Hassan Ball', private: true, rank: 3, last_rank: 5, size: 11 }] });
    mockQueries.live = ok({
      ...status,
      gameweek: { id: 8, name: 'Gameweek 8', average: 45, highest: 120 },
      points: 52, provisional_bonus: 6, transfer_cost: 4, players_left: 3, chip: '3xc',
      captain: 'Haaland', armband: 'Salah', auto_subs: [{ out: 'Gabriel', in: 'Saliba' }], total: 512,
      squad: [
        slot(1, 'Raya', 'GKP'),
        slot(4, 'Salah', 'MID', { points: 8, provisional_bonus: 2, multiplier: 3, state: 'playing', is_vice_captain: true }),
        slot(5, 'Haaland', 'FWD', { points: 0, minutes: 0, multiplier: 0, is_captain: true, starting: false, slot: 12 }),
        slot(6, 'Saka', 'MID', { points: 0, minutes: 0, state: 'to_play' }),
      ],
    });
    await render(<Live />);
    expect(screen.getByTestId('live-points').props.children).toEqual([52, ' pts']);
    expect(screen.getByText('includes 6 provisional bonus · −4 for transfers')).toBeTruthy();
    expect(screen.getByText('Live')).toBeTruthy();
    expect(screen.getByText(/Triple Captain played/)).toBeTruthy();
    expect(screen.getByText("Haaland didn't play, so Salah takes the armband.")).toBeTruthy();
    expect(screen.getByText('Saliba on for Gabriel')).toBeTruthy();
    expect(screen.getByLabelText('Salah, ARS, 24 pts · live, vice captain')).toBeTruthy(); // 8 x 3
    expect(screen.getByLabelText('Saka, ARS, LIV (A)')).toBeTruthy(); // yet to play: the fixture
    expect(screen.getByLabelText('Your bench')).toBeTruthy();

    await userEvent.setup().press(screen.getByTestId('live-league-911741'));
    expect(mockPush).toHaveBeenCalledWith({ pathname: '/live-league/[id]', params: { id: '911741', name: 'Hossam Hassan Ball' } });
  });

  test('the live table re-ranks and shows who is still to play', async () => {
    mockQueries.params = { id: '911741' };
    mockQueries.liveLeague = ok({
      ...status,
      league: { id: 911741, name: 'Hossam Hassan Ball', size: 11 },
      gameweek: { id: 8, name: 'Gameweek 8' },
      managers_read: 11, partial: false, your_live_rank: 1, gap_to_leader: 0, gap_to_next: null,
      swing: {
        rival: { entry: 4276486, team_name: 'Poehlerboyz', gap: -7 },
        managers: 10,
        against_rival: [
          { player_id: 5, name: 'Haaland', team: 'MCI', position: 'FWD', state: 'playing', you: 1, them: 2, net: -1 },
        ],
        for_you: [{ player_id: 4, name: 'Salah', team: 'LIV', position: 'MID', state: 'to_play', you: 2, eo: 0.6, net: 1.4 }],
        against_you: [],
      },
      standings: [
        { entry: 6727534, team_name: "Andrew's Team", manager_name: 'Andrew', rank: 3, last_rank: 3, live_rank: 1, gameweek_points: 70, total: 405, players_left: 2, captain: 'Salah', chip: null, is_you: true },
        { entry: 4276486, team_name: 'Poehlerboyz', manager_name: 'Jonas', rank: 1, last_rank: 1, live_rank: 2, gameweek_points: 40, total: 398, players_left: 0, captain: 'Haaland', chip: 'bboost', is_you: false },
      ],
    });
    await render(<LiveLeagueScreen />);
    expect(screen.getByText('#1')).toBeTruthy();
    expect(screen.getByText('Top')).toBeTruthy();
    expect(screen.getByText('(C) Salah · 2 to play')).toBeTruthy();
    expect(screen.getByText('(C) Haaland · 0 to play · Bench Boost')).toBeTruthy();
    expect(screen.getByText('▲')).toBeTruthy(); // you, 3rd at the start of the gameweek

    // Who decides it: against the rival just behind, and against the league.
    expect(screen.getByText('What decides it from here')).toBeTruthy();
    expect(screen.getByText(/7 behind you/)).toBeTruthy();
    expect(screen.getByText('You: owned · them: captain')).toBeTruthy();
    expect(screen.getByText('−1 per point')).toBeTruthy();
    expect(screen.getByText('You: captain · league: 0.6 per point')).toBeTruthy();
    expect(screen.getByText('+1.4 per point')).toBeTruthy();
    await userEvent.setup().press(screen.getByTestId('live-standing-4276486'));
    expect(mockPush).toHaveBeenCalledWith({ pathname: '/rival/[id]', params: { id: '4276486', league: '911741' } });
  });
});

test('the gameweek review: points, ranks, captain, best and worst, advice, leagues and the season', async () => {
  const user = userEvent.setup();
  const p = (player_id: number, name: string, points: number, multiplier = 1) => ({
    player_id, name, team: 'ARS', position: 'MID', points, multiplier, contribution: points * multiplier, minutes: 90,
  });
  mockQueries.review = ok({
    gameweek: { id: 8, name: 'Gameweek 8', average: 45, highest: 120 },
    finished: true, points: 49, transfer_cost: 4, chip: '3xc',
    gameweek_rank: 4_000_000, overall_rank: 1_700_000, previous_overall_rank: 1_500_000,
    best: [p(68, 'Tavernier', 10)], worst: [p(154, 'Palmer', -1, 3)],
    captain: { pick: p(154, 'Palmer', -1, 3), best: p(68, 'Tavernier', 10), missed: 22 },
    bench_points: 11, bench: [p(9, 'Kinsky', 9), p(10, 'Kostoulas', 2)], auto_subs: [],
    advice: [{ kind: 'captain', followed: false, correct: true, predicted: 12, actual: 24, regret: 0, override_delta: -22 }],
    leagues: [{ id: 6715, name: 'UKDH', rank: 7, last_rank: 9, size: 32 }],
    season: [
      { gameweek: 7, points: 67, average: 59, overall_rank: 1_500_000 },
      { gameweek: 8, points: 49, average: 45, overall_rank: 1_700_000 },
    ],
  });
  await render(<Review />);
  expect(screen.getByTestId('review-points').props.children).toEqual([49, ' pts']);
  expect(screen.getByText(/4 above the average · −4 for transfers · Triple Captain/)).toBeTruthy();
  const n = (v: number) => v.toLocaleString(); // the phone's locale
  expect(screen.getByText(`  ▼ ${n(200_000)}`)).toBeTruthy();
  expect(screen.getByText('Tavernier scored 10: with the armband he would have given you 22 more.')).toBeTruthy();
  expect(screen.getByText('11 points stayed on your bench, 9 of them from Kinsky.')).toBeTruthy();
  expect(screen.getByText('Following our captain pick would have gained you 22 points.')).toBeTruthy();
  expect(screen.getByText('▲ 2')).toBeTruthy(); // league rank 9 -> 7

  // The season chart: tap a bar to read it.
  expect(screen.getByTestId('season-readout').props.children).toBe(`GW8: 49 points · average 45 · rank ${n(1_700_000)}`);
  await user.press(screen.getByLabelText('Gameweek 7: 67 points, average 59'));
  expect(screen.getByTestId('season-readout').props.children).toBe(`GW7: 67 points · average 59 · rank ${n(1_500_000)}`);

  // Share: the card shows first, then becomes a 1080x1350 PNG for the share sheet.
  await user.press(screen.getByText('Share your gameweek'));
  const card = within(screen.getByTestId('share-card'));
  expect(card.getByText("Andrew's Team")).toBeTruthy();
  expect(card.getByText('Star: Tavernier 10')).toBeTruthy();
  expect(card.getByText('Captain: Palmer −3')).toBeTruthy();
  await user.press(screen.getByTestId('share-send'));
  await waitFor(() => expect(mockShare).toHaveBeenCalled());
  expect(mockCapture.mock.calls[0][1]).toMatchObject({ format: 'png', result: 'tmpfile', width: 1080, height: 1350 });
  expect(mockShare).toHaveBeenCalledWith('file:///tmp/card.png', expect.objectContaining({ mimeType: 'image/png', UTI: 'public.png' }));
});

test('transfer trends: buys with the model\'s alternative, sells it disagrees with, and tonight\'s prices', async () => {
  const user = userEvent.setup();
  const t = (player_id: number, name: string, extra = {}) => ({
    player_id, name, team: 'ARS', position: 'FWD', price: 6.7, kit: null, ownership: 8, transfers_in: 0, transfers_out: 0,
    net: 0, status: 'a', news: null, xpts_next: 3, xpts_horizon: 14.3, position_rank: 10, position_count: 79, price_move: null, ...extra,
  });
  mockQueries.trends = ok({
    gameweek: { id: 9, name: 'Gameweek 9' },
    horizon: 5,
    most_bought: [
      t(30, 'N.Jackson', { transfers_in: 397_922, alternative: t(31, 'Gonzalo', { price: 6, xpts_horizon: 16.9 }) }),
      t(32, 'Isak', { transfers_in: 144_795, position_rank: 2, alternative: null }),
    ],
    most_sold: [t(3, 'Saka', { position: 'MID', transfers_out: 164_446, position_rank: 2, position_count: 299 })],
    rising: [t(33, 'Tavernier', { price_move: { direction: 'rise', when: 'tonight', offset: 0, likelihood: 5, progress: 83 }, position_rank: 2 })],
    // Raya is in the mocked squad.
    falling: [t(1, 'Raya', { position: 'GKP', price_move: { direction: 'fall', when: 'tonight', offset: 0, likelihood: 4, progress: -90 } })],
  });
  await render(<TransferTrendsScreen />);
  expect(screen.getByText('+398k')).toBeTruthy();
  expect(screen.getByText('The model prefers Gonzalo (£6.0m): 16.9 vs 14.3 over 5 GW')).toBeTruthy();
  expect(screen.getByText('The model agrees: 2nd of 79 forwards.')).toBeTruthy();

  await user.press(screen.getByText('Most sold'));
  expect(screen.getByText('−164k')).toBeTruthy();
  expect(screen.getByText('The model ranks him 2nd of 299 midfielders: selling may be a mistake.')).toBeTruthy();
  expect(screen.getByText('Yours')).toBeTruthy(); // Saka is in your squad

  await user.press(screen.getByText('Price changes'));
  expect(screen.getByText('Rises tonight (very likely)')).toBeTruthy();
  expect(screen.getByText('The model rates him: buying before tonight saves £0.1m.')).toBeTruthy();
  expect(screen.getByText('You own him: selling before tonight saves £0.1m.')).toBeTruthy();
});

test('the fixture planner ranks runs by the chosen view and marks doubles, blanks and your clubs', async () => {
  const user = userEvent.setup();
  const m = (opponent: string, home: boolean, attack: number, defence: number) => ({
    opponent, home, fpl: 3, attack, defence, overall: (attack + defence) / 2,
  });
  const team = (team_id: number, team: string, fixtures: ReturnType<typeof m>[][], ease: [number, number, number]) => ({
    team_id, team, name: team, fixtures: fixtures.map((matches, i) => ({ gameweek: 9 + i, matches })),
    ease: { overall: ease[0], attack: ease[1], defence: ease[2] }, doubles: [], blanks: [],
  });
  const weeks: number[] = [];
  mockQueries.planner = (w: number) => {
    weeks.push(w);
    return ok({
      gameweeks: [9, 10],
      source: 'model',
      teams: [
        // Easier for defenders, harder for attackers.
        team(1, 'ARS', [[m('bur', true, 3.5, 1.2)], []], [6, 2.5, 8]),
        team(2, 'LIV', [[m('che', false, 1.5, 3.4), m('ful', true, 2, 3)], [m('eve', true, 1.6, 2.6)]], [7, 9, 5]),
      ],
    });
  };
  await render(<FixturePlannerScreen />);
  expect(weeks.at(-1)).toBe(6);

  const order = () => screen.getAllByTestId(/^planner-/).map((n) => n.props.testID);
  expect(order()).toEqual(['planner-LIV', 'planner-ARS']); // overall ease 7 > 6
  expect(screen.getByLabelText('Blank: no fixture')).toBeTruthy();
  expect(screen.getByText('BUR')).toBeTruthy(); // home in capitals
  expect(screen.getByText('che')).toBeTruthy(); // away in lower case
  expect(screen.getByLabelText('3 of your players')).toBeTruthy(); // Raya, Gabriel and Saka are ARS

  await user.press(screen.getByText('For defenders'));
  expect(order()).toEqual(['planner-ARS', 'planner-LIV']);
  await user.press(screen.getByText('Next 3'));
  expect(weeks.at(-1)).toBe(3);
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
