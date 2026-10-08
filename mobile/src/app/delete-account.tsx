import { useState } from 'react';
import { Alert, Platform } from 'react-native';

import { Button } from '@/components/button';
import { errorMessage } from '@/components/error-view';
import { Card, Screen } from '@/components/screen';
import { ThemedText } from '@/components/themed-text';
import { useAuth } from '@/lib/auth';
import { openManageSubscription } from '@/lib/billing';
import { useEntitlement } from '@/lib/query';
import { managedInStore } from '@/lib/subscription';

const STORE = Platform.OS === 'ios' ? 'App Store' : 'Google Play';

export default function DeleteAccount() {
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
    <Screen testID="delete-account-screen" belowHeader footer={<Button title="Delete my account" variant="destructive" loading={busy} onPress={confirm} />}>
      {subscribed ? (
        <Card>
          <ThemedText type="smallBold" themeColor="warning">
            Your subscription will keep renewing
          </ThemedText>
          <ThemedText type="small">
            Deleting your account does not cancel your {STORE} subscription. Cancel it first, or you will keep being
            charged.
          </ThemedText>
          <Button
            title="Manage subscription"
            variant="secondary"
            onPress={() => openManageSubscription().catch((e) => setError(errorMessage(e)))}
          />
        </Card>
      ) : null}

      <Card>
        <ThemedText type="smallBold">What gets deleted</ThemedText>
        <ThemedText type="small">
          • Your sign-in account{'\n'}• Your connected FPL team and any transfers you recorded{'\n'}• Your alerts,
          recommendation history and notification settings{'\n'}• Your subscription record with us
        </ThemedText>
        <ThemedText type="small" themeColor="textSecondary">
          Your FPL team itself is untouched — it belongs to the official Fantasy Premier League. Purchase records are
          kept without personal details where the law requires it, and your team cannot receive a second free trial.
        </ThemedText>
      </Card>

      {error ? (
        <ThemedText themeColor="danger" accessibilityRole="alert">
          {error}
        </ThemedText>
      ) : null}
    </Screen>
  );
}
