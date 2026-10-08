import { useQuery } from '@tanstack/react-query';
import { router } from 'expo-router';
import { useState } from 'react';
import { Platform, Pressable, StyleSheet, View } from 'react-native';
import type { PurchasesPackage } from 'react-native-purchases';

import { Button } from '@/components/button';
import { errorMessage } from '@/components/error-view';
import { LegalLinks } from '@/components/legal-links';
import { Card, Pill, Screen } from '@/components/screen';
import { ThemedText } from '@/components/themed-text';
import { Radius, Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import { api } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { billingAvailable, loadPlans, purchase, restore } from '@/lib/billing';
import { refreshAccount, useEntitlement } from '@/lib/query';

const STORE = Platform.OS === 'ios' ? 'Apple ID' : 'Google Play account';
const SETTINGS = Platform.OS === 'ios' ? 'your App Store account settings' : 'the Google Play Store';

const FEATURES = [
  'Best transfers over 1, 3 or 5 gameweeks, with the reasons',
  'Captain picks in safe, balanced and differential modes',
  'Your optimal starting XI and bench order',
  'A gameweek-by-gameweek transfer planner',
  'Alerts for injuries, price changes and the deadline',
];

function headline(status: string | undefined): string {
  if (status === 'TRIALING') return 'Keep every feature after your free trial.';
  if (status === 'EXPIRED') return 'Your free trial or subscription has ended.';
  if (status === 'NONE') return 'This team has already used its free trial.';
  return 'Subscribe to keep using FPL Copilot.';
}

export default function Paywall() {
  const theme = useTheme();
  const { session, signOut } = useAuth();
  const userId = session?.user.id;
  const entitlement = useEntitlement(true);
  // Opened from "Upgrade" while the trial runs, rather than required.
  const optional = entitlement.data?.premium === true;
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

  function close() {
    if (router.canGoBack?.()) router.back();
  }

  async function onSubscribe() {
    if (!pkg || !userId) return;
    setBusy('buy');
    setMessage(null);
    try {
      const outcome = await purchase(pkg, userId);
      if (outcome === 'pending') {
        setMessage({ text: 'Your purchase is waiting for approval. Access starts as soon as the store confirms it.', error: false });
      } else if (outcome === 'purchased') {
        if (await confirmWithServer()) {
          if (optional) close();
        } else {
          setMessage({ text: 'Payment received. Confirming with the store — pull down to refresh in a moment.', error: false });
        }
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
      onRefresh={refreshAccount}
      refreshing={entitlement.isFetching}
      footer={
        <>
          <Button
            title="Subscribe"
            variant="brand"
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
      {optional ? (
        <View style={styles.closeRow}>
          <ThemedText type="smallBold" themeColor="textSecondary" accessibilityRole="button" onPress={close}>
            Not now
          </ThemedText>
        </View>
      ) : null}

      <Card variant="hero" style={styles.hero}>
        <Pill label="PRO" color="onBrand" soft="brand" />
        <ThemedText type="title" accessibilityRole="header" style={{ color: theme.onHero }}>
          FPL Copilot Pro
        </ThemedText>
        <ThemedText style={{ color: theme.onHeroMuted }}>{headline(entitlement.data?.status)}</ThemedText>
        <View style={styles.features}>
          {FEATURES.map((f) => (
            <View key={f} style={styles.feature}>
              <View style={[styles.check, { backgroundColor: theme.brand }]}>
                <ThemedText style={[styles.checkMark, { color: theme.onBrand }]}>✓</ThemedText>
              </View>
              <ThemedText type="small" style={[styles.grow, { color: theme.onHero }]}>
                {f}
              </ThemedText>
            </View>
          ))}
        </View>
      </Card>

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
                style={[
                  styles.plan,
                  {
                    backgroundColor: theme.backgroundElement,
                    borderColor: isSelected ? theme.accent : theme.hairline,
                    borderWidth: isSelected ? 2 : 1,
                  },
                ]}>
                <View style={[styles.radio, { borderColor: isSelected ? theme.accent : theme.hairline }]}>
                  {isSelected ? <View style={[styles.radioDot, { backgroundColor: theme.accent }]} /> : null}
                </View>
                <View style={styles.grow}>
                  <ThemedText type="headline">{key === 'annual' ? 'Annual' : 'Monthly'}</ThemedText>
                  <ThemedText type="small" themeColor="textSecondary">
                    {option.product.priceString} / {key === 'annual' ? 'year' : 'month'}
                  </ThemedText>
                </View>
                {key === 'annual' && plans.data.annualSavingPercent ? (
                  <Pill label={`Save ${plans.data.annualSavingPercent}% vs monthly`} color="highlight" soft="highlightSoft" />
                ) : null}
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

      {optional && entitlement.data?.status === 'TRIALING' ? (
        <ThemedText type="small" themeColor="textSecondary">
          Subscribing now starts your paid plan straight away, in place of the rest of the free trial.
        </ThemedText>
      ) : null}

      {/* Auto-renewal disclosure required by both stores. */}
      <ThemedText type="caption" themeColor="textSecondary">
        {pkg
          ? `${pkg.product.priceString} per ${choice === 'annual' ? 'year' : 'month'}, charged to your ${STORE} when you confirm. `
          : ''}
        The subscription renews automatically unless cancelled at least 24 hours before the end of the current
        period. Manage or cancel it any time in {SETTINGS}.
      </ThemedText>
      {optional ? null : <Button title="Sign out" variant="secondary" onPress={signOut} />}
    </Screen>
  );
}

const styles = StyleSheet.create({
  closeRow: { alignItems: 'flex-end' },
  hero: { gap: Spacing.two, paddingVertical: Spacing.four },
  features: { gap: 10, marginTop: Spacing.two },
  feature: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  check: { width: 20, height: 20, borderRadius: 10, alignItems: 'center', justifyContent: 'center' },
  checkMark: { fontSize: 12, lineHeight: 14, fontWeight: '900' },
  plans: { gap: Spacing.two },
  plan: { flexDirection: 'row', alignItems: 'center', gap: 12, borderRadius: Radius.lg, padding: Spacing.three },
  radio: { width: 22, height: 22, borderRadius: 11, borderWidth: 2, alignItems: 'center', justifyContent: 'center' },
  radioDot: { width: 10, height: 10, borderRadius: 5 },
  grow: { flex: 1 },
});
