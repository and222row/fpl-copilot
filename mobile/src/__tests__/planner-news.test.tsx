import { render, screen, userEvent } from '@testing-library/react-native';

const mockUsePlanner = jest.fn();
const mockMarkRead = jest.fn();

jest.mock('react-native-safe-area-context', () => require('react-native-safe-area-context/jest/mock').default);
jest.mock('expo-router', () => ({ router: { push: jest.fn() }, Stack: { Screen: () => null } }));
jest.mock('@/lib/api', () => ({ api: { markAlertsRead: (...a: unknown[]) => mockMarkRead(...a) } }));
jest.mock('@/lib/query', () => {
  const ok = (data: unknown) => ({ data, isPending: false, isError: false, isRefetching: false, refetch: jest.fn() });
  const f = require('@/lib/__fixtures__/planner-news');
  return {
    useTeamId: () => 1234,
    usePlanner: (...a: unknown[]) => mockUsePlanner(...a),
    useAlerts: () => ok(f.alerts),
    useNewsEvents: () => ok(f.events),
    usePriceWatch: () =>
      ok([{ player_id: 7, name: 'Semenyo', team: 'BOU', price: 7.1, direction: 'rise', percent_to_threshold: 72, net_transfers_gw: 1 }]),
    queryClient: { invalidateQueries: jest.fn() },
    queryKeys: { alerts: (id: number) => ['alerts', id] },
  };
});

import { plan } from '@/lib/__fixtures__/planner-news';
import News from '@/app/news';
import Planner from '@/app/planner';

beforeEach(() => {
  mockUsePlanner.mockReset().mockReturnValue({ data: plan, isPending: false, isError: false, refetch: jest.fn() });
  mockMarkRead.mockReset().mockResolvedValue({ marked_read: 2 });
});

describe('planner', () => {
  test('lays out the best path gameweek by gameweek', async () => {
    await render(<Planner />);
    expect(screen.getByText('Best path · GW8–10')).toBeTruthy();
    expect(screen.getByText('171.4 pts')).toBeTruthy();
    expect(screen.getByText('GW9')).toBeTruthy();
    expect(screen.getByText('Wissa')).toBeTruthy();
    expect(screen.getByText('Watkins')).toBeTruthy();
  });

  test('warns about a later buy that may rise in price, not one made now', async () => {
    await render(<Planner />);
    expect(screen.getByText(/Watkins is 72% of the way to a price rise and may cost more by\s+GW9/)).toBeTruthy();
    expect(screen.queryByText(/Saka is .* price rise/)).toBeNull(); // bought in GW8, today's price
  });

  test('shows what else was considered at each decision', async () => {
    await render(<Planner />);
    // Rolling was the runner-up at both transfer decisions, each 2 points worse.
    expect(screen.getAllByText('Also considered: Roll (−2.0 pts)')).toHaveLength(2);
  });

  test('changing the horizon re-plans', async () => {
    const user = userEvent.setup();
    await render(<Planner />);
    expect(mockUsePlanner).toHaveBeenLastCalledWith(1234, 3);
    await user.press(screen.getByText('5 GW'));
    expect(mockUsePlanner).toHaveBeenLastCalledWith(1234, 5);
  });
});

describe('news', () => {
  test('alerts come first, and unread ones can be cleared', async () => {
    const user = userEvent.setup();
    await render(<News />);
    expect(screen.getByText('Timber is a doubt')).toBeTruthy();
    await user.press(screen.getByText('Mark 1 as read'));
    expect(mockMarkRead).toHaveBeenCalledWith(1234);
  });

  test('the feed shows category and source, and hides price moves', async () => {
    const user = userEvent.setup();
    await render(<News />);
    await user.press(screen.getByText('All news'));
    expect(screen.getByText('Wissa · NEW')).toBeTruthy();
    expect(screen.getByText('Injury')).toBeTruthy();
    expect(screen.getAllByText(/^FPL official · /).length).toBe(2);
    expect(screen.queryByText('Semenyo · BOU')).toBeNull();
    expect(screen.getByText(/could not read this update automatically/)).toBeTruthy();
  });

  test('categories filter the feed', async () => {
    const user = userEvent.setup();
    await render(<News />);
    await user.press(screen.getByText('All news'));
    await user.press(screen.getByText('Suspensions'));
    expect(screen.getByText('Rice · ARS')).toBeTruthy();
    expect(screen.queryByText('Wissa · NEW')).toBeNull();
  });

  test('price watch shows direction and progress', async () => {
    const user = userEvent.setup();
    await render(<News />);
    await user.press(screen.getByText('Prices'));
    expect(screen.getByText('▲ 72%')).toBeTruthy();
  });
});

