import * as Clipboard from 'expo-clipboard';
import { router, useLocalSearchParams } from 'expo-router';
import { openBrowserAsync } from 'expo-web-browser';
import { useState } from 'react';
import { StyleSheet, View } from 'react-native';

import { Button } from '@/components/button';
import { errorMessage } from '@/components/error-view';
import { Card, Screen } from '@/components/screen';
import { ThemedText } from '@/components/themed-text';
import { Spacing } from '@/constants/theme';
import { ApiError, api, type VerifiedConnection } from '@/lib/api';
import { refreshAccount } from '@/lib/query';

const FPL_SITE = 'https://fantasy.premierleague.com/';

function formatDate(iso: string | null): string {
  return iso ? new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'long' }) : '';
}

export default function Verify() {
  const { teamId, code, teamName } = useLocalSearchParams<{
    teamId: string;
    code: string;
    teamName: string;
  }>();
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expired, setExpired] = useState(false);
  const [done, setDone] = useState<VerifiedConnection | null>(null);

  async function verify() {
    setBusy(true);
    setError(null);
    try {
      setDone(await api.verifyConnection(Number(teamId)));
    } catch (e) {
      // 404: the code expired. 429: attempts used up. Either way a new code
      // has to be requested from the previous screen.
      setExpired(e instanceof ApiError && (e.status === 404 || e.status === 429));
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function copy() {
    await Clipboard.setStringAsync(code);
    setCopied(true);
  }

  if (done) {
    return (
      <Screen title="You're connected" footer={<Button title="Continue" onPress={refreshAccount} />}>
        <Card>
          <ThemedText type="smallBold">{done.team_name}</ThemedText>
          <ThemedText themeColor="textSecondary">{done.manager_name}</ThemedText>
        </Card>
        <ThemedText>
          {done.trial_started
            ? `Your 30-day free trial has started. It runs until ${formatDate(done.entitlement.trial_ends_at)}.`
            : 'This team or account has already used its free trial.'}
        </ThemedText>
        <ThemedText themeColor="textSecondary">
          You can change your FPL team name back now.
        </ThemedText>
      </Screen>
    );
  }

  return (
    <Screen
      title="Prove it's your team"
      footer={
        expired ? (
          <Button title="Get a new code" onPress={() => router.back()} />
        ) : (
          <Button title="Verify" onPress={verify} loading={busy} />
        )
      }>
      <ThemedText themeColor="textSecondary">
        Anyone can type a Team ID, so we ask you to put this code in your team name for a moment.
        Only the owner can do that.
      </ThemedText>

      <Card>
        <ThemedText type="small" themeColor="textSecondary">
          {teamName}
        </ThemedText>
        <View style={styles.codeRow}>
          <ThemedText type="subtitle" selectable accessibilityLabel={`Code ${code.split('').join(' ')}`}>
            {code}
          </ThemedText>
          <Button title={copied ? 'Copied' : 'Copy'} variant="secondary" onPress={copy} />
        </View>
      </Card>

      <ThemedText>
        1. Open FPL and go to Team Details.{'\n'}
        2. Add {code} anywhere in your team name (replace part of it if you hit the 20-character
        limit) and save.{'\n'}
        3. Come back and tap Verify. Changes can take a minute to show.
      </ThemedText>
      <Button title="Open FPL" variant="secondary" onPress={() => openBrowserAsync(FPL_SITE)} />

      {error ? (
        <ThemedText themeColor="danger" accessibilityRole="alert">
          {error}
        </ThemedText>
      ) : null}
    </Screen>
  );
}

const styles = StyleSheet.create({
  codeRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: Spacing.three,
  },
});
