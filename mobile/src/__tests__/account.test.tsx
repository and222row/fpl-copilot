import { act, fireEvent, render, screen, userEvent, waitFor } from '@testing-library/react-native';
import { Alert, Linking } from 'react-native';

const mockDeleteAccount = jest.fn();
const mockManage = jest.fn();
const mockEntitlement = jest.fn();
const mockPushState = jest.fn();
const mockUpdate = jest.fn();

jest.mock('react-native-safe-area-context', () => require('react-native-safe-area-context/jest/mock').default);
jest.mock('react-native-purchases', () => ({}));
jest.mock('@/lib/auth', () => ({ useAuth: () => ({ deleteAccount: () => mockDeleteAccount() }) }));
jest.mock('@/lib/billing', () => ({ openManageSubscription: () => mockManage() }));
jest.mock('@/lib/push', () => ({ pushState: () => mockPushState(), enablePush: jest.fn() }));
jest.mock('@/lib/api', () => ({
  ApiError: class ApiError extends Error {},
  api: {
    notificationSettings: async () => ({ availability: true, price: true, deadline: false }),
    updateNotificationSettings: (c: unknown) => mockUpdate(c),
  },
}));
jest.mock('@/lib/query', () => {
  const { QueryClient } = require('@tanstack/react-query');
  return {
    useEntitlement: () => ({ data: mockEntitlement() }),
    queryClient: new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } }),
  };
});

import { QueryClientProvider } from '@tanstack/react-query';
import DeleteAccount from '@/app/delete-account';
import Notifications from '@/app/notifications';
import { queryClient } from '@/lib/query';

const subscribed = { premium: true, status: 'ACTIVE', provider: 'APPLE', plan: 'MONTHLY' };

beforeEach(() => {
  [mockDeleteAccount, mockManage, mockEntitlement, mockPushState, mockUpdate].forEach((m) => m.mockReset());
  queryClient.clear();
});

afterEach(() => jest.restoreAllMocks());

describe('delete account', () => {
  test('warns that a store subscription keeps renewing', async () => {
    mockEntitlement.mockReturnValue(subscribed);
    await render(<DeleteAccount />);
    expect(screen.getByText('Your subscription will keep renewing')).toBeTruthy();
    expect(screen.getByText('Manage subscription')).toBeTruthy();
  });

  test('no subscription warning on a trial', async () => {
    mockEntitlement.mockReturnValue({ premium: true, status: 'TRIALING', provider: 'TRIAL' });
    await render(<DeleteAccount />);
    expect(screen.queryByText('Your subscription will keep renewing')).toBeNull();
  });

  test('deletes only after an explicit confirmation', async () => {
    const user = userEvent.setup();
    const alert = jest.spyOn(Alert, 'alert');
    mockEntitlement.mockReturnValue(undefined);
    mockDeleteAccount.mockResolvedValue(undefined);
    await render(<DeleteAccount />);
    await user.press(screen.getByText('Delete my account'));
    expect(mockDeleteAccount).not.toHaveBeenCalled();
    const buttons = alert.mock.calls[0][2]!;
    expect(buttons.find((b) => b.text === 'Cancel')).toBeTruthy();
    await act(async () => {
      await buttons.find((b) => b.text === 'Delete')!.onPress!();
    });
    expect(mockDeleteAccount).toHaveBeenCalledTimes(1);
  });

  test('a failure is shown and nothing else happens', async () => {
    const alert = jest.spyOn(Alert, 'alert');
    const user = userEvent.setup();
    mockEntitlement.mockReturnValue(undefined);
    mockDeleteAccount.mockRejectedValue(new Error('Could not delete your account right now.'));
    await render(<DeleteAccount />);
    await user.press(screen.getByText('Delete my account'));
    await act(async () => {
      await alert.mock.calls[0][2]!.find((b) => b.text === 'Delete')!.onPress!();
    });
    expect(screen.getByText('Could not delete your account right now.')).toBeTruthy();
  });
});

describe('notification settings', () => {
  async function show() {
    await render(
      <QueryClientProvider client={queryClient}>
        <Notifications />
      </QueryClientProvider>,
    );
    await screen.findByText('Deadline reminder');
  }

  test('switches reflect and update the server settings', async () => {
    mockPushState.mockResolvedValue('enabled');
    mockUpdate.mockResolvedValue({ availability: true, price: false, deadline: false });
    await show();
    expect(screen.getByLabelText('Deadline reminder').props.value).toBe(false);
    await act(async () => {
      await fireEvent(screen.getByLabelText('Price changes'), 'valueChange', false);
    });
    await waitFor(() => expect(mockUpdate).toHaveBeenCalledWith({ price: false }));
  });

  test('a server refusal puts the switch back', async () => {
    mockPushState.mockResolvedValue('enabled');
    mockUpdate.mockRejectedValue(new Error('Something went wrong'));
    await show();
    await act(async () => {
      await fireEvent(screen.getByLabelText('Price changes'), 'valueChange', false);
    });
    await waitFor(() => expect(screen.getByLabelText('Price changes').props.value).toBe(true));
    expect(screen.getByText('Something went wrong')).toBeTruthy();
  });

  test('blocked permission points to the phone settings', async () => {
    const user = userEvent.setup();
    const open = jest.spyOn(Linking, 'openSettings').mockResolvedValue();
    mockPushState.mockResolvedValue('blocked');
    await show();
    await user.press(await screen.findByText('Open settings'));
    expect(open).toHaveBeenCalled();
  });
});
