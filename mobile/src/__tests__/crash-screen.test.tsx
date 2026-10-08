import { render, screen, userEvent } from '@testing-library/react-native';

const mockReport = jest.fn();

jest.mock('react-native-safe-area-context', () => require('react-native-safe-area-context/jest/mock').default);
jest.mock('react-native-purchases', () => ({}));
jest.mock('expo-splash-screen', () => ({ preventAutoHideAsync: jest.fn(), hideAsync: jest.fn() }));
jest.mock('expo-notifications', () => ({}));
jest.mock('@/lib/api', () => ({ ApiError: class ApiError extends Error {} }));
jest.mock('@/lib/auth',() => ({ AuthProvider: ({ children }: { children: unknown }) => children, useAuth: jest.fn() }));
jest.mock('@/lib/push', () => ({ refreshRegistration: jest.fn(), targetFor: jest.fn() }));
jest.mock('@/lib/query', () => ({ queryClient: {}, refreshAccount: jest.fn(), useAccountQueries: jest.fn() }));
jest.mock('@/lib/monitoring', () => ({
  initMonitoring: jest.fn(),
  monitoringEnabled: () => true,
  reportError: (e: unknown) => mockReport(e),
  wrapRoot: (c: unknown) => c,
}));

import { ErrorBoundary } from '@/app/_layout';

test('a crash shows a retry screen and is reported', async () => {
  const user = userEvent.setup();
  const retry = jest.fn(async () => undefined);
  const error = new Error('Cannot read properties of undefined');

  await render(<ErrorBoundary error={error} retry={retry} />);

  expect(screen.getByTestId('crash-screen')).toBeTruthy();
  expect(screen.getByText('FPL Copilot hit an unexpected problem. It has been reported.')).toBeTruthy();
  // The raw message is for the report, not the user.
  expect(screen.queryByText(/Cannot read properties/)).toBeNull();
  expect(mockReport).toHaveBeenCalledWith(error);

  await user.press(screen.getByText('Try again'));
  expect(retry).toHaveBeenCalledTimes(1);
});
