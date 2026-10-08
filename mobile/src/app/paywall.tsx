import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Platform, Pressable, StyleSheet, View } from 'react-native';
import type { PurchasesPackage } from 'react-native-purchases';

import { Button } from '@/components/button';
import { errorMessage } from '@/components/error-view';
import { LegalLinks } from '@/components/legal-links';
import { Card, Screen } from '@/components/screen';
import { ThemedText } from '@/components/themed-text';
import { Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import { api } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { billingAvailable, loadPlans, purchase, restore } from '@/lib/billing';
import { refreshAccount, useEntitlement } from '@/lib/query';

const STORE = Platform.OS === 'ios' ? 'Apple ID' : 'Google Play account';
const SETTINGS = Platform.OS === 'ios' ? 'your App Store account settings' : 'the Google Play Store';

function headline(status: string | undefined): string {
  if (status === 'EXPIRED') return 'Your free trial or subscription has ended.';
  if (status === 'NONE') return 'This team has already used its free trial.';
  return 'Subscribe to keep using FPL Copilot.';
}

export default function Paywall() {
  const theme = useTheme();
  const { session, signOut } = useAuth();
  const userId = session?.user.id;
  const entitlement = useEntitlement(true);
  const available = billingAvailable();
  const plans = useQuery({ queryKey: ['plans'], queryFn: loadPlans, enabled: available, staleTime: 3_600_000 });
  const [selected, setSelected] = useState<'annual' | 'monthly'>('annual');
  const [busy, setBusy] = useState<'buy' | 'restore' | null>(null);
  const [message, setMessage] = useState<{ text: string; error: boolean } | null>(null);

  // If annual is not on sale in this store, fall back to what is.
  const choice = selected === 'annual' && !plans.data?.annual && plans.data?.monthly ? 'monthly' : selected;
  const pkg: PurchasesPackage | null = plans.data?.[choice] ?? null;

  async function confirmWithServer(): Promise<boolean> {
    const result = await api.syncBilling();
    await refreshAccount();
    return result.premium;
  }

  async function onSubscribe() {
    if (!pkg || !userId) return;
    setBusy('buy');
    setMessage(null);
    try {
      const outcome = await purchase(pkg, userId);
      if (outcome === 'pending') {
        setMessage({ text: 'Your purchase is waiting for approval. Access starts as soon as the store confirms it.', error: false });
      } else if (outcome === 'purchased' && !(await confirmWithServer())) {
        setMessage({ text: 'Payment received. Confirming with the store — pull down to refresh in a moment.', error: false });
      }
    } catch (e) {
      setMessage({ text: errorMessage(e), error: true });
    } finally {
      setBusy(null);
    }
  }

  async function onRestore() {
    if (!userId) return;
    setBusy('restore');
    setMessage(null);
    try {
      await restore(userId);
      if (!(await confirmWithServer())) {
        setMessage({ text: `No active subscription was found for this ${STORE}.`, error: false });
      }
    } catch (e) {
      setMessage({ text: errorMessage(e), error: true });
    } finally {
      setBusy(null);
    }
  }

  return (
    <Screen
      testID="paywall-screen"
      title="FPL Copilot Pro"
      onRefresh={refreshAccount}
      refreshing={entitlement.isFetching}
      footer={
        <>
          <Button
            title="Subscribe"
            onPress={onSubscribe}
            loading={busy === 'buy'}
            disabled={!pkg || busy !== null}
          />
          <Button
            title="Restore purchases"
            variant="secondary"
            onPress={onRestore}
            loading={busy === 'restore'}
            disabled={!available || busy !== null}
          />
          <LegalLinks />
        </>
      }>
      <ThemedText>{headline(entitlement.data?.status)}</ThemedText>
      <ThemedText themeColor="textSecondary">
        Continue using your FPL assistant: optimal transfers, captaincy, lineups and planning.
      </ThemedText>

      {!available ? (
        <ThemedText themeColor="warning">Subscriptions are not available on this device.</ThemedText>
      ) : plans.isPending ? (
        <ThemedText themeColor="textSecondary">Loading prices…</ThemedText>
      ) : plans.isError || (!plans.data?.annual && !plans.data?.monthly) ? (
        <ThemedText themeColor="warning">
          Prices could not be loaded from the store. Check your connection and pull down to retry.
        </ThemedText>
      ) : (
        <View style={styles.plans} accessibilityRole="radiogroup">
          {(['annual', 'monthly'] as const).map((key) => {
            const option = plans.data[key];
            if (!option) return null;
            const isSelected = choice === key;
            return (
              <Pressable
                key={key}
                accessibilityRole="radio"
                accessibilityState={{ selected: isSelected }}
                onPress={() => setSelected(key)}
                style={[styles.plan, { borderColor: isSelected ? theme.accent : 'transparent' }]}>
                <Card>
                  <ThemedText type="smallBold">{key === 'annual' ? 'Annual' : 'Monthly'}</ThemedText>
                  <ThemedText type="subtitle">
                    {option.product.priceString} / {key === 'annual' ? 'year' : 'month'}
                  </ThemedText>
                  {key === 'annual' && plans.data.annualSavingPercent ? (
                    <ThemedText type="small" themeColor="highlight">
                      Save {plans.data.annualSavingPercent}% vs monthly
                    </ThemedText>
                  ) : null}
                </Card>
              </Pressable>
            );
          })}
        </View>
      )}

      {message ? (
        <ThemedText testID="paywall-message" themeColor={message.error ? 'danger' : 'text'} accessibilityRole="alert">
          {message.text}
        </ThemedText>
      ) : null}

      {/* Auto-renewal disclosure required by both stores. */}
      <ThemedText type="small" themeColor="textSecondary">
        {pkg
          ? `${pkg.product.priceString} per ${choice === 'annual' ? 'year' : 'month'}, charged to your ${STORE} when you confirm. `
          : ''}
        The subscription renews automatically unless cancelled at least 24 hours before the end of the current
        period. Manage or cancel it any time in {SETTINGS}.
      </ThemedText>
      <Button title="Sign out" variant="secondary" onPress={signOut} />
    </Screen>
  );
}

const styles = StyleSheet.create({
  plans: { gap: Spacing.two },
  plan: { borderWidth: 2, borderRadius: 18 },
});
