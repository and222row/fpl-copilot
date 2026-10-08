import { useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import { Button } from '@/components/button';
import { LegalLinks } from '@/components/legal-links';
import { Card, Screen } from '@/components/screen';
import { ThemedText } from '@/components/themed-text';
import { Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import { useAuth } from '@/lib/auth';
import { refreshAccount, useEntitlement } from '@/lib/query';

// Display only. Once store purchases are wired, prices come localised from the
// App Store / Play Store and these constants go away.
const PLANS = [
  { id: 'ANNUAL', label: 'Annual', price: '€29.99 / year', note: 'Save 37% vs monthly' },
  { id: 'MONTHLY', label: 'Monthly', price: '€3.99 / month', note: '€47.88 a year' },
] as const;

function headline(status: string | undefined): string {
  if (status === 'EXPIRED') return 'Your free trial has ended.';
  if (status === 'NONE') return 'This team has already used its free trial.';
  if (status === 'CANCELED' || status === 'PAST_DUE') return 'Your subscription is not active.';
  return 'Subscribe to keep using FPL Copilot.';
}

export default function Paywall() {
  const theme = useTheme();
  const { signOut } = useAuth();
  const entitlement = useEntitlement(true);
  const [plan, setPlan] = useState<(typeof PLANS)[number]['id']>('ANNUAL');

  return (
    <Screen
      title="FPL Copilot Pro"
      onRefresh={refreshAccount}
      refreshing={entitlement.isFetching}
      footer={
        <>
          {/* Purchases arrive with the approved store-billing integration. */}
          <Button title="Subscribe" disabled />
          <Button title="Restore purchases" variant="secondary" disabled />
          <LegalLinks />
        </>
      }>
      <ThemedText>{headline(entitlement.data?.status)}</ThemedText>
      <ThemedText themeColor="textSecondary">
        Continue using your FPL assistant: optimal transfers, captaincy, lineups and planning.
      </ThemedText>

      <View style={styles.plans} accessibilityRole="radiogroup">
        {PLANS.map((p) => {
          const selected = plan === p.id;
          return (
            <Pressable
              key={p.id}
              accessibilityRole="radio"
              accessibilityState={{ selected }}
              onPress={() => setPlan(p.id)}
              style={[styles.plan, { borderColor: selected ? theme.accent : 'transparent' }]}>
              <Card>
                <ThemedText type="smallBold">{p.label}</ThemedText>
                <ThemedText type="subtitle">{p.price}</ThemedText>
                <ThemedText type="small" themeColor={p.id === 'ANNUAL' ? 'highlight' : 'textSecondary'}>
                  {p.note}
                </ThemedText>
              </Card>
            </Pressable>
          );
        })}
      </View>

      <ThemedText type="small" themeColor="textSecondary">
        In-app purchase is coming in the next update. Pull down to refresh if you subscribed on
        another device.
      </ThemedText>
      <Button title="Sign out" variant="secondary" onPress={signOut} />
    </Screen>
  );
}

const styles = StyleSheet.create({
  plans: { gap: Spacing.two },
  plan: { borderWidth: 2, borderRadius: 18 },
});
