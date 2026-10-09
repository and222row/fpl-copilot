import { router } from 'expo-router';
import { useState } from 'react';
import { StyleSheet } from 'react-native';

import { Button } from '@/components/button';
import { errorMessage } from '@/components/error-view';
import { Card, Screen } from '@/components/screen';
import { Steps } from '@/components/steps';
import { TextField } from '@/components/text-field';
import { ThemedText } from '@/components/themed-text';
import { api } from '@/lib/api';
import { refreshAccount } from '@/lib/query';

export default function TeamId() {
  const [value, setValue] = useState('');
  const [showHelp, setShowHelp] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const teamId = /^\d{1,9}$/.test(value) ? Number(value) : null;

  async function submit() {
    if (!teamId) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.startConnection(teamId);
      if (result.status === 'connected') {
        await refreshAccount();
        return;
      }
      router.push({
        pathname: '/onboarding/verify',
        params: {
          teamId: String(result.fpl_entry_id),
          code: result.code,
          teamName: result.team_name,
        },
      });
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Screen
      belowHeader
      testID="team-id-screen"
      title="Your FPL Team ID"
      subtitle="The number FPL gives your team. We use it to read your squad."
      footer={<Button title="Continue" onPress={submit} loading={busy} disabled={!teamId} />}>
      <TextField
        large
        testID="team-id-input"
        value={value}
        onChangeText={(t) => setValue(t.replace(/\D/g, ''))}
        onSubmitEditing={submit}
        placeholder="1234567"
        keyboardType="number-pad"
        returnKeyType="go"
        maxLength={9}
        autoFocus
        accessibilityLabel="FPL Team ID"
      />
      {error ? (
        <ThemedText testID="team-id-error" themeColor="danger" accessibilityRole="alert">
          {error}
        </ThemedText>
      ) : null}

      <ThemedText type="smallBold" themeColor="accent" accessibilityRole="button" onPress={() => setShowHelp((s) => !s)} style={styles.help}>
        Where do I find my Team ID?
      </ThemedText>
      {showHelp ? (
        <Card>
          <Steps
            items={[
              { body: 'Sign in at fantasy.premierleague.com in a web browser.' },
              { body: 'Open the Points tab.' },
              { body: 'Look at the address bar: the number after /entry/ is your Team ID.' },
            ]}
          />
          <Card variant="inset">
            <ThemedText type="code">fantasy.premierleague.com/entry/1234567/event/7</ThemedText>
          </Card>
        </Card>
      ) : null}
    </Screen>
  );
}

const styles = StyleSheet.create({
  help: { textAlign: 'center' },
});
