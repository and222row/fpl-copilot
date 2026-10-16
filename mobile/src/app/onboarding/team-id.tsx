import { useState } from 'react';
import { StyleSheet } from 'react-native';

import { Button } from '@/components/button';
import { Connected } from '@/components/connected';
import { errorMessage } from '@/components/error-view';
import { Card, Screen } from '@/components/screen';
import { Steps } from '@/components/steps';
import { TextField } from '@/components/text-field';
import { ThemedText } from '@/components/themed-text';
import { ApiError, api, TEAM_TAKEN, type ConnectResult } from '@/lib/api';
import { proveTeam } from '@/lib/prove';
import { refreshAccount } from '@/lib/query';

export default function TeamId() {
  const [value, setValue] = useState('');
  const [showHelp, setShowHelp] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // The team ID another account already holds, offered for takeover.
  const [taken, setTaken] = useState<number | null>(null);
  const [done, setDone] = useState<ConnectResult | null>(null);

  const teamId = /^\d{1,9}$/.test(value) ? Number(value) : null;

  async function submit() {
    if (!teamId) return;
    setBusy(true);
    setError(null);
    setTaken(null);
    try {
      const result = await api.connectTeam(teamId);
      // trial_started is absent when the team was already ours: nothing new to show.
      if (result.trial_started === undefined) await refreshAccount();
      else setDone(result);
    } catch (e) {
      if (e instanceof ApiError && e.code === TEAM_TAKEN) setTaken(teamId);
      else setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function takeOver() {
    if (!taken) return;
    setBusy(true);
    setError(null);
    try {
      await proveTeam(taken);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  if (done) return <Connected result={done} />;

  return (
    <Screen
      belowHeader
      testID="team-id-screen"
      title="Your FPL Team ID"
      subtitle="The number FPL gives your team. We use it to read your squad."
      footer={
        taken === teamId && teamId ? (
          <Button title="It's my team: take it over" onPress={takeOver} loading={busy} testID="take-over" />
        ) : (
          <Button title="Connect" onPress={submit} loading={busy} disabled={!teamId} />
        )
      }>
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

      {taken === teamId && teamId ? (
        <Card testID="team-taken">
          <ThemedText type="headline" accessibilityRole="alert">
            This team is already connected to another account
          </ThemedText>
          <ThemedText type="small" themeColor="textSecondary">
            Each team can be connected to one FPL Copilot account. If you signed up before with another email, sign in
            with that one. If the team is yours, take it over: you add a short code to your team name on the FPL
            website for a moment, which only the owner can do.
          </ThemedText>
        </Card>
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
