import { Image } from 'expo-image';
import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import { Button } from '@/components/button';
import { ErrorView } from '@/components/error-view';
import { Loading } from '@/components/loading';
import { PlayerPhoto } from '@/components/player-photo';
import { openPlayer } from '@/components/pitch';
import { Card, Screen, SectionHeader } from '@/components/screen';
import { ThemedText } from '@/components/themed-text';
import { Radius, Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import type { Story } from '@/lib/api';
import { timeAgo } from '@/lib/format';
import { initials } from '@/lib/news';
import { useStory, useTeamId } from '@/lib/query';

const GROUND = '#37003C';

/** The article behind a squad warning or alert. */
export default function StoryScreen() {
  const { id, alert } = useLocalSearchParams<{ id: string; alert?: string }>();
  const story = useStory(useTeamId(), Number(id), alert ? Number(alert) : undefined);
  return (
    <Screen testID="story-screen" belowHeader onRefresh={() => story.refetch()} refreshing={story.isRefetching}>
      {story.isPending ? <Loading /> : null}
      {story.isError ? <ErrorView error={story.error} onRetry={() => story.refetch()} /> : null}
      {story.data ? <Article s={story.data} /> : null}
    </Screen>
  );
}

function youLines(s: Story): string[] {
  const y = s.you;
  const lines: string[] = [];
  if (!y.owned) lines.push(`${s.player.name} isn't in your squad.`);
  else if (y.captain) lines.push(`He's your captain${y.starting ? ' and in your starting XI' : ''}.`);
  else lines.push(y.starting ? "He's in your starting XI." : "He's in your squad.");
  if (y.projected_next !== null && y.gameweek) {
    lines.push(`He's projected ${y.projected_next.toFixed(1)} points in ${y.gameweek}.`);
  }
  return lines;
}

function Article({ s }: { s: Story }) {
  const theme = useTheme();
  const [failed, setFailed] = useState(false);
  const p = s.player;
  return (
    <>
      <View style={[styles.hero, { borderRadius: Radius.lg }]}>
        {p.photo && !failed ? (
          <Image
            source={{ uri: p.photo }}
            style={styles.heroPhoto}
            contentFit="contain"
            contentPosition="bottom"
            cachePolicy="memory-disk"
            onError={() => setFailed(true)}
            accessibilityIgnoresInvertColors
          />
        ) : (
          <ThemedText style={styles.heroInitials}>{initials(p.name)}</ThemedText>
        )}
        <View style={[styles.tag, { backgroundColor: s.severity === 'critical' ? theme.danger : theme.warning }]}>
          <ThemedText type="caption" style={styles.tagText}>
            {p.status_label}
          </ThemedText>
        </View>
      </View>

      <View style={styles.header}>
        <ThemedText testID="story-headline" type="title" style={styles.headline}>
          {s.headline}
        </ThemedText>
        <ThemedText type="caption" themeColor="textSecondary">
          {[p.team_name, p.position, `£${p.price.toFixed(1)}m`, s.published_at ? timeAgo(s.published_at) : null].filter(Boolean).join(' · ')}
        </ThemedText>
      </View>

      <ThemedText style={styles.lede}>{s.summary}</ThemedText>

      <SectionHeader title="What it means for you" />
      <Card testID="story-you">
        {youLines(s).map((l) => (
          <ThemedText key={l} type="small">
            {l}
          </ThemedText>
        ))}
        {s.you.plan ? (
          <View style={[styles.plan, { backgroundColor: theme.backgroundSelected }]}>
            <ThemedText type="small">Our transfer plan already moves him out:</ThemedText>
            <ThemedText type="smallBold">
              {s.you.plan.out} → {s.you.plan.in}
            </ThemedText>
          </View>
        ) : null}
      </Card>

      {s.history.length > 0 ? (
        <>
          <SectionHeader title="Recent news" />
          <Card style={styles.list}>
            {s.history.map((h, i) => (
              <View key={`${h.at}${i}`} style={[styles.event, i > 0 && { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: theme.hairline }]}>
                <View style={[styles.dot, { backgroundColor: h.event_type.startsWith('price') ? theme.accent : theme.warning }]} />
                <View style={styles.grow}>
                  <ThemedText type="small">{h.news ?? h.status ?? h.event_type.replace(/_/g, ' ')}</ThemedText>
                  <ThemedText type="caption" themeColor="textSecondary">
                    {h.at ? timeAgo(h.at) : ''}
                  </ThemedText>
                </View>
              </View>
            ))}
          </Card>
        </>
      ) : null}

      {s.replacements.length > 0 ? (
        <>
          <SectionHeader title={s.you.owned ? 'Replacements you can afford' : 'Alternatives'} />
          <Card style={styles.list}>
            {s.replacements.map((r, i) => (
              <Pressable
                key={r.player_id}
                testID={`replacement-${r.player_id}`}
                accessibilityRole="button"
                onPress={() => openPlayer(r.player_id)}
                style={({ pressed }) => [
                  styles.event,
                  i > 0 && { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: theme.hairline },
                  pressed && { opacity: 0.7 },
                ]}>
                <PlayerPhoto uri={r.photo} position={p.position} size={40} />
                <View style={styles.grow}>
                  <ThemedText type="smallBold">{r.name}</ThemedText>
                  <ThemedText type="caption" themeColor="textSecondary">
                    {r.team} · £{r.price.toFixed(1)}m
                  </ThemedText>
                </View>
                <View style={styles.right}>
                  <ThemedText type="smallBold">{r.xpts_horizon.toFixed(1)}</ThemedText>
                  <ThemedText type="caption" themeColor="textSecondary">
                    xPts · {s.horizon} GW
                  </ThemedText>
                </View>
              </Pressable>
            ))}
          </Card>
        </>
      ) : null}

      {s.fixtures.length > 0 ? (
        <>
          <SectionHeader title={`${p.team} next`} />
          <View style={styles.fixtures}>
            {s.fixtures.map((f) => (
              <View key={f.gameweek} style={[styles.fixture, { backgroundColor: theme.backgroundElement }]}>
                <ThemedText type="caption" themeColor="textSecondary">
                  GW{f.gameweek}
                </ThemedText>
                <ThemedText type="smallBold">{f.opponents.join(', ') || 'Blank'}</ThemedText>
              </View>
            ))}
          </View>
        </>
      ) : null}

      <View style={styles.actions}>
        <Button title="See player" variant="secondary" onPress={() => openPlayer(p.id)} />
        {s.you.owned ? <Button title="Plan transfers" onPress={() => router.push('/transfers')} /> : null}
      </View>
    </>
  );
}

const styles = StyleSheet.create({
  hero: { height: 240, backgroundColor: GROUND, overflow: 'hidden', alignItems: 'center', justifyContent: 'flex-end' },
  heroPhoto: { width: '100%', height: 240 },
  heroInitials: { color: '#FFFFFF', fontSize: 56, lineHeight: 64, fontWeight: '900', marginBottom: 80 },
  tag: { position: 'absolute', top: Spacing.three, left: Spacing.three, borderRadius: Radius.pill, paddingHorizontal: 10, paddingVertical: 3 },
  tagText: { color: '#FFFFFF', fontWeight: '800' },
  header: { gap: 4 },
  headline: { fontSize: 28, lineHeight: 34 },
  lede: { fontSize: 17, lineHeight: 25 },
  plan: { borderRadius: Radius.md, padding: 12, gap: 2, marginTop: Spacing.one },
  list: { paddingVertical: 4, gap: 0 },
  event: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 10 },
  dot: { width: 8, height: 8, borderRadius: 4 },
  right: { alignItems: 'flex-end' },
  fixtures: { flexDirection: 'row', gap: Spacing.two },
  fixture: { flex: 1, borderRadius: Radius.md, padding: 12, gap: 2 },
  actions: { gap: Spacing.two },
  grow: { flex: 1 },
});
