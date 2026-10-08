import { QueryClientProvider } from '@tanstack/react-query';
import { DarkTheme, DefaultTheme, Stack, ThemeProvider } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { useEffect } from 'react';
import { useColorScheme } from 'react-native';

import { ErrorView } from '@/components/error-view';
import { Screen } from '@/components/screen';
import { AuthProvider, useAuth } from '@/lib/auth';
import { decideGate } from '@/lib/gate';
import { queryClient, refreshAccount, useAccountQueries } from '@/lib/query';

SplashScreen.preventAutoHideAsync();

export default function RootLayout() {
  const scheme = useColorScheme();
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <ThemeProvider value={scheme === 'dark' ? DarkTheme : DefaultTheme}>
          <GatedStack />
        </ThemeProvider>
      </AuthProvider>
    </QueryClientProvider>
  );
}

function GatedStack() {
  const { session, loading } = useAuth();
  const signedIn = !!session;
  const { me, entitlement } = useAccountQueries(signedIn);
  const gate = decideGate({
    authLoading: loading,
    signedIn,
    me: me.data,
    entitlement: entitlement.data,
    failed: me.isError || entitlement.isError,
  });

  useEffect(() => {
    if (gate !== 'loading') SplashScreen.hideAsync();
  }, [gate]);

  // The splash screen stays up until we know where the user belongs.
  if (gate === 'loading') return null;

  if (gate === 'error') {
    return (
      <Screen title="Can't reach FPL Copilot">
        <ErrorView error={me.error ?? entitlement.error} onRetry={refreshAccount} />
      </Screen>
    );
  }

  return (
    <Stack screenOptions={{ headerShown: false }}>
      <Stack.Protected guard={gate === 'signed-out'}>
        <Stack.Screen name="sign-in" />
      </Stack.Protected>
      <Stack.Protected guard={gate === 'needs-team'}>
        <Stack.Screen name="onboarding" />
      </Stack.Protected>
      <Stack.Protected guard={gate === 'needs-premium'}>
        <Stack.Screen name="paywall" />
      </Stack.Protected>
      <Stack.Protected guard={gate === 'ready'}>
        <Stack.Screen name="(tabs)" />
        {/* Above the tabs, so Back returns to whichever tab opened them. */}
        <Stack.Screen name="player/[id]" options={{ headerShown: true, title: '', headerBackTitle: 'Back' }} />
        <Stack.Screen name="compare" options={{ headerShown: true, title: 'Compare', headerBackTitle: 'Back' }} />
      </Stack.Protected>
    </Stack>
  );
}
