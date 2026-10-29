import { render, screen, userEvent } from '@testing-library/react-native';

const mockPush = jest.fn();
const mockConnect = jest.fn();
const mockClaim = jest.fn();
const mockRefresh = jest.fn();

jest.mock('react-native-safe-area-context', () => require('react-native-safe-area-context/jest/mock').default);
jest.mock('expo-router', () => ({ router: { push: (...a: unknown[]) => mockPush(...a) } }));
jest.mock('@/lib/api', () => {
  class ApiError extends Error {
    status: number;
    code: string;
    constructor(status: number, code: string, message: string) {
      super(message);
      this.status = status;
      this.code = code;
    }
  }
  return {
    ApiError,
    TEAM_TAKEN: 'TEAM_TAKEN',
    api: { connectTeam: (id: number) => mockConnect(id), claimConnection: (id: number) => mockClaim(id) },
  };
});
jest.mock('@/lib/query', () => ({ refreshAccount: () => mockRefresh() }));
const mockBrowser = jest.fn();
jest.mock('expo-web-browser', () => ({ openBrowserAsync: (...a: unknown[]) => mockBrowser(...a) }));

import TeamId from '@/app/onboarding/team-id';
import { ApiError } from '@/lib/api';

const TEAM = { fpl_entry_id: 1234, team_name: 'Gold Team', manager_name: 'Sam Doe', connected_at: '' };

beforeEach(() => {
  for (const m of [mockPush, mockConnect, mockClaim, mockRefresh]) m.mockReset();
});

test('the Team ID help opens the FPL website, where the ID is shown', async () => {
  const user = userEvent.setup();
  await render(<TeamId />);
  expect(screen.queryByTestId('team-id-open-fpl')).toBeNull(); // folded away until asked for
  await user.press(screen.getByText('Where do I find my Team ID?'));
  expect(screen.getByText('Open the Points tab.')).toBeTruthy();
  await user.press(screen.getByTestId('team-id-open-fpl'));
  expect(mockBrowser).toHaveBeenCalledWith('https://fantasy.premierleague.com/');
});

async function enter(id: string) {
  const user = userEvent.setup();
  await render(<TeamId />);
  await user.type(screen.getByTestId('team-id-input'), id);
  return user;
}

test('a free team connects straight away and is offered the trial behind a proof', async () => {
  mockConnect.mockResolvedValue({
    status: 'connected',
    ...TEAM,
    verified: false,
    trial_started: false,
    trial_available: true,
    entitlement: {},
  });
  mockClaim.mockResolvedValue({ status: 'verification_required', ...TEAM, code: 'K7QM2X' });
  const user = await enter('1234');
  await user.press(screen.getByText('Connect'));

  expect(mockConnect).toHaveBeenCalledWith(1234);
  expect(await screen.findByTestId('connected-screen')).toBeTruthy();
  expect(screen.getByText('Gold Team')).toBeTruthy();
  expect(screen.getByTestId('trial-offer')).toBeTruthy();
  expect(screen.queryByText(/free trial has started/)).toBeNull();
  expect(mockPush).not.toHaveBeenCalled();

  await user.press(screen.getByTestId('start-trial'));
  expect(mockClaim).toHaveBeenCalledWith(1234);
  expect(mockPush).toHaveBeenCalledWith({
    pathname: '/prove',
    params: { teamId: '1234', code: 'K7QM2X', teamName: 'Gold Team' },
  });
});

test('the trial can be left for later', async () => {
  mockConnect.mockResolvedValue({ status: 'connected', ...TEAM, trial_started: false, trial_available: true, entitlement: {} });
  const user = await enter('1234');
  await user.press(screen.getByText('Connect'));
  await user.press(await screen.findByText('Not now'));
  expect(mockRefresh).toHaveBeenCalled();
  expect(mockClaim).not.toHaveBeenCalled();
});

test('a team or account whose trial is spent says so instead of offering one', async () => {
  mockConnect.mockResolvedValue({ status: 'connected', ...TEAM, trial_started: false, trial_available: false, entitlement: {} });
  const user = await enter('1234');
  await user.press(screen.getByText('Connect'));
  expect(await screen.findByText('This team or account has already used its free trial.')).toBeTruthy();
  expect(screen.queryByTestId('trial-offer')).toBeNull();
  await user.press(screen.getByText('Continue'));
  expect(mockRefresh).toHaveBeenCalled();
});

test('a team held by another account offers a takeover with a code', async () => {
  mockConnect.mockRejectedValue(new ApiError(409, 'TEAM_TAKEN', 'taken'));
  mockClaim.mockResolvedValue({ status: 'verification_required', ...TEAM, code: 'K7QM2X' });
  const user = await enter('1234');
  await user.press(screen.getByText('Connect'));

  expect(await screen.findByTestId('team-taken')).toBeTruthy();
  expect(screen.queryByTestId('team-id-error')).toBeNull();

  await user.press(screen.getByTestId('take-over'));
  expect(mockClaim).toHaveBeenCalledWith(1234);
  expect(mockPush).toHaveBeenCalledWith({
    pathname: '/prove',
    params: { teamId: '1234', code: 'K7QM2X', teamName: 'Gold Team' },
  });
});

test('editing the Team ID drops the takeover offer', async () => {
  mockConnect.mockRejectedValue(new ApiError(409, 'TEAM_TAKEN', 'taken'));
  const user = await enter('1234');
  await user.press(screen.getByText('Connect'));
  expect(await screen.findByTestId('team-taken')).toBeTruthy();

  await user.type(screen.getByTestId('team-id-input'), '5');
  expect(screen.queryByTestId('team-taken')).toBeNull();
  expect(screen.getByText('Connect')).toBeTruthy();
});

test('other failures show their message', async () => {
  mockConnect.mockRejectedValue(new ApiError(404, 'HTTP_404', 'No FPL team has that ID'));
  const user = await enter('99');
  await user.press(screen.getByText('Connect'));
  expect((await screen.findByTestId('team-id-error')).props.children).toBe('No FPL team has that ID');
  expect(screen.queryByTestId('team-taken')).toBeNull();
});


test('a proven team shows the trial that just started', async () => {
  const { Connected } = require('@/components/connected');
  await render(
    <Connected
      proven
      result={{ status: 'connected', ...TEAM, trial_started: true, entitlement: { trial_ends_at: '2026-11-09T12:00:00Z' } }}
    />,
  );
  expect(screen.getByText(/30-day free trial has started/)).toBeTruthy();
  expect(screen.getByText('Verified')).toBeTruthy();
  expect(screen.getByText('You can change your FPL team name back now.')).toBeTruthy();
});
