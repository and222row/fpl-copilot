import { render, screen, userEvent, waitFor } from '@testing-library/react-native';

const USER = '11111111-1111-4111-8111-111111111111';
const mockPurchase = jest.fn();
const mockRestore = jest.fn();
const mockSync = jest.fn();
const mockRefresh = jest.fn();
const mockAvailable = jest.fn();

jest.mock('react-native-safe-area-context', () => require('react-native-safe-area-context/jest/mock').default);
jest.mock('react-native-purchases', () => ({}));
jest.mock('expo-router', () => ({ router: { push: jest.fn() }, Link: () => null }));
jest.mock('@/lib/config', () => ({ config: { termsUrl: 'https://x.test/terms', privacyUrl: 'https://x.test/privacy' } }));
jest.mock('@/lib/auth', () => ({
  useAuth: () => ({ session: { user: { id: '11111111-1111-4111-8111-111111111111' } }, signOut: jest.fn() }),
}));
jest.mock('@/lib/billing', () => ({
  billingAvailable: () => mockAvailable(),
  loadPlans: async () => ({
    monthly: { identifier: '$rc_monthly', product: { price: 3.99, priceString: '€3.99' } },
    annual: { identifier: '$rc_annual', product: { price: 29.99, priceString: '€29.99' } },
    annualSavingPercent: 37,
  }),
  purchase: (...a: unknown[]) => mockPurchase(...a),
  restore: (...a: unknown[]) => mockRestore(...a),
}));
jest.mock('@/lib/api', () => ({ api: { syncBilling: () => mockSync() } }));
jest.mock('@/lib/query', () => ({
  refreshAccount: () => mockRefresh(),
  useEntitlement: () => ({ data: { status: 'EXPIRED', premium: false }, isFetching: false }),
}));

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Paywall from '@/app/paywall';

async function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  await render(
    <QueryClientProvider client={client}>
      <Paywall />
    </QueryClientProvider>,
  );
  await screen.findByText('€29.99 / year');
}

beforeEach(() => {
  [mockPurchase, mockRestore, mockSync, mockRefresh, mockAvailable].forEach((m) => m.mockReset());
  mockAvailable.mockReturnValue(true);
  mockSync.mockResolvedValue({ premium: true });
});

test('prices and the saving come from the store', async () => {
  await show();
  expect(screen.getByText('€3.99 / month')).toBeTruthy();
  expect(screen.getByText('Save 37% vs monthly')).toBeTruthy();
  expect(screen.getByText('Your free trial or subscription has ended.')).toBeTruthy();
});

test('the renewal disclosure names the selected price and how to cancel', async () => {
  const user = userEvent.setup();
  await show();
  expect(screen.getByText(/€29\.99 per year, charged to your .* when you confirm\./)).toBeTruthy();
  expect(screen.getByText(/renews automatically unless cancelled at least 24 hours/)).toBeTruthy();
  await user.press(screen.getByText('€3.99 / month'));
  expect(screen.getByText(/€3\.99 per month/)).toBeTruthy();
});

test('buying asks the server to confirm, and only the server unlocks', async () => {
  const user = userEvent.setup();
  mockPurchase.mockResolvedValue('purchased');
  await show();
  await user.press(screen.getByText('Subscribe'));
  await waitFor(() => expect(mockRefresh).toHaveBeenCalled());
  expect(mockPurchase).toHaveBeenCalledWith(expect.objectContaining({ identifier: '$rc_annual' }), USER);
  expect(mockSync).toHaveBeenCalled();
});

test('a cancelled purchase does nothing', async () => {
  const user = userEvent.setup();
  mockPurchase.mockResolvedValue('cancelled');
  await show();
  await user.press(screen.getByText('Subscribe'));
  await waitFor(() => expect(mockPurchase).toHaveBeenCalled());
  expect(mockSync).not.toHaveBeenCalled();
});

test('a pending purchase explains the wait', async () => {
  const user = userEvent.setup();
  mockPurchase.mockResolvedValue('pending');
  await show();
  await user.press(screen.getByText('Subscribe'));
  expect(await screen.findByText(/waiting for approval/)).toBeTruthy();
  expect(mockSync).not.toHaveBeenCalled();
});

test('restore with nothing to restore says so', async () => {
  const user = userEvent.setup();
  mockRestore.mockResolvedValue(undefined);
  mockSync.mockResolvedValue({ premium: false });
  await show();
  await user.press(screen.getByText('Restore purchases'));
  expect(await screen.findByText(/No active subscription was found/)).toBeTruthy();
});

test('without billing on the device the buttons cannot be used', async () => {
  mockAvailable.mockReturnValue(false);
  const client = new QueryClient({ defaultOptions: { queries: { gcTime: Infinity } } });
  await render(
    <QueryClientProvider client={client}>
      <Paywall />
    </QueryClientProvider>,
  );
  expect(screen.getByText('Subscriptions are not available on this device.')).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Subscribe' })).toBeDisabled();
});
