import { router, Stack, useLocalSearchParams } from 'expo-router';
import { Pressable, StyleSheet, View } from 'react-native';

import { ErrorView } from '@/components/error-view';
import { Card, Pill, Screen, SectionHeader } from '@/components/screen';
import { Stat, StatRow } from '@/components/stat';
import { ThemedText } from '@/components/themed-text';
import { Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import type { LiveLeague, LiveStandingRow, Swing, SwingPlayer } from '@/lib/api';
import { chipName, liveBadge, perPoint, role } from '@/lib/live';
import { useLiveLeague, useTeamId } from '@/lib/query';

export default function LiveLeagueScreen() {
  const { id, name } = useLocalSearchParams<{ id: string; name?: string }>();
  const teamId = useTeamId();
  const league = useLiveLeague(teamId, Number(id));

  return (
    <Screen testID="live-league-screen" belowHeader onRefresh={() => league.refetch()} refreshing={league.isRefetching}>
      <Stack.Screen options={{ title: league.data?.league.name ?? name ?? 'Live table' }} />
      {league.isPending ? <ThemedText themeColor="textSecondary">Working out everyone&apos;s live points…</ThemedText> : null}
      {league.isError ? <ErrorView error={league.error} onRetry={() => league.refetch()} /> : null}
      {league.data ? <Body data={league.data} /> : null}
    </Screen>
  );
}

function Body({ data }: { data: LiveLeague }) {
  const theme = useTheme();
  const badge = liveBadge(data);
  return (
    <>
      <Card variant="hero">
        <View style={styles.badges}>
          <ThemedText type="eyebrow" style={{ color: theme.brand }}>
            {data.gameweek.name}
          </ThemedText>
          <Pill label={badge.label} color={badge.color} soft={badge.soft} />
        </View>
        <StatRow>
          <Stat onHero label="Live rank" value={data.your_live_rank ? `#${data.your_live_rank}` : '—'} />
          <Stat onHero label="To leader" value={data.gap_to_leader ? `−${data.gap_to_leader}` : data.gap_to_leader === 0 ? 'Top' : '—'} />
          <Stat onHero label="To next" value={data.gap_to_next ? `−${data.gap_to_next}` : '—'} />
        </StatRow>
      </Card>

      {data.swing ? <SwingView swing={data.swing} finished={data.finished} /> : null}

      <SectionHeader title="Live table" />
      <Card style={styles.table}>
        {data.standings.map((row, i) => (
          <Line key={row.entry} row={row} first={i === 0} leagueId={data.league.id} />
        ))}
      </Card>
      <ThemedText type="caption" themeColor="textSecondary">
        {data.partial
          ? `Live ranks cover the top ${data.managers_read}; anyone further down shows FPL's figures. `
          : ''}
        Points include provisional bonus and projected substitutions. Tap a manager to go head to head.
      </ThemedText>
    </>
  );
}

/** Who decides the league from here, against the nearest rival and the field. */
function SwingView({ swing, finished }: { swing: Swing; finished: boolean }) {
  const empty = !swing.against_rival.length && !swing.for_you.length && !swing.against_you.length;
  if (empty) {
    return finished ? null : (
      <Card>
        <ThemedText type="small" themeColor="textSecondary">
          Nothing left to decide between you and the league: the players still to play are owned the same way.
        </ThemedText>
      </Card>
    );
  }
  const r = swing.rival;
  return (
    <>
      <SectionHeader title="What decides it from here" />
      {r && swing.against_rival.length ? (
        <Card testID="swing-rival">
          <ThemedText type="headline">
            Against {r.team_name}
            <ThemedText type="small" themeColor="textSecondary">
              {r.gap > 0 ? `  ${r.gap} ahead of you` : r.gap < 0 ? `  ${-r.gap} behind you` : '  level'}
            </ThemedText>
          </ThemedText>
          {swing.against_rival.map((p) => (
            <SwingRow key={p.player_id} player={p} detail={`You: ${role(p.you)} · them: ${role(p.them ?? 0)}`} />
          ))}
        </Card>
      ) : null}
      {swing.for_you.length || swing.against_you.length ? (
        <Card testID="swing-league">
          <ThemedText type="headline">Against the league</ThemedText>
          <ThemedText type="caption" themeColor="textSecondary">
            Your share of each player against his average across {swing.managers} rivals.
          </ThemedText>
          {[...swing.for_you, ...swing.against_you].map((p) => (
            <SwingRow key={p.player_id} player={p} detail={`You: ${role(p.you)} · league: ${(p.eo ?? 0).toFixed(1)} per point`} />
          ))}
        </Card>
      ) : null}
    </>
  );
}

function SwingRow({ player, detail }: { player: SwingPlayer; detail: string }) {
  const theme = useTheme();
  const tone = player.net > 0 ? 'highlight' : 'danger';
  return (
    <View testID={`swing-${player.player_id}`} style={styles.swing}>
      <View style={styles.grow}>
        <ThemedText type="smallBold">
          {player.name}{' '}
          <ThemedText type="caption" themeColor="textSecondary">
            {player.team} · {player.state === 'playing' ? 'playing now' : 'yet to play'}
          </ThemedText>
        </ThemedText>
        <ThemedText type="caption" themeColor="textSecondary">
          {detail}
        </ThemedText>
      </View>
      <ThemedText type="smallBold" style={{ color: theme[tone] }}>
        {perPoint(player.net)}
      </ThemedText>
    </View>
  );
}

function Line({ row, first, leagueId }: { row: LiveStandingRow; first: boolean; leagueId: number }) {
  const theme = useTheme();
  const rank = row.live_rank ?? row.rank;
  // Against the table at the start of the gameweek.
  const moved = row.live_rank && row.last_rank && row.last_rank !== row.live_rank ? (row.live_rank < row.last_rank ? '▲' : '▼') : '';
  const chip = chipName(row.chip);
  const detail = [
    row.captain ? `(C) ${row.captain}` : null,
    row.players_left !== null ? `${row.players_left} to play` : null,
    chip,
  ].filter(Boolean);
  return (
    <Pressable
      testID={`live-standing-${row.entry}`}
      accessibilityRole={row.is_you ? undefined : 'button'}
      disabled={row.is_you}
      onPress={() => router.push({ pathname: '/rival/[id]', params: { id: String(row.entry), league: String(leagueId) } })}
      style={({ pressed }) => [
        styles.row,
        !first && { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: theme.hairline },
        row.is_you && { backgroundColor: theme.accentSoft },
        pressed && { backgroundColor: theme.backgroundSelected },
      ]}>
      <View style={styles.rank}>
        <ThemedText type="smallBold">{rank}</ThemedText>
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
          {detail.join(' · ') || row.manager_name}
        </ThemedText>
      </View>
      <View style={styles.points}>
        <ThemedText type="headline" style={styles.num}>
          {row.gameweek_points}
        </ThemedText>
        <ThemedText type="caption" themeColor="textSecondary" style={styles.num}>
          {row.total.toLocaleString()}
        </ThemedText>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  badges: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: Spacing.two },
  table: { padding: 0, gap: 0, overflow: 'hidden' },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 16, paddingVertical: 10 },
  rank: { width: 34, alignItems: 'center' },
  points: { alignItems: 'flex-end' },
  swing: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 6 },
  num: { fontVariant: ['tabular-nums'] },
  grow: { flex: 1 },
});
