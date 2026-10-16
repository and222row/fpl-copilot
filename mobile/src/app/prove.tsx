import * as Clipboard from 'expo-clipboard';
import { router, useLocalSearchParams } from 'expo-router';
import { openBrowserAsync } from 'expo-web-browser';
import { useState } from 'react';
import { StyleSheet, View } from 'react-native';

import { Button } from '@/components/button';
import { Connected } from '@/components/connected';
import { errorMessage, ErrorView } from '@/components/error-view';
import { Card, Screen } from '@/components/screen';
import { Steps } from '@/components/steps';
import { ThemedText } from '@/components/themed-text';
import { Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import { ApiError, api, type VerifiedConnection } from '@/lib/api';

// The Pick Team page, where Admin -> Team Details renames the team. Opened in
// an in-app browser so a phone with the FPL app installed is not handed to
// the app, which cannot rename teams.
const PICK_TEAM = 'https://fantasy.premierleague.com/my-team';

export default function Prove() {
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

  if (done) return <Connected result={done} proven />;

  return (
    <Screen
      belowHeader
      testID="verify-screen"
      title="Prove it's your team"
      subtitle="Put this code in your team name for a moment. Only the team's owner can, so it proves the team is yours."
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
