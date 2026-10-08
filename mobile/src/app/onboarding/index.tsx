import { router, Stack } from 'expo-router';

import { Button } from '@/components/button';
import { Card, Screen } from '@/components/screen';
import { ThemedText } from '@/components/themed-text';

const STEPS = [
  ['Connect your FPL team', 'Enter your Team ID and prove it is yours with a short code.'],
  ['We read your squad', 'Players, bank and free transfers come straight from FPL.'],
  ['30 days free', 'Your trial starts the moment your team is connected.'],
] as const;

export default function Welcome() {
  return (
    <Screen
      title="Welcome"
      footer={<Button title="Connect my team" onPress={() => router.push('/onboarding/team-id')} />}>
      <Stack.Screen options={{ headerShown: false }} />
      {STEPS.map(([title, body]) => (
        <Card key={title}>
          <ThemedText type="smallBold">{title}</ThemedText>
          <ThemedText themeColor="textSecondary">{body}</ThemedText>
        </Card>
      ))}
    </Screen>
  );
}
