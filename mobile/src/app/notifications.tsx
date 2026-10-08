import { useMutation, useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Linking, StyleSheet, Switch, View } from 'react-native';

import { Button } from '@/components/button';
import { errorMessage, ErrorView } from '@/components/error-view';
import { Card, Screen } from '@/components/screen';
import { ThemedText } from '@/components/themed-text';
import { Spacing } from '@/constants/theme';
import { api, type NotificationSettings } from '@/lib/api';
import { enablePush, pushState, type PushState } from '@/lib/push';
import { queryClient } from '@/lib/query';

const KINDS: { key: keyof NotificationSettings; title: string; detail: string }[] = [
  { key: 'availability', title: 'Injuries and availability', detail: 'A player in your squad is injured, doubtful, suspended or back.' },
  { key: 'price', title: 'Price changes', detail: 'A player you own changed price or is about to.' },
  { key: 'deadline', title: 'Deadline reminder', detail: 'Two hours before each gameweek deadline.' },
];

const SETTINGS_KEY = ['notification-settings'];

export default function Notifications() {
  const state = useQuery({ queryKey: ['push-state'], queryFn: pushState });
  const settings = useQuery({ queryKey: SETTINGS_KEY, queryFn: api.notificationSettings });
  const [enabling, setEnabling] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const update = useMutation({
    mutationFn: api.updateNotificationSettings,
    // Flip the switch immediately; put it back if the server refuses.
    onMutate: async (changes) => {
      const previous = queryClient.getQueryData<NotificationSettings>(SETTINGS_KEY);
      if (previous) queryClient.setQueryData(SETTINGS_KEY, { ...previous, ...changes });
      return { previous };
    },
    onError: (e, _changes, context) => {
      if (context?.previous) queryClient.setQueryData(SETTINGS_KEY, context.previous);
      setError(errorMessage(e));
    },
    onSuccess: (saved) => queryClient.setQueryData(SETTINGS_KEY, saved),
  });

  async function onEnable() {
    setEnabling(true);
    setError(null);
    try {
      queryClient.setQueryData<PushState>(['push-state'], await enablePush());
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setEnabling(false);
    }
  }

  return (
    <Screen belowHeader>
      <PermissionCard state={state.data} enabling={enabling} onEnable={onEnable} />
      {error ? (
        <ThemedText themeColor="danger" accessibilityRole="alert">
          {error}
        </ThemedText>
      ) : null}
      {settings.isError ? <ErrorView error={settings.error} onRetry={() => settings.refetch()} /> : null}
      {settings.data ? (
        <Card>
          {KINDS.map((k) => (
            <View key={k.key} style={styles.row}>
              <View style={styles.grow}>
                <ThemedText type="smallBold">{k.title}</ThemedText>
                <ThemedText type="small" themeColor="textSecondary">
                  {k.detail}
                </ThemedText>
              </View>
              <Switch
                accessibilityLabel={k.title}
                value={settings.data[k.key]}
                onValueChange={(value) => {
                  setError(null);
                  update.mutate({ [k.key]: value });
                }}
              />
            </View>
          ))}
        </Card>
      ) : null}
    </Screen>
  );
}

function PermissionCard({
  state,
  enabling,
  onEnable,
}: {
  state: PushState | undefined;
  enabling: boolean;
  onEnable: () => void;
}) {
  if (state === 'enabled') {
    return (
      <ThemedText type="small" themeColor="textSecondary">
        Notifications are on for this device.
      </ThemedText>
    );
  }
  if (state === 'unavailable') {
    return (
      <ThemedText type="small" themeColor="warning">
        Push notifications are not available on this device.
      </ThemedText>
    );
  }
  if (state === 'blocked') {
    return (
      <Card>
        <ThemedText type="small">Notifications are turned off for FPL Copilot in your phone&apos;s settings.</ThemedText>
        <Button title="Open settings" variant="secondary" onPress={() => Linking.openSettings()} />
      </Card>
    );
  }
  return (
    <Card>
      <ThemedText type="small">Get told when something changes for your squad, without opening the app.</ThemedText>
      <Button title="Turn on notifications" onPress={onEnable} loading={enabling} disabled={state === undefined} />
    </Card>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', gap: Spacing.three, paddingVertical: Spacing.two },
  grow: { flex: 1 },
});
