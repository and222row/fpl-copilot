import Constants from 'expo-constants';
import * as Device from 'expo-device';
import * as Notifications from 'expo-notifications';
import { Platform } from 'react-native';

import { api } from '@/lib/api';

// Must match the channelId the server sends with every push.
const CHANNEL_ID = 'alerts';

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: false,
    shouldSetBadge: false,
  }),
});

export type PushState = 'enabled' | 'off' | 'blocked' | 'unavailable';

function projectId(): string | undefined {
  return Constants.expoConfig?.extra?.eas?.projectId ?? Constants.easConfig?.projectId;
}

export async function pushState(): Promise<PushState> {
  if (!Device.isDevice || !projectId()) return 'unavailable';
  const perm = await Notifications.getPermissionsAsync();
  if (perm.granted) return 'enabled';
  return perm.canAskAgain ? 'off' : 'blocked';
}

// Android 13+ needs the channel to exist before it will show the permission
// prompt or deliver to it. Creating it again is a no-op.
async function ensureChannel(): Promise<void> {
  if (Platform.OS !== 'android') return;
  await Notifications.setNotificationChannelAsync(CHANNEL_ID, {
    name: 'Squad alerts',
    importance: Notifications.AndroidImportance.HIGH,
  });
}

async function registerToken(): Promise<void> {
  await ensureChannel();
  const { data: token } = await Notifications.getExpoPushTokenAsync({ projectId: projectId() });
  await api.registerDevice(token, Platform.OS === 'ios' ? 'ios' : 'android');
}

/** Ask for permission (in context, from a button) and register this install. */
export async function enablePush(): Promise<PushState> {
  const state = await pushState();
  if (state === 'unavailable' || state === 'blocked') return state;
  if (state === 'off') {
    await ensureChannel();
    const perm = await Notifications.requestPermissionsAsync();
    if (!perm.granted) return perm.canAskAgain ? 'off' : 'blocked';
  }
  await registerToken();
  return 'enabled';
}

/** On launch: push tokens can change, so re-register when already permitted. Never prompts. */
export async function refreshRegistration(): Promise<void> {
  if ((await pushState()) === 'enabled') await registerToken();
}

/** On sign-out, so the next person to use this phone does not get these alerts. */
export async function unregisterPush(): Promise<void> {
  if ((await pushState()) !== 'enabled') return;
  const { data: token } = await Notifications.getExpoPushTokenAsync({ projectId: projectId() });
  await api.unregisterDevice(token);
}

export type PushTarget = { pathname: '/player/[id]'; params: { id: string } } | '/news' | '/transfers' | null;

/** Where tapping a notification should go, from the data the server attached. */
export function targetFor(data: Record<string, unknown> | undefined): PushTarget {
  if (!data) return null;
  if (data.type === 'alert' && typeof data.player_id === 'number') {
    return { pathname: '/player/[id]', params: { id: String(data.player_id) } };
  }
  if (data.type === 'alert') return '/news';
  if (data.type === 'deadline') return '/transfers';
  return null;
}
