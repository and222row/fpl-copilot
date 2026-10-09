import { useState } from 'react';
import { Alert, Platform, StyleSheet, View } from 'react-native';

import { Button } from '@/components/button';
import { errorMessage, ErrorView } from '@/components/error-view';
import { Card, Screen, SectionHeader } from '@/components/screen';
import { ThemedText } from '@/components/themed-text';
import { Radius } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import { useAuth } from '@/lib/auth';
import { openManageSubscription } from '@/lib/billing';
import { useEntitlement } from '@/lib/query';
import { managedInStore } from '@/lib/subscription';

const STORE = Platform.OS === 'ios' ? 'App Store' : 'Google Play';

const DELETED = [
  'Your sign-in account',
  'Your connected FPL team and any transfers you recorded',
  'Your alerts, recommendation history and notification settings',
  'Your subscription record with us',
];

export default function DeleteAccount() {
  const theme = useTheme();
  const { deleteAccount } = useAuth();
  const entitlement = useEntitlement(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const subscribed = entitlement.data ? managedInStore(entitlement.data) : false;

  function confirm() {
    Alert.alert(
      'Delete your account?',
      'This cannot be undone. Your account and everything listed here will be permanently deleted.',
      [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Delete', style: 'destructive', onPress: run },
      ],
    );
  }

  async function run() {
    setBusy(true);
    setError(null);
    try {
      // On success the session ends and the app returns to sign-in.
      await deleteAccount();
    } catch (e) {
      setError(errorMessage(e));
      setBusy(false);
    }
  }

  return (
    <Screen
      testID="delete-account-screen"
      belowHeader
      footer={<Button title="Delete my account" variant="destructive" loading={busy} onPress={confirm} />}>
      {subscribed ? (
        <View style={[styles.warning, { backgroundColor: theme.warningSoft }]}>
          <ThemedText type="headline" themeColor="warning">
            Your subscription will keep renewing
          </ThemedText>
          <ThemedText type="small">
            Deleting your account does not cancel your {STORE} subscription. Cancel it first, or you will keep being
            charged.
          </ThemedText>
          <Button
            title="Manage subscription"
            variant="secondary"
            compact
            onPress={() => openManageSubscription().catch((e) => setError(errorMessage(e)))}
          />
        </View>
      ) : null}

      <SectionHeader title="What gets deleted" />
      <Card>
        {DELETED.map((item) => (
          <View key={item} style={styles.item}>
            <View style={[styles.cross, { backgroundColor: theme.dangerSoft }]}>
              <ThemedText type="caption" themeColor="danger" style={styles.crossText}>
                ✕
              </ThemedText>
            </View>
            <ThemedText type="small" style={styles.grow}>
              {item}
            </ThemedText>
          </View>
        ))}
      </Card>
      <ThemedText type="caption" themeColor="textSecondary">
        Your FPL team itself is untouched — it belongs to the official Fantasy Premier League. Purchase records are
        kept without personal details where the law requires it, and your team cannot receive a second free trial.
      </ThemedText>

      {error ? <ErrorView error={new Error(error)} /> : null}
    </Screen>
  );
}

const styles = StyleSheet.create({
  warning: { borderRadius: Radius.lg, padding: 18, gap: 10 },
  item: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  cross: { width: 24, height: 24, borderRadius: 12, alignItems: 'center', justifyContent: 'center' },
  crossText: { fontWeight: '900' },
  grow: { flex: 1 },
});
