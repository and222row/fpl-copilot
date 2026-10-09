import { useState } from 'react';
import { StyleSheet, View } from 'react-native';

import { Button } from '@/components/button';
import { TextField } from '@/components/text-field';
import { ThemedText } from '@/components/themed-text';
import { Spacing } from '@/constants/theme';
import { supabase } from '@/lib/supabase';

// Included only in e2e builds (see sign-in.tsx). It talks to the staging
// Supabase project, the only one with the email provider enabled; production
// has it off, so even a mistakenly shipped form could not sign anyone in.
export function E2ESignIn() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setBusy(true);
    setError(null);
    const { error: e } = await supabase.auth.signInWithPassword({ email, password });
    if (e) setError(e.message);
    setBusy(false);
  }

  return (
    <View style={styles.box}>
      <ThemedText type="small" themeColor="warning">
        Test build sign-in
      </ThemedText>
      <TextField
        testID="e2e-email"
        value={email}
        onChangeText={setEmail}
        autoCapitalize="none"
        keyboardType="email-address"
        placeholder="Email"
      />
      <TextField
        testID="e2e-password"
        value={password}
        onChangeText={setPassword}
        secureTextEntry
        placeholder="Password"
      />
      <Button testID="e2e-sign-in" title="Sign in (test)" variant="secondary" loading={busy} onPress={submit} />
      {error ? (
        <ThemedText testID="e2e-sign-in-error" themeColor="danger">
          {error}
        </ThemedText>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  box: { gap: Spacing.two, marginTop: Spacing.four },
});
