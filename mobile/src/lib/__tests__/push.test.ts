jest.mock('expo-notifications', () => ({
  setNotificationHandler: jest.fn(),
  getPermissionsAsync: jest.fn(),
  requestPermissionsAsync: jest.fn(),
  getExpoPushTokenAsync: jest.fn(),
  setNotificationChannelAsync: jest.fn(),
  AndroidImportance: { HIGH: 4 },
}));
jest.mock('expo-device', () => ({ get isDevice() { return mockEnv.isDevice; } }));
jest.mock('expo-constants', () => ({
  __esModule: true,
  default: { get expoConfig() { return { extra: { eas: { projectId: mockEnv.projectId } } }; }, easConfig: null },
}));
jest.mock('@/lib/api', () => ({ api: { registerDevice: jest.fn(), unregisterDevice: jest.fn() } }));

const mockEnv = { isDevice: true, projectId: 'proj-1' as string | undefined };

import { api } from '@/lib/api';
import { enablePush, pushState, refreshRegistration, targetFor, unregisterPush } from '@/lib/push';

const N: Record<string, jest.Mock> = jest.requireMock('expo-notifications');
const TOKEN = 'ExponentPushToken[abcdefghijklmnop]';

function permission(granted: boolean, canAskAgain = true) {
  N.getPermissionsAsync.mockResolvedValue({ granted, canAskAgain });
}

beforeEach(() => {
  Object.values(N).forEach((m) => typeof m === 'function' && 'mockReset' in m && m.mockReset());
  (api.registerDevice as jest.Mock).mockReset();
  (api.unregisterDevice as jest.Mock).mockReset();
  mockEnv.isDevice = true;
  mockEnv.projectId = 'proj-1';
  N.getExpoPushTokenAsync.mockResolvedValue({ data: TOKEN });
});

test('state reflects the device and permission', async () => {
  permission(true);
  expect(await pushState()).toBe('enabled');
  permission(false, true);
  expect(await pushState()).toBe('off');
  permission(false, false);
  expect(await pushState()).toBe('blocked');
  mockEnv.isDevice = false;
  expect(await pushState()).toBe('unavailable');
  mockEnv.isDevice = true;
  mockEnv.projectId = undefined;
  expect(await pushState()).toBe('unavailable');
});

test('enabling asks once and registers the token', async () => {
  permission(false, true);
  N.requestPermissionsAsync.mockResolvedValue({ granted: true, canAskAgain: true });
  expect(await enablePush()).toBe('enabled');
  expect(N.requestPermissionsAsync).toHaveBeenCalledTimes(1);
  expect(N.getExpoPushTokenAsync).toHaveBeenCalledWith({ projectId: 'proj-1' });
  expect(api.registerDevice).toHaveBeenCalledWith(TOKEN, expect.stringMatching(/^(ios|android)$/));
});

test('a refusal registers nothing', async () => {
  permission(false, true);
  N.requestPermissionsAsync.mockResolvedValue({ granted: false, canAskAgain: false });
  expect(await enablePush()).toBe('blocked');
  expect(api.registerDevice).not.toHaveBeenCalled();
});

test('when blocked, enabling does not re-prompt', async () => {
  permission(false, false);
  expect(await enablePush()).toBe('blocked');
  expect(N.requestPermissionsAsync).not.toHaveBeenCalled();
});

test('launch refresh never prompts', async () => {
  permission(false, true);
  await refreshRegistration();
  expect(N.requestPermissionsAsync).not.toHaveBeenCalled();
  expect(api.registerDevice).not.toHaveBeenCalled();
  permission(true);
  await refreshRegistration();
  expect(api.registerDevice).toHaveBeenCalledWith(TOKEN, expect.any(String));
});

test('sign-out unregisters this install only when push is on', async () => {
  permission(false, true);
  await unregisterPush();
  expect(api.unregisterDevice).not.toHaveBeenCalled();
  permission(true);
  await unregisterPush();
  expect(api.unregisterDevice).toHaveBeenCalledWith(TOKEN);
});

test('tapping a notification opens the right screen', () => {
  expect(targetFor({ type: 'alert', player_id: 7 })).toEqual({ pathname: '/player/[id]', params: { id: '7' } });
  expect(targetFor({ type: 'alert', player_id: null })).toBe('/news');
  expect(targetFor({ type: 'deadline' })).toBe('/transfers');
  expect(targetFor({ type: 'something-new' })).toBeNull();
  expect(targetFor(undefined)).toBeNull();
});
