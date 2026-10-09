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
 * How connecting works, before the user starts: where the Team ID is, and
 * that the ownership code goes into the team name on the FPL website (the
 * FPL app cannot rename a team).
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
              Getting started · 1 of 4
            </ThemedText>
            <ThemedText type="title" accessibilityRole="header" style={{ color: theme.onHero }}>
              Welcome
            </ThemedText>
            <ThemedText style={{ color: theme.onHeroMuted }}>
              Connect your FPL team in about two minutes. Swipe for how it works, or tap Connect my team.
            </ThemedText>
            <Steps
              items={[
                { title: 'Find your Team ID', body: 'A number on the FPL website.' },
                { title: 'Prove the team is yours', body: 'Add a short code to your team name.' },
                { title: '30 days free', body: 'Your trial starts the moment it is verified.' },
              ]}
            />
          </Card>,

          <Card key="team-id" style={styles.slide}>
            <ThemedText type="eyebrow" themeColor="textSecondary">
              Step 1 of 3 · 2 of 4
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

          <Card key="code" style={styles.slide}>
            <ThemedText type="eyebrow" themeColor="textSecondary">
              Step 2 of 3 · 3 of 4
            </ThemedText>
            <ThemedText type="subtitle">Add the code to your team name</ThemedText>
            <ThemedText type="small" themeColor="textSecondary">
              Anyone can type a Team ID, so we give you a 6-character code to put in your team name. Do it on the FPL
              website: the FPL app cannot rename a team.
            </ThemedText>
            <Steps
              items={[
                { body: 'On fantasy.premierleague.com, open Pick Team.' },
                { body: 'Scroll to Admin and tap Team Details.' },
                { body: 'Add the code anywhere in your team name, then tap Update details.' },
              ]}
            />
            <TeamNameField />
          </Card>,

          <Card key="verify" style={styles.slide}>
            <ThemedText type="eyebrow" themeColor="textSecondary">
              Step 3 of 3 · 4 of 4
            </ThemedText>
            <ThemedText type="subtitle">Verify, then change it back</ThemedText>
            <Steps
              items={[
                { body: 'Come back to FPL Copilot and tap Verify. A name change can take a minute to show.' },
                { body: 'Once verified, change your team name back whenever you like.' },
                { body: 'Your 30-day free trial starts straight away.' },
              ]}
            />
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
