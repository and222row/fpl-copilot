import * as AppleAuthentication from 'expo-apple-authentication';
import { useEffect, useState, type ComponentType } from 'react';
import { Platform, StyleSheet, View } from 'react-native';

import { Button } from '@/components/button';
import { errorMessage } from '@/components/error-view';
import { LegalLinks } from '@/components/legal-links';
import { Card, Screen } from '@/components/screen';
import { ThemedText } from '@/components/themed-text';
import { Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
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
  const theme = useTheme();
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
      <Card variant="hero" style={styles.hero}>
        <ThemedText type="eyebrow" style={{ color: theme.brand }}>
          Fantasy Premier League
        </ThemedText>
        <ThemedText type="title" accessibilityRole="header" style={{ color: theme.onHero }}>
          FPL Copilot
        </ThemedText>
        <ThemedText style={{ color: theme.onHeroMuted }}>
          Transfers, captaincy and lineups worked out by an optimiser, with the evidence behind
          every call.
        </ThemedText>
        <View style={styles.points}>
          {['Your best XI and captain, every gameweek', 'Transfers that pay off, hits included', 'Alerts before prices and players move'].map(
            (line) => (
              <View key={line} style={styles.point}>
                <View style={[styles.dot, { backgroundColor: theme.brand }]} />
                <ThemedText type="small" style={{ color: theme.onHero }}>
                  {line}
                </ThemedText>
              </View>
            ),
          )}
        </View>
      </Card>

      <View style={styles.buttons}>
        {appleAvailable ? (
          <AppleAuthentication.AppleAuthenticationButton
            buttonType={AppleAuthentication.AppleAuthenticationButtonType.CONTINUE}
            buttonStyle={
              scheme === 'dark'
                ? AppleAuthentication.AppleAuthenticationButtonStyle.WHITE
                : AppleAuthentication.AppleAuthenticationButtonStyle.BLACK
            }
            cornerRadius={14}
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
  hero: { gap: Spacing.two, marginTop: Spacing.five, paddingVertical: Spacing.five },
  points: { gap: 10, marginTop: Spacing.three },
  point: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  dot: { width: 8, height: 8, borderRadius: 4 },
  buttons: { gap: Spacing.two, marginTop: Spacing.four },
  apple: { height: 52 },
});
