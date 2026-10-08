import Constants from 'expo-constants';
import { router } from 'expo-router';
import { useState } from 'react';
import { Alert } from 'react-native';

import { Button } from '@/components/button';
import { errorMessage } from '@/components/error-view';
import { LegalLinks } from '@/components/legal-links';
import { Card, Screen } from '@/components/screen';
import { ThemedText } from '@/components/themed-text';
import { api } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { billingAvailable, openManageSubscription, restore } from '@/lib/billing';
import { refreshAccount, useEntitlement, useMe } from '@/lib/query';
import { describeEntitlement, managedInStore } from '@/lib/subscription';

export default function Profile() {
  const { session, signOut } = useAuth();
  const me = useMe(true);
  const entitlement = useEntitlement(true);
  const [busy, setBusy] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const account = me.data?.fpl_accounts[0];

  async function onRestore() {
    if (!session) return;
    setRestoring(true);
    try {
      await restore(session.user.id);
      await api.syncBilling();
      await refreshAccount();
    } catch (e) {
      Alert.alert('Could not restore', errorMessage(e));
    } finally {
      setRestoring(false);
    }
  }

  function confirmDisconnect() {
    if (!account) return;
    Alert.alert(
      'Disconnect team?',
      `${account.team_name} will be removed from your account, along with any transfers you recorded. You can reconnect it later.`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Disconnect',
          style: 'destructive',
          onPress: async () => {
            setBusy(true);
            try {
              await api.disconnect(account.fpl_entry_id);
              await refreshAccount();
            } catch (e) {
              Alert.alert('Could not disconnect', errorMessage(e));
            } finally {
              setBusy(false);
            }
          },
        },
      ],
    );
  }

  return (
    <Screen testID="profile-screen" title="Profile">
      <Card>
        <ThemedText type="small" themeColor="textSecondary">
          Signed in with {me.data?.providers.join(' & ') || '…'}
        </ThemedText>
        <ThemedText>{me.data?.email ?? me.data?.phone ?? ''}</ThemedText>
      </Card>

      {account ? (
        <Card>
          <ThemedText type="small" themeColor="textSecondary">
            FPL team
          </ThemedText>
          <ThemedText type="smallBold">{account.team_name}</ThemedText>
          <ThemedText type="small" themeColor="textSecondary">
            {account.manager_name} · ID {account.fpl_entry_id}
          </ThemedText>
        </Card>
      ) : null}

      <Card>
        <ThemedText type="small" themeColor="textSecondary">
          Subscription
        </ThemedText>
        <ThemedText testID="profile-subscription">{entitlement.data ? describeEntitlement(entitlement.data) : '…'}</ThemedText>
        {entitlement.data?.status === 'PAST_DUE' ? (
          <ThemedText type="small" themeColor="warning">
            The store could not take your last payment. Update your payment method there to keep access.
          </ThemedText>
        ) : null}
        {entitlement.data && managedInStore(entitlement.data) ? (
          <Button
            title="Manage subscription"
            variant="secondary"
            onPress={() => openManageSubscription().catch((e) => Alert.alert('Could not open', errorMessage(e)))}
          />
        ) : null}
        {billingAvailable() ? (
          <Button title="Restore purchases" variant="secondary" loading={restoring} onPress={onRestore} />
        ) : null}
      </Card>

      <Button title="Notifications" variant="secondary" onPress={() => router.push('/notifications')} />
      <Button title="Sign out" variant="secondary" onPress={signOut} />
      {account ? (
        <Button title="Disconnect team" variant="destructive" loading={busy} onPress={confirmDisconnect} />
      ) : null}
      <Button title="Delete account" variant="destructive" onPress={() => router.push('/delete-account')} />

      <ThemedText type="small" themeColor="textSecondary" style={{ textAlign: 'center' }}>
        Version {Constants.expoConfig?.version}
      </ThemedText>
      <LegalLinks />
    </Screen>
  );
}
