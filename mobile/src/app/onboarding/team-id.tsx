import { router } from 'expo-router';
import { useState } from 'react';
import { Pressable, StyleSheet, TextInput } from 'react-native';

import { Button } from '@/components/button';
import { errorMessage } from '@/components/error-view';
import { Card, Screen } from '@/components/screen';
import { ThemedText } from '@/components/themed-text';
import { Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import { api } from '@/lib/api';
import { refreshAccount } from '@/lib/query';

export default function TeamId() {
  const theme = useTheme();
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
      title="Your FPL Team ID"
      footer={<Button title="Continue" onPress={submit} loading={busy} disabled={!teamId} />}>
      <TextInput
        value={value}
        onChangeText={(t) => setValue(t.replace(/\D/g, ''))}
        onSubmitEditing={submit}
        placeholder="e.g. 1234567"
        placeholderTextColor={theme.textSecondary}
        keyboardType="number-pad"
        returnKeyType="go"
        maxLength={9}
        autoFocus
        accessibilityLabel="FPL Team ID"
        style={[styles.input, { color: theme.text, backgroundColor: theme.backgroundElement }]}
      />
      {error ? (
        <ThemedText themeColor="danger" accessibilityRole="alert">
          {error}
        </ThemedText>
      ) : null}

      <Pressable accessibilityRole="button" onPress={() => setShowHelp((s) => !s)}>
        <ThemedText type="linkPrimary">Where do I find my Team ID?</ThemedText>
      </Pressable>
      {showHelp ? (
        <Card>
          <ThemedText>
            1. Sign in at fantasy.premierleague.com in a web browser.{'\n'}
            2. Open the Points tab.{'\n'}
            3. Look at the address bar: the number after /entry/ is your Team ID.
          </ThemedText>
          <ThemedText type="code">fantasy.premierleague.com/entry/1234567/event/7</ThemedText>
        </Card>
      ) : null}
    </Screen>
  );
}

const styles = StyleSheet.create({
  input: {
    fontSize: 24,
    fontWeight: '600',
    borderRadius: 12,
    paddingHorizontal: Spacing.three,
    paddingVertical: Spacing.three,
    letterSpacing: 2,
  },
});
