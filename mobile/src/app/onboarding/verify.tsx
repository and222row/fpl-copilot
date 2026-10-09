import * as Clipboard from 'expo-clipboard';
import { router, useLocalSearchParams } from 'expo-router';
import { openBrowserAsync } from 'expo-web-browser';
import { useState } from 'react';
import { StyleSheet, View } from 'react-native';

import { Button } from '@/components/button';
import { errorMessage, ErrorView } from '@/components/error-view';
import { Card, Pill, Screen } from '@/components/screen';
import { Steps } from '@/components/steps';
import { ThemedText } from '@/components/themed-text';
import { Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import { ApiError, api, type VerifiedConnection } from '@/lib/api';
import { refreshAccount } from '@/lib/query';

// The Pick Team page, where Admin -> Team Details renames the team. Opened in
// an in-app browser so a phone with the FPL app installed is not handed to
// the app, which cannot rename teams.
const PICK_TEAM = 'https://fantasy.premierleague.com/my-team';

function formatDate(iso: string | null): string {
  return iso ? new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'long' }) : '';
}

export default function Verify() {
  const theme = useTheme();
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
      <Screen belowHeader title="You're connected" footer={<Button title="Continue" onPress={refreshAccount} />}>
        <Card variant="hero">
          <Pill label="Verified" color="onBrand" soft="brand" />
          <ThemedText type="subtitle" style={{ color: theme.onHero }}>
            {done.team_name}
          </ThemedText>
          <ThemedText style={{ color: theme.onHeroMuted }}>{done.manager_name}</ThemedText>
        </Card>
        <Card>
          <ThemedText type="headline">
            {done.trial_started
              ? `Your 30-day free trial has started. It runs until ${formatDate(done.entitlement.trial_ends_at)}.`
              : 'This team or account has already used its free trial.'}
          </ThemedText>
          <ThemedText type="small" themeColor="textSecondary">
            You can change your FPL team name back now.
          </ThemedText>
        </Card>
      </Screen>
    );
  }

  return (
    <Screen
      belowHeader
      testID="verify-screen"
      title="Prove it's your team"
      subtitle="Anyone can type a Team ID, so we ask you to put this code in your team name for a moment. Only the owner can do that."
      footer={
        expired ? (
          <Button title="Get a new code" onPress={() => router.back()} />
        ) : (
          <Button title="Verify" onPress={verify} loading={busy} />
        )
      }>
      <Card variant="hero" style={styles.codeCard}>
        <ThemedText type="eyebrow" style={{ color: theme.onHeroMuted }}>
          {teamName}
        </ThemedText>
        <ThemedText
          testID="verify-code"
          selectable
          accessibilityLabel={`Code ${code.split('').join(' ')}`}
          style={[styles.code, { color: theme.brand }]}>
          {code}
        </ThemedText>
        <Button title={copied ? 'Copied' : 'Copy'} variant="brand" compact onPress={copy} style={styles.copy} />
      </Card>

      <Card>
        <Steps
          items={[
            { body: 'Tap Open FPL below and sign in. It has to be the website: the FPL app cannot rename a team.' },
            { body: 'On Pick Team, scroll to Admin and tap Team Details.' },
            {
              body: `Add ${code} anywhere in your team name (replace part of it if you hit the 20-character limit) and tap Update details.`,
            },
            { body: 'Come back and tap Verify. Changes can take a minute to show.' },
          ]}
        />
        <View style={styles.open}>
          <Button title="Open FPL" variant="secondary" onPress={() => openBrowserAsync(PICK_TEAM)} />
        </View>
      </Card>

      {error ? <ErrorView error={new Error(error)} /> : null}
    </Screen>
  );
}

const styles = StyleSheet.create({
  codeCard: { alignItems: 'center', paddingVertical: Spacing.four },
  code: { fontSize: 40, lineHeight: 48, fontWeight: '900', letterSpacing: 8, fontVariant: ['tabular-nums'] },
  copy: { alignSelf: 'center' },
  open: { marginTop: Spacing.one },
});
