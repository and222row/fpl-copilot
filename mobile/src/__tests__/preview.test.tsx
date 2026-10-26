import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, userEvent } from '@testing-library/react-native';

const mockPreview = jest.fn();
const mockBack = jest.fn();

jest.mock('react-native-safe-area-context', () => require('react-native-safe-area-context/jest/mock').default);
jest.mock('expo-router', () => ({ router: { back: () => mockBack() } }));
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
  return { ApiError, api: { preview: (id: number) => mockPreview(id) } };
});

import Preview from '@/app/preview';
import { ApiError } from '@/lib/api';

const TEASER = {
  team: { id: 1003, name: 'Beg, Steele Or Porro', manager: 'Oliver K', overall_rank: 878_268, total_points: 530, last_gameweek_points: 62 },
  gameweek: { id: 9, name: 'Gameweek 9', deadline_time: null },
  squad: [],
  flagged: [{ name: 'Calafiori', reason: 'Doubtful', news: 'Hip injury - 75% chance of playing' }],
  teaser: { transfers: 2, gain: 18.82, horizon: 5, hit: 4, projected: 59.39, formation: '3-4-3' },
};

async function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const user = userEvent.setup();
  await render(
    <QueryClientProvider client={client}>
      <Preview />
    </QueryClientProvider>,
  );
  return user;
}

beforeEach(() => {
  mockPreview.mockReset();
  mockBack.mockReset();
});

test('a Team ID shows the public details and a teaser, with the players locked', async () => {
  mockPreview.mockResolvedValue(TEASER);
  const user = await show();
  await user.type(screen.getByTestId('preview-input'), '1003');
  await user.press(screen.getByTestId('preview-go'));

  expect(await screen.findByText('Beg, Steele Or Porro')).toBeTruthy();
  expect(mockPreview).toHaveBeenCalledWith(1003);
  expect(screen.getByText(/We found 2 transfers worth \+18\.8 points over the next 5 gameweeks, after the −4 hit\./)).toBeTruthy();
  expect(screen.getByText('Who to sell, who to buy and who to captain unlock when you sign in.')).toBeTruthy();
  expect(screen.getByText(/Hip injury/)).toBeTruthy();

  await user.press(screen.getByTestId('preview-sign-in'));
  expect(mockBack).toHaveBeenCalled(); // back to sign-in
});

test('an unknown team says so', async () => {
  mockPreview.mockRejectedValue(new ApiError(404, 'HTTP_404', 'No FPL team has that ID.'));
  const user = await show();
  await user.type(screen.getByTestId('preview-input'), '999999999');
  await user.press(screen.getByTestId('preview-go'));
  expect((await screen.findByTestId('preview-error')).props.children).toBe('No FPL team has that ID.');
});

test('a squad needing nothing says so instead of a transfer', async () => {
  mockPreview.mockResolvedValue({ ...TEASER, flagged: [], teaser: { ...TEASER.teaser, transfers: 0, gain: 0, hit: 0 } });
  const user = await show();
  await user.type(screen.getByTestId('preview-input'), '1003');
  await user.press(screen.getByTestId('preview-go'));
  expect(await screen.findByText(/we'd roll the transfer this week/)).toBeTruthy();
});
