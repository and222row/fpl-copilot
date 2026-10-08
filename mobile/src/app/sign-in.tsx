import * as AppleAuthentication from 'expo-apple-authentication';
import { useEffect, useState } from 'react';
import { Platform, StyleSheet, View } from 'react-native';

import { Button } from '@/components/button';
import { errorMessage } from '@/components/error-view';
import { LegalLinks } from '@/components/legal-links';
import { Screen } from '@/components/screen';
import { ThemedText } from '@/components/themed-text';
import { Spacing } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { useAuth } from '@/lib/auth';

export default function SignIn() {
  const { signInWithApple, signInWithGoogle } = useAuth();
  const scheme = useColorScheme();
  const [appleAvailable, setAppleAvailable] = useState(false);
  const [busy, setBusy] = useState<'apple' | 'google' | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (Platform.OS === 'ios') AppleAuthentication.isAvailableAsync().then(setAppleAvailable);
  }, []);

  async function run(provider: 'apple' | 'google', fn: () => Promise<void>) {
    setBusy(provider);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <Screen footer={<LegalLinks />}>
      <View style={styles.hero}>
        <ThemedText type="subtitle" accessibilityRole="header">
          FPL Copilot
        </ThemedText>
        <ThemedText themeColor="textSecondary">
          Transfers, captaincy and lineups worked out by an optimiser, with the evidence behind
          every call.
        </ThemedText>
      </View>

      <View style={styles.buttons}>
        {appleAvailable ? (
          <AppleAuthentication.AppleAuthenticationButton
            buttonType={AppleAuthentication.AppleAuthenticationButtonType.CONTINUE}
            buttonStyle={
              scheme === 'dark'
                ? AppleAuthentication.AppleAuthenticationButtonStyle.WHITE
                : AppleAuthentication.AppleAuthenticationButtonStyle.BLACK
            }
            cornerRadius={12}
            style={styles.apple}
            onPress={() => run('apple', signInWithApple)}
          />
        ) : null}
        <Button
          title="Continue with Google"
          variant="secondary"
          loading={busy === 'google'}
          disabled={busy !== null}
          onPress={() => run('google', signInWithGoogle)}
        />
        {error ? (
          <ThemedText themeColor="danger" accessibilityRole="alert">
            {error}
          </ThemedText>
        ) : null}
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  hero: { gap: Spacing.two, marginTop: Spacing.six },
  buttons: { gap: Spacing.two, marginTop: Spacing.five },
  apple: { height: 50 },
});
