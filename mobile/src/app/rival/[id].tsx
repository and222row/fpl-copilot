import { Stack, useLocalSearchParams } from 'expo-router';
import { Pressable, StyleSheet, View } from 'react-native';

import { ErrorView } from '@/components/error-view';
import { openPlayer } from '@/components/pitch';
import { Card, Screen, SectionHeader } from '@/components/screen';
import { Stat, StatRow } from '@/components/stat';
import { ThemedText } from '@/components/themed-text';
import { useTheme } from '@/hooks/use-theme';
import type { LeaguePlayer, RivalView } from '@/lib/api';
import { useRival, useTeamId } from '@/lib/query';

export default function Rival() {
  const { id, league } = useLocalSearchParams<{ id: string; league: string }>();
  const teamId = useTeamId();
  const rival = useRival(teamId, Number(league), Number(id));

  return (
    <Screen testID="rival-screen" belowHeader onRefresh={() => rival.refetch()} refreshing={rival.isRefetching}>
      <Stack.Screen options={{ title: rival.data?.rival.team_name ?? 'Head to head' }} />
      {rival.isPending ? <ThemedText themeColor="textSecondary">Comparing squads…</ThemedText> : null}
      {rival.isError ? <ErrorView error={rival.error} onRetry={() => rival.refetch()} /> : null}
      {rival.data ? <RivalBody data={rival.data} /> : null}
    </Screen>
  );
}

function RivalBody({ data }: { data: RivalView }) {
  const theme = useTheme();
  const gap = data.points_gap;
  const edge = data.edge_next_gameweek;
  return (
    <>
      <Card variant="hero">
        <ThemedText type="eyebrow" style={{ color: theme.brand }}>
          {data.rival.manager_name}
        </ThemedText>
        <StatRow>
          <Stat onHero label="Their rank" value={`#${data.rival.rank}`} />
          <Stat onHero label="Gap" value={gap === null ? '—' : gap > 0 ? `${gap} ahead` : gap < 0 ? `${-gap} behind` : 'Level'} />
          <Stat onHero label="Captain" value={data.rival.captain ?? '—'} />
        </StatRow>
        <ThemedText type="small" style={{ color: theme.onHeroMuted }}>
          {edge > 0
            ? `Your differences project ${edge.toFixed(1)} points more than theirs next gameweek.`
            : edge < 0
              ? `Their differences project ${(-edge).toFixed(1)} points more than yours next gameweek.`
              : 'Your differences cancel out next gameweek.'}
        </ThemedText>
      </Card>

      <Side title={`Only you have (${data.only_yours.length})`} players={data.only_yours} tone="highlight" />
      <Side title={`Only they have (${data.only_theirs.length})`} players={data.only_theirs} tone="danger" />
      <Side title={`Both have (${data.shared.length})`} players={data.shared} />

      <ThemedText type="caption" themeColor="textSecondary">
        Their squad as of the GW{data.squads_as_of_gameweek} deadline; yours includes transfers you recorded.
        Projections are for GW{data.projections_for_gameweek}.
      </ThemedText>
    </>
  );
}

function Side({ title, players, tone }: { title: string; players: LeaguePlayer[]; tone?: 'highlight' | 'danger' }) {
  const theme = useTheme();
  if (players.length === 0) return null;
  return (
    <>
      <SectionHeader title={title} />
      <Card style={styles.list}>
        {players.map((p, i) => (
          <Pressable
            key={p.player_id}
            accessibilityRole="button"
            onPress={() => openPlayer(p.player_id)}
            style={[styles.row, i > 0 && { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: theme.hairline }]}>
            {tone ? <View style={[styles.dot, { backgroundColor: theme[tone] }]} /> : null}
            <View style={styles.grow}>
              <ThemedText type="smallBold">{p.name}</ThemedText>
              <ThemedText type="caption" themeColor="textSecondary">
                {p.team} · {p.position} · £{p.price.toFixed(1)}m
              </ThemedText>
            </View>
            <ThemedText type="smallBold">{p.xpts.toFixed(1)}</ThemedText>
          </Pressable>
        ))}
      </Card>
    </>
  );
}

const styles = StyleSheet.create({
  list: { paddingVertical: 4, gap: 0 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 10 },
  dot: { width: 8, height: 8, borderRadius: 4 },
  grow: { flex: 1 },
});
