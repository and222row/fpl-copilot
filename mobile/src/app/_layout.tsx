import { QueryClientProvider } from '@tanstack/react-query';
import { DarkTheme, DefaultTheme, router, Stack, ThemeProvider, type ErrorBoundaryProps } from 'expo-router';
import * as Notifications from 'expo-notifications';
import * as SplashScreen from 'expo-splash-screen';
import { useEffect } from 'react';
import { useColorScheme } from 'react-native';

import { ErrorView } from '@/components/error-view';
import { Screen } from '@/components/screen';
import { AuthProvider, useAuth } from '@/lib/auth';
import { decideGate } from '@/lib/gate';
import { initMonitoring, monitoringEnabled, reportError, wrapRoot } from '@/lib/monitoring';
import { refreshRegistration, targetFor } from '@/lib/push';
import { queryClient, refreshAccount, useAccountQueries } from '@/lib/query';

// First, so a crash during startup is reported too.
initMonitoring();
SplashScreen.preventAutoHideAsync();

export default monitoringEnabled() ? wrapRoot(RootLayout) : RootLayout;

// Catches a render error anywhere in the app. Without it a crash in one screen
// is a blank app; with it the user can retry, and the error is reported (an
// error caught here never reaches the global crash handler).
export function ErrorBoundary({ error, retry }: ErrorBoundaryProps) {
  useEffect(() => {
    reportError(error);
  }, [error]);
  // The crash may have come before the splash screen was hidden.
  useEffect(() => {
    SplashScreen.hideAsync();
  }, []);
  const message = monitoringEnabled()
    ? 'FPL Copilot hit an unexpected problem. It has been reported.'
    : 'FPL Copilot hit an unexpected problem.';
  return (
    <Screen title="Something went wrong" testID="crash-screen">
      <ErrorView error={new Error(message)} onRetry={() => void retry()} />
    </Screen>
  );
}

function RootLayout() {
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

  usePushWhenReady(gate === 'ready');

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
        <Stack.Screen name="planner" options={{ headerShown: true, title: 'Planner', headerBackTitle: 'Back' }} />
        <Stack.Screen name="news" options={{ headerShown: true, title: 'News', headerBackTitle: 'Back' }} />
        <Stack.Screen
          name="notifications"
          options={{ headerShown: true, title: 'Notifications', headerBackTitle: 'Back' }}
        />
        <Stack.Screen
          name="delete-account"
          options={{ headerShown: true, title: 'Delete account', headerBackTitle: 'Back' }}
        />
      </Stack.Protected>
    </Stack>
  );
}

// Only once the user is fully in: before that there is no account to register
// the device to and no screen a notification could open.
function usePushWhenReady(ready: boolean) {
  const response = Notifications.useLastNotificationResponse();

  useEffect(() => {
    if (ready) refreshRegistration().catch(() => undefined);
  }, [ready]);

  useEffect(() => {
    if (!ready || !response || response.actionIdentifier !== Notifications.DEFAULT_ACTION_IDENTIFIER) return;
    const target = targetFor(response.notification.request.content.data);
    if (target) router.push(target);
  }, [ready, response]);
}
