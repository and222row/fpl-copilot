// Render tests for the squad screens. There is no device in CI, so these are
// what catch a screen that crashes on real response shapes or is wired to the
// wrong recommendation.
import { render, screen, userEvent, within } from '@testing-library/react-native';

import { recommendation, watkins, watkinsDetail, wissa } from '@/lib/__fixtures__/recommendation';

const mockPush = jest.fn();
const mockRecordTransfers = jest.fn();
const mockUseTransfers = jest.fn();
const mockUsePlayer = jest.fn();

jest.mock('react-native-safe-area-context', () => require('react-native-safe-area-context/jest/mock').default);
jest.mock('expo-router', () => ({
  router: { push: (...a: unknown[]) => mockPush(...a), back: jest.fn() },
  useLocalSearchParams: () => ({ id: String(require('@/lib/__fixtures__/recommendation').watkins.player_id) }),
  Stack: { Screen: () => null },
}));
jest.mock('expo-image', () => ({ Image: () => null }));
jest.mock('@/lib/api', () => ({
  api: { recordTransfers: (...a: unknown[]) => mockRecordTransfers(...a), resetRecordedTransfers: jest.fn() },
}));
jest.mock('@/lib/query', () => {
  const { recommendation: rec } = require('@/lib/__fixtures__/recommendation');
  const ok = (data: unknown) => ({ data, isPending: false, isError: false, isRefetching: false, refetch: jest.fn() });
  return {
    useTeamId: () => 1234,
    useRecommendation: () => ok(rec),
    useTransfers: (...a: unknown[]) => mockUseTransfers(...a),
    useCaptain: () => ok({ modes: { safe: { ranking: [], confidence: null }, balanced: { ranking: [], confidence: null }, differential: { ranking: [], confidence: null } } }),
    usePlayer: (...a: unknown[]) => mockUsePlayer(...a),
    refreshSquadDerived: jest.fn(),
  };
});

import { Pitch } from '@/components/pitch';
import Transfers from '@/app/(tabs)/transfers';
import PlayerScreen from '@/app/player/[id]';
import { Alert } from 'react-native';

beforeEach(() => {
  mockPush.mockReset();
  mockRecordTransfers.mockReset().mockResolvedValue({ free_transfers: 0 });
  mockUseTransfers.mockReset().mockReturnValue({ data: undefined, isPending: false, isError: false });
  mockUsePlayer.mockReset().mockReturnValue({ data: watkinsDetail, isPending: false, isError: false, refetch: jest.fn() });
});

describe('pitch', () => {
  test('shows the eleven with captaincy, availability and verdicts', async () => {
    await render(<Pitch rec={recommendation} />);
    for (const p of recommendation.lineup.starting) expect(screen.getByText(p.name)).toBeTruthy();

    const haaland = screen.getByLabelText(/^Haaland,/);
    expect(within(haaland).getByText('C')).toBeTruthy();

    // Timber's doubt reads as a percentage; Wissa is injured and being sold.
    expect(screen.getByLabelText(/^Timber,.*75%.*START$/)).toBeTruthy();
    expect(screen.getByLabelText(/^Wissa,.*Injured.*SELL$/)).toBeTruthy();
  });

  test('tapping a player opens his screen', async () => {
    const user = userEvent.setup();
    await render(<Pitch rec={recommendation} />);
    await user.press(screen.getByLabelText(/^Saka,/));
    expect(mockPush).toHaveBeenCalledWith({ pathname: '/player/[id]', params: { id: expect.any(String) } });
  });
});

describe('transfers', () => {
  test('shows the move, its cost, budget impact and reasons', async () => {
    await render(<Transfers />);
    expect(screen.getByText('TRANSFER')).toBeTruthy();
    expect(screen.getByText('84%')).toBeTruthy();
    expect(screen.getByText('Free')).toBeTruthy(); // no hit
    expect(screen.getByText('£1.5m')).toBeTruthy(); // bank now
    expect(screen.getByText('£0.0m')).toBeTruthy(); // bank after
    expect(screen.getByText('+26.3 pts / 5 GW')).toBeTruthy();
    expect(screen.getByText('−£2.9m')).toBeTruthy(); // Watkins costs £2.9m more than Wissa
    expect(screen.getByText(/Wissa is injured/)).toBeTruthy();
    expect(screen.getByText(/Roll the transfer/)).toBeTruthy();
  });

  test('five gameweeks reuses the shared recommendation; others ask the server', async () => {
    const user = userEvent.setup();
    await render(<Transfers />);
    expect(mockUseTransfers).toHaveBeenLastCalledWith(1234, 5, false);
    await user.press(screen.getByText('Next GW'));
    expect(mockUseTransfers).toHaveBeenLastCalledWith(1234, 1, true);
  });

  test('recording sends the exact moves after confirmation', async () => {
    const user = userEvent.setup();
    const alert = jest.spyOn(Alert, 'alert');
    await render(<Transfers />);
    await user.press(screen.getByText("I've made these transfers"));
    const buttons = alert.mock.calls[0][2]!;
    await buttons.find((b) => b.text === 'I made them')!.onPress!();
    expect(mockRecordTransfers).toHaveBeenCalledWith(1234, [{ out: wissa.player_id, in: watkins.player_id }]);
  });
});

describe('player screen', () => {
  test('explains a recommended buy with the optimiser reasons', async () => {
    await render(<PlayerScreen />);
    expect(screen.getByText('Ollie Watkins')).toBeTruthy();
    expect(screen.getByLabelText('Recommendation: BUY')).toBeTruthy();
    expect(screen.getByText('Recommended transfer in, for Wissa.')).toBeTruthy();
    expect(screen.getByText(/Easier fixtures/)).toBeTruthy();
  });

  test('shows fixtures, price pressure and degrades when FPL is down', async () => {
    await render(<PlayerScreen />);
    expect(screen.getByText('BUR (H) · 2.2')).toBeTruthy();
    expect(screen.getByText('LIV (A) · 3.9')).toBeTruthy();
    expect(screen.getByText(/Price likely to rise soon \(64%/)).toBeTruthy();
    expect(screen.getByText(/FPL didn.t respond/)).toBeTruthy();
  });

  test('a player outside the plan is not given a verdict', async () => {
    mockUsePlayer.mockReturnValue({
      data: { ...watkinsDetail, id: 999 },
      isPending: false,
      isError: false,
      refetch: jest.fn(),
    });
    await render(<PlayerScreen />);
    expect(screen.queryByLabelText(/^Recommendation:/)).toBeNull();
    expect(screen.getByText('Not in your recommended transfers this gameweek.')).toBeTruthy();
  });
});
