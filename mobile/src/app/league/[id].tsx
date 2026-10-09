import { router, Stack, useLocalSearchParams } from 'expo-router';
import { Pressable, StyleSheet, View } from 'react-native';

import { ErrorView } from '@/components/error-view';
import { openPlayer } from '@/components/pitch';
import { Card, Screen, SectionHeader } from '@/components/screen';
import { Stat, StatRow } from '@/components/stat';
import { ThemedText } from '@/components/themed-text';
import { Radius, Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import type { LeaguePlayer, LeagueView, StandingRow } from '@/lib/api';
import { useLeague, useTeamId } from '@/lib/query';

export default function League() {
  const { id, name } = useLocalSearchParams<{ id: string; name?: string }>();
  const teamId = useTeamId();
  const league = useLeague(teamId, Number(id));

  return (
    <Screen testID="league-screen" belowHeader onRefresh={() => league.refetch()} refreshing={league.isRefetching}>
      <Stack.Screen options={{ title: league.data?.league.name ?? name ?? 'League' }} />
      {league.isPending ? (
        <ThemedText themeColor="textSecondary">Reading the table and your rivals&apos; squads…</ThemedText>
      ) : null}
      {league.isError ? <ErrorView error={league.error} onRetry={() => league.refetch()} /> : null}
      {league.data ? <LeagueBody data={league.data} /> : null}
    </Screen>
  );
}

function LeagueBody({ data }: { data: LeagueView }) {
  const theme = useTheme();
  const leader = data.standings[0];
  return (
    <>
      <Card variant="hero">
        <ThemedText type="eyebrow" style={{ color: theme.brand }}>
          {data.league.name}
        </ThemedText>
        <StatRow>
          <Stat onHero label="Your rank" value={data.your_rank ? `#${data.your_rank.toLocaleString()}` : '—'} />
          <Stat onHero label="To leader" value={data.gaps ? (data.gaps.to_leader ? `−${data.gaps.to_leader}` : 'Top') : '—'} />
          <Stat onHero label="To next" value={data.gaps ? (data.gaps.to_next ? `−${data.gaps.to_next}` : '—') : '—'} />
        </StatRow>
        {leader && !leader.is_you ? (
          <ThemedText type="caption" style={{ color: theme.onHeroMuted }}>
            {leader.team_name} leads on {leader.total} points.
          </ThemedText>
        ) : null}
      </Card>

      {data.threats.length > 0 ? (
        <>
          <SectionHeader title="Rivals own, you don't" />
          <Card>
            <ThemedText type="caption" themeColor="textSecondary">
              Owned by at least half of the top {data.rivals_sampled}. If they score, you fall behind.
            </ThemedText>
            {data.threats.slice(0, 8).map((p) => (
              <PlayerShare key={p.player_id} player={p} sample={data.rivals_sampled} tone="danger" />
            ))}
          </Card>
        </>
      ) : null}

      {data.differentials.length > 0 ? (
        <>
          <SectionHeader title="Your differentials" />
          <Card>
            <ThemedText type="caption" themeColor="textSecondary">
              Players few of your rivals own: where you can gain ground.
            </ThemedText>
            {data.differentials.slice(0, 6).map((p) => (
              <PlayerShare key={p.player_id} player={p} sample={data.rivals_sampled} tone="highlight" />
            ))}
          </Card>
        </>
      ) : null}

      <SectionHeader title="Table" />
      <Card style={styles.table}>
        {data.standings.map((row, i) => (
          <StandingLine key={row.entry} row={row} first={i === 0} leagueId={data.league.id} />
        ))}
      </Card>
      <ThemedText type="caption" themeColor="textSecondary">
        Rival squads as of the GW{data.squads_as_of_gameweek} deadline; FPL hides newer transfers. Projections are for
        GW{data.projections_for_gameweek}. Tap a manager to go head to head.
      </ThemedText>
    </>
  );
}

function PlayerShare({ player, sample, tone }: { player: LeaguePlayer; sample: number; tone: 'danger' | 'highlight' }) {
  const theme = useTheme();
  const share = sample ? (player.owned_by ?? 0) / sample : 0;
  return (
    <Pressable accessibilityRole="button" onPress={() => openPlayer(player.player_id)} style={styles.shareRow}>
      <View style={styles.grow}>
        <ThemedText type="smallBold">
          {player.name} <ThemedText type="caption" themeColor="textSecondary">{player.team} · {player.position}</ThemedText>
        </ThemedText>
        <View style={[styles.bar, { backgroundColor: theme.backgroundSelected }]}>
          <View style={[styles.fill, { width: `${Math.max(4, share * 100)}%`, backgroundColor: theme[tone] }]} />
        </View>
      </View>
      <View style={styles.right}>
        <ThemedText type="smallBold">
          {player.owned_by ?? 0}/{sample}
        </ThemedText>
        <ThemedText type="caption" themeColor="textSecondary">
          {player.xpts.toFixed(1)} xPts
        </ThemedText>
      </View>
    </Pressable>
  );
}

function StandingLine({ row, first, leagueId }: { row: StandingRow; first: boolean; leagueId: number }) {
  const theme = useTheme();
  const moved = row.last_rank && row.last_rank !== row.rank ? (row.rank < row.last_rank ? '▲' : '▼') : '';
  return (
    <Pressable
      testID={`standing-${row.entry}`}
      accessibilityRole={row.is_you ? undefined : 'button'}
      disabled={row.is_you}
      onPress={() => router.push({ pathname: '/rival/[id]', params: { id: String(row.entry), league: String(leagueId) } })}
      style={({ pressed }) => [
        styles.standing,
        !first && { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: theme.hairline },
        row.is_you && { backgroundColor: theme.accentSoft },
        pressed && { backgroundColor: theme.backgroundSelected },
      ]}>
      <View style={styles.rank}>
        <ThemedText type="smallBold">{row.rank}</ThemedText>
        {moved ? (
          <ThemedText type="caption" style={{ color: moved === '▲' ? theme.highlight : theme.danger }}>
            {moved}
          </ThemedText>
        ) : null}
      </View>
      <View style={styles.grow}>
        <ThemedText type="smallBold" numberOfLines={1}>
          {row.team_name}
          {row.is_you ? ' (you)' : ''}
        </ThemedText>
        <ThemedText type="caption" themeColor="textSecondary" numberOfLines={1}>
          {row.manager_name} · GW {row.gameweek_points}
        </ThemedText>
      </View>
      <ThemedText type="headline" style={styles.total}>
        {row.total}
      </ThemedText>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  table: { padding: 0, gap: 0, overflow: 'hidden' },
  standing: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 16, paddingVertical: 10 },
  rank: { width: 34, alignItems: 'center' },
  total: { fontVariant: ['tabular-nums'] },
  shareRow: { flexDirection: 'row', alignItems: 'center', gap: Spacing.three, paddingVertical: 6 },
  bar: { height: 6, borderRadius: Radius.pill, marginTop: 4, overflow: 'hidden' },
  fill: { height: 6, borderRadius: Radius.pill },
  right: { alignItems: 'flex-end' },
  grow: { flex: 1 },
});
