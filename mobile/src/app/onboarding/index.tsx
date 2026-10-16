import { router, Stack } from 'expo-router';
import { openBrowserAsync } from 'expo-web-browser';
import { StyleSheet, View } from 'react-native';

import { Button } from '@/components/button';
import { Carousel } from '@/components/carousel';
import { Card, Screen } from '@/components/screen';
import { Steps } from '@/components/steps';
import { ThemedText } from '@/components/themed-text';
import { Radius, Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';

const FPL_SITE = 'https://fantasy.premierleague.com/';

/**
 * How connecting works, before the user starts: where the Team ID is, and the
 * short code in the team name on the FPL website (the FPL app cannot rename a
 * team) that proves a team is yours. That proof starts the free trial — it is
 * once per team, so an ID alone cannot claim it — and takes a team back if
 * another account connected it first.
 */
export default function Welcome() {
  const theme = useTheme();
  return (
    <Screen
      testID="onboarding-welcome"
      footer={<Button title="Connect my team" onPress={() => router.push('/onboarding/team-id')} />}>
      <Stack.Screen options={{ headerShown: false }} />
      <Carousel
        testID="onboarding-carousel"
        pages={[
          <Card key="welcome" variant="hero" style={styles.slide}>
            <ThemedText type="eyebrow" style={{ color: theme.brand }}>
              Getting started · 1 of 3
            </ThemedText>
            <ThemedText type="title" accessibilityRole="header" style={{ color: theme.onHero }}>
              Welcome
            </ThemedText>
            <ThemedText style={{ color: theme.onHeroMuted }}>
              Connect your FPL team in under a minute. Swipe for how it works, or tap Connect my team.
            </ThemedText>
            <Steps
              items={[
                { title: 'Find your Team ID', body: 'A number on the FPL website.' },
                { title: 'Enter it', body: 'Your team connects straight away.' },
                { title: '30 days free', body: 'It starts once a quick code proves the team is yours.' },
              ]}
            />
          </Card>,

          <Card key="team-id" style={styles.slide}>
            <ThemedText type="eyebrow" themeColor="textSecondary">
              Find your team · 2 of 3
            </ThemedText>
            <ThemedText type="subtitle">Find your Team ID</ThemedText>
            <Steps
              items={[
                { body: 'Open fantasy.premierleague.com in a web browser and sign in.' },
                { body: 'Tap Points.' },
                { body: 'The number after /entry/ in the address bar is your Team ID.' },
              ]}
            />
            <AddressBar />
            <Button title="Open the FPL website" variant="secondary" compact onPress={() => openBrowserAsync(FPL_SITE)} />
          </Card>,

          <Card key="taken" style={styles.slide}>
            <ThemedText type="eyebrow" themeColor="textSecondary">
              If your team is taken · 3 of 3
            </ThemedText>
            <ThemedText type="subtitle">A quick code proves it&apos;s yours</ThemedText>
            <ThemedText type="small" themeColor="textSecondary">
              Add a short code to your team name for a moment. Only the owner can, so it starts your free trial, and
              takes the team back if someone else connected it first. Do it on the FPL website: the FPL app cannot
              rename a team.
            </ThemedText>
            <Steps
              items={[
                { body: 'On fantasy.premierleague.com, open Pick Team.' },
                { body: 'Scroll to Admin and tap Team Details.' },
                { body: 'Add the code anywhere in your team name, tap Update details, then come back and tap Verify.' },
              ]}
            />
            <TeamNameField />
          </Card>,
        ]}
      />
    </Screen>
  );
}

/** A browser address bar with the Team ID picked out. */
function AddressBar() {
  const theme = useTheme();
  return (
    <View style={[styles.mock, { backgroundColor: theme.backgroundSelected }]} accessibilityLabel="Example address: fantasy.premierleague.com/entry/1234567/event/6">
      <ThemedText type="caption" themeColor="textSecondary" numberOfLines={1}>
        fantasy.premierleague.com/entry/
        <ThemedText type="caption" style={[styles.highlight, { backgroundColor: theme.brand, color: theme.onBrand }]}>
          {' 1234567 '}
        </ThemedText>
        /event/6
      </ThemedText>
    </View>
  );
}

/** A team name field with the code added to it. */
function TeamNameField() {
  const theme = useTheme();
  return (
    <View style={[styles.mock, { backgroundColor: theme.backgroundSelected }]} accessibilityLabel="Example team name: Andrew's Team K7QM2X">
      <ThemedText type="caption" themeColor="textSecondary">
        Team name
      </ThemedText>
      <ThemedText type="smallBold">
        Andrew&apos;s Team{' '}
        <ThemedText type="smallBold" style={[styles.highlight, { backgroundColor: theme.brand, color: theme.onBrand }]}>
          {' K7QM2X '}
        </ThemedText>
      </ThemedText>
    </View>
  );
}

const styles = StyleSheet.create({
  slide: { minHeight: 440, gap: 12 },
  mock: { borderRadius: Radius.md, paddingHorizontal: 12, paddingVertical: 10, gap: 2, marginTop: Spacing.one },
  highlight: { fontWeight: '800', borderRadius: 4 },
});
