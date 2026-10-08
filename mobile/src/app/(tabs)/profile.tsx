import Constants from 'expo-constants';
import { useState } from 'react';
import { Alert } from 'react-native';

import { Button } from '@/components/button';
import { errorMessage } from '@/components/error-view';
import { LegalLinks } from '@/components/legal-links';
import { Card, Screen } from '@/components/screen';
import { ThemedText } from '@/components/themed-text';
import { api, type Entitlement } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { refreshAccount, useEntitlement, useMe } from '@/lib/query';

function describe(e: Entitlement | undefined): string {
  if (!e) return '…';
  const date = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString() : '');
  switch (e.status) {
    case 'TRIALING':
      return `Free trial until ${date(e.trial_ends_at)}`;
    case 'ACTIVE':
      return `${e.plan === 'ANNUAL' ? 'Annual' : 'Monthly'} plan · renews ${date(e.subscription_ends_at)}`;
    case 'EXPIRED':
      return 'Trial ended';
    default:
      return e.status;
  }
}

export default function Profile() {
  const { signOut } = useAuth();
  const me = useMe(true);
  const entitlement = useEntitlement(true);
  const [busy, setBusy] = useState(false);
  const account = me.data?.fpl_accounts[0];

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
    <Screen title="Profile" footer={<LegalLinks />}>
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
        <ThemedText>{describe(entitlement.data)}</ThemedText>
      </Card>

      <Button title="Sign out" variant="secondary" onPress={signOut} />
      {account ? (
        <Button title="Disconnect team" variant="destructive" loading={busy} onPress={confirmDisconnect} />
      ) : null}

      <ThemedText type="small" themeColor="textSecondary" style={{ textAlign: 'center' }}>
        Version {Constants.expoConfig?.version}
      </ThemedText>
    </Screen>
  );
}
