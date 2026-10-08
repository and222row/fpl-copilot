import Constants from 'expo-constants';
import { router } from 'expo-router';
import { useState } from 'react';
import { Alert, StyleSheet, View } from 'react-native';

import { Button } from '@/components/button';
import { errorMessage } from '@/components/error-view';
import { LegalLinks } from '@/components/legal-links';
import { Card, ListGroup, ListRow, Screen, SectionHeader } from '@/components/screen';
import { ThemedText } from '@/components/themed-text';
import { Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import { api } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { billingAvailable, openManageSubscription, restore } from '@/lib/billing';
import { refreshAccount, useEntitlement, useMe } from '@/lib/query';
import { describeEntitlement, managedInStore } from '@/lib/subscription';

const PROVIDER_NAMES: Record<string, string> = { apple: 'Apple', google: 'Google', email: 'email' };

export default function Profile() {
  const theme = useTheme();
  const { session, signOut } = useAuth();
  const me = useMe(true);
  const entitlement = useEntitlement(true);
  const [busy, setBusy] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const account = me.data?.fpl_accounts[0];
  const ent = entitlement.data;
  const email = me.data?.email ?? me.data?.phone ?? '';
  const providers = (me.data?.providers ?? []).map((p) => PROVIDER_NAMES[p] ?? p).join(' & ');

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
        <View style={styles.identity}>
          <View style={[styles.avatar, { backgroundColor: theme.accent }]}>
            <ThemedText type="headline" style={{ color: theme.onAccent }}>
              {(email[0] ?? '?').toUpperCase()}
            </ThemedText>
          </View>
          <View style={styles.grow}>
            <ThemedText type="headline" numberOfLines={1}>
              {email}
            </ThemedText>
            <ThemedText type="small" themeColor="textSecondary">
              Signed in with {providers || '…'}
            </ThemedText>
          </View>
        </View>
      </Card>

      {account ? (
        <>
          <SectionHeader title="FPL team" />
          <ListGroup>
            <ListRow title={account.team_name} subtitle={`${account.manager_name} · ID ${account.fpl_entry_id}`} last />
          </ListGroup>
        </>
      ) : null}

      <SectionHeader title="Subscription" />
      <Card>
        <ThemedText testID="profile-subscription" type="headline">
          {ent ? describeEntitlement(ent) : '…'}
        </ThemedText>
        {ent?.status === 'PAST_DUE' ? (
          <ThemedText type="small" themeColor="warning">
            The store could not take your last payment. Update your payment method there to keep access.
          </ThemedText>
        ) : null}
        {ent?.status === 'TRIALING' ? (
          <Button title="Upgrade to Pro" variant="brand" onPress={() => router.push('/paywall')} />
        ) : null}
      </Card>
      {(ent && managedInStore(ent)) || billingAvailable() ? (
        <ListGroup>
          {ent && managedInStore(ent) ? (
            <ListRow
              title="Manage subscription"
              onPress={() => openManageSubscription().catch((e) => Alert.alert('Could not open', errorMessage(e)))}
              last={!billingAvailable()}
            />
          ) : null}
          {billingAvailable() ? (
            <ListRow title="Restore purchases" value={restoring ? 'Restoring…' : undefined} onPress={onRestore} last />
          ) : null}
        </ListGroup>
      ) : null}

      <SectionHeader title="Settings" />
      <ListGroup>
        <ListRow title="Notifications" onPress={() => router.push('/notifications')} last />
      </ListGroup>

      <SectionHeader title="Account" />
      <ListGroup>
        <ListRow title="Sign out" onPress={signOut} />
        {account ? (
          <ListRow title="Disconnect team" value={busy ? 'Disconnecting…' : undefined} destructive onPress={confirmDisconnect} />
        ) : null}
        <ListRow title="Delete account" destructive onPress={() => router.push('/delete-account')} last />
      </ListGroup>

      <View style={styles.footer}>
        <LegalLinks />
        <ThemedText type="caption" themeColor="textSecondary" style={styles.center}>
          Version {Constants.expoConfig?.version}
        </ThemedText>
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  identity: { flexDirection: 'row', alignItems: 'center', gap: 14 },
  avatar: { width: 48, height: 48, borderRadius: 24, alignItems: 'center', justifyContent: 'center' },
  footer: { gap: Spacing.one, marginTop: Spacing.two },
  center: { textAlign: 'center' },
  grow: { flex: 1 },
});
