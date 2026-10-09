import { router, Stack } from 'expo-router';

import { Button } from '@/components/button';
import { Card, Screen } from '@/components/screen';
import { Steps } from '@/components/steps';
import { ThemedText } from '@/components/themed-text';
import { useTheme } from '@/hooks/use-theme';

const STEPS = [
  { title: 'Connect your FPL team', body: 'Enter your Team ID and prove it is yours with a short code.' },
  { title: 'We read your squad', body: 'Players, bank and free transfers come straight from FPL.' },
  { title: '30 days free', body: 'Your trial starts the moment your team is connected.' },
];

export default function Welcome() {
  const theme = useTheme();
  return (
    <Screen
      testID="onboarding-welcome"
      footer={<Button title="Connect my team" onPress={() => router.push('/onboarding/team-id')} />}>
      <Stack.Screen options={{ headerShown: false }} />
      <Card variant="hero">
        <ThemedText type="eyebrow" style={{ color: theme.brand }}>
          Getting started
        </ThemedText>
        <ThemedText type="title" accessibilityRole="header" style={{ color: theme.onHero }}>
          Welcome
        </ThemedText>
        <ThemedText style={{ color: theme.onHeroMuted }}>
          Two minutes to set up, then advice for every gameweek.
        </ThemedText>
      </Card>
      <Card>
        <Steps items={STEPS} />
      </Card>
    </Screen>
  );
}
