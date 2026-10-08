import * as AppleAuthentication from 'expo-apple-authentication';
import { useEffect, useState, type ComponentType } from 'react';
import { Platform, StyleSheet, View } from 'react-native';

import { Button } from '@/components/button';
import { errorMessage } from '@/components/error-view';
import { LegalLinks } from '@/components/legal-links';
import { Screen } from '@/components/screen';
import { ThemedText } from '@/components/themed-text';
import { Spacing } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { useAuth } from '@/lib/auth';

// Email/password sign-in for Maestro, which cannot drive Google's or Apple's
// system sheets. Only the `e2e` EAS profile sets EXPO_PUBLIC_E2E (CI fails if
// another does). The literal comparison lets the bundler drop the require, so
// other builds do not contain the form at all — verified by grepping bundles.
const E2ESignIn: ComponentType | null =
  // eslint-disable-next-line @typescript-eslint/no-require-imports -- a static import would always bundle it
  process.env.EXPO_PUBLIC_E2E === 'true' ? require('@/components/e2e-sign-in').E2ESignIn : null;

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
    <Screen testID="sign-in-screen" footer={<LegalLinks />}>
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
      {E2ESignIn ? <E2ESignIn /> : null}
    </Screen>
  );
}

const styles = StyleSheet.create({
  hero: { gap: Spacing.two, marginTop: Spacing.six },
  buttons: { gap: Spacing.two, marginTop: Spacing.five },
  apple: { height: 50 },
});
