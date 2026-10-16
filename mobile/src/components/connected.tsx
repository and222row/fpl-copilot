import { useState } from 'react';

import { Button } from '@/components/button';
import { errorMessage } from '@/components/error-view';
import { Card, Pill, Screen } from '@/components/screen';
import { ThemedText } from '@/components/themed-text';
import { useTheme } from '@/hooks/use-theme';
import type { ConnectResult } from '@/lib/api';
import { proveTeam } from '@/lib/prove';
import { refreshAccount } from '@/lib/query';

function formatDate(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'long' }) : '';
}

/**
 * The end of onboarding: the team, and where the free trial stands.
 *
 * Connecting by ID needs no proof, but the trial does — it is once per team,
 * so granting it on an ID alone would let anyone spend a stranger's. A team
 * that is not yet proven is offered the short proof step here, while the user
 * is still in the flow, rather than discovering it at the paywall.
 */
export function Connected({ result, proven = false }: { result: ConnectResult; proven?: boolean }) {
  const theme = useTheme();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function startTrial() {
    setBusy(true);
    setError(null);
    try {
      await proveTeam(result.fpl_entry_id);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  const offerTrial = !result.trial_started && result.trial_available === true;

  return (
    <Screen
      belowHeader
      testID="connected-screen"
      title="You're connected"
      footer={
        <Button
          title={offerTrial ? 'Not now' : 'Continue'}
          variant={offerTrial ? 'secondary' : undefined}
          onPress={refreshAccount}
        />
      }>
      <Card variant="hero">
        <Pill label={proven ? 'Verified' : 'Connected'} color="onBrand" soft="brand" />
        <ThemedText type="subtitle" style={{ color: theme.onHero }}>
          {result.team_name}
        </ThemedText>
        <ThemedText style={{ color: theme.onHeroMuted }}>{result.manager_name}</ThemedText>
      </Card>

      {result.trial_started ? (
        <Card>
          <ThemedText type="headline">
            {`Your 30-day free trial has started. It runs until ${formatDate(result.entitlement?.trial_ends_at)}.`}
          </ThemedText>
          {proven ? (
            <ThemedText type="small" themeColor="textSecondary">
              You can change your FPL team name back now.
            </ThemedText>
          ) : null}
        </Card>
      ) : offerTrial ? (
        <Card testID="trial-offer">
          <ThemedText type="headline">One more step starts your 30-day free trial</ThemedText>
          <ThemedText type="small" themeColor="textSecondary">
            Prove the team is yours by adding a short code to its name on the FPL website for a moment. Only the
            owner can do that, which is what stops anyone using up someone else&apos;s trial.
          </ThemedText>
          <Button title="Start my free trial" onPress={startTrial} loading={busy} testID="start-trial" />
          {error ? (
            <ThemedText themeColor="danger" accessibilityRole="alert">
              {error}
            </ThemedText>
          ) : null}
        </Card>
      ) : (
        <Card>
          <ThemedText type="headline">This team or account has already used its free trial.</ThemedText>
        </Card>
      )}
    </Screen>
  );
}
