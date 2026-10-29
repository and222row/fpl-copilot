import { router, Stack, useLocalSearchParams } from 'expo-router';
import { Pressable, StyleSheet, View } from 'react-native';

import { ErrorView } from '@/components/error-view';
import { MatchScore, ResultChip, resultWord } from '@/components/h2h';
import { Loading } from '@/components/loading';
import { Card, Pill, Screen, SectionHeader } from '@/components/screen';
import { ThemedText } from '@/components/themed-text';
import { Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import type { H2HLeague } from '@/lib/api';
import { liveBadge } from '@/lib/live';
import { useH2HLeague, useTeamId } from '@/lib/query';

/** Another manager's team this gameweek, on a pitch. */
function openManager(entry: number, name: string) {
  router.push({ pathname: '/manager/[id]', params: { id: String(entry), name } });
}

export default function H2HScreen() {
  const { id, name } = useLocalSearchParams<{ id: string; name?: string }>();
  const league = useH2HLeague(useTeamId(), Number(id));
  return (
    <Screen testID="h2h-screen" belowHeader onRefresh={() => league.refetch()} refreshing={league.isRefetching}>
      <Stack.Screen options={{ title: league.data?.league.name ?? name ?? 'Head to head' }} />
      {league.isPending ? <Loading /> : null}
      {league.isError ? <ErrorView error={league.error} onRetry={() => league.refetch()} /> : null}
      {league.data ? <Body data={league.data} /> : null}
    </Screen>
  );
}

function Body({ data }: { data: H2HLeague }) {
  const theme = useTheme();
  const { W, D, L } = data.record;
  const current = data.current;
  const next = data.next;
  return (
    <>
      {current ? (
        <Pressable
          testID="h2h-current"
          accessibilityRole={current.opponent ? 'button' : undefined}
          disabled={!current.opponent}
          onPress={() => current.opponent && openManager(current.opponent.entry, current.opponent.team_name)}
          style={({ pressed }) => pressed && styles.pressed}>
          <Card variant="hero">
            <View style={styles.between}>
              <ThemedText type="eyebrow" style={{ color: theme.brand }}>
                Gameweek {current.gameweek}
              </ThemedText>
              {data.current_status ? (
                <Pill {...liveBadge(data.current_status)} />
              ) : current.result ? (
                <Pill label={resultWord(current.result)} color="onBrand" soft="brand" />
              ) : null}
            </View>
            <MatchScore match={current} onHero />
            {current.opponent ? (
              <ThemedText type="caption" style={{ color: theme.onHeroMuted }}>
                See their team ›
              </ThemedText>
            ) : null}
          </Card>
        </Pressable>
      ) : null}

      {next ? (
        <Pressable
          testID="h2h-next"
          accessibilityRole={next.opponent ? 'button' : undefined}
          disabled={!next.opponent}
          onPress={() => next.opponent && openManager(next.opponent.entry, next.opponent.team_name)}
          style={({ pressed }) => pressed && styles.pressed}>
          <Card>
            <ThemedText type="caption" themeColor="textSecondary">
              Next · Gameweek {next.gameweek}
            </ThemedText>
            <View style={styles.between}>
              <View style={styles.grow}>
                <ThemedText type="headline">{next.opponent ? `vs ${next.opponent.team_name}` : 'A bye'}</ThemedText>
                {next.opponent ? (
                  <ThemedText type="small" themeColor="textSecondary">
                    {next.opponent.manager_name}
                  </ThemedText>
                ) : null}
              </View>
              {next.opponent ? <Chevron /> : null}
            </View>
          </Card>
        </Pressable>
      ) : null}

      <SectionHeader title="Table" />
      <Card style={styles.table}>
        {data.standings.map((r, i) => (
          <Pressable
            key={r.entry}
            testID={`h2h-standing-${r.entry}`}
            accessibilityRole={r.is_you ? undefined : 'button'}
            disabled={r.is_you}
            onPress={() => openManager(r.entry, r.team_name)}
            style={({ pressed }) => [
              styles.row,
              i > 0 && { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: theme.hairline },
              r.is_you && { backgroundColor: theme.accentSoft },
              pressed && { backgroundColor: theme.backgroundSelected },
            ]}>
            <ThemedText type="smallBold" style={styles.rank}>
              {r.rank}
            </ThemedText>
            <View style={styles.grow}>
              <ThemedText type="smallBold" numberOfLines={1}>
                {r.team_name}
                {r.is_you ? ' (you)' : ''}
              </ThemedText>
              <ThemedText type="caption" themeColor="textSecondary">
                {`W${r.won} D${r.drawn} L${r.lost} · ${r.points_for} scored`}
              </ThemedText>
            </View>
            <ThemedText type="headline" style={styles.num}>
              {r.points}
            </ThemedText>
            {r.is_you ? <View style={styles.chevronSpace} /> : <Chevron />}
          </Pressable>
        ))}
      </Card>
      {data.partial ? (
        <ThemedText type="caption" themeColor="textSecondary">
          The top of the table; the full league is on the FPL site.
        </ThemedText>
      ) : null}

      {data.results.length ? (
        <>
          <SectionHeader title={`Your results · ${W}W ${D}D ${L}L`} />
          <Card style={styles.table}>
            {data.results.map((m, i) => (
              <Pressable
                key={m.gameweek}
                testID={`h2h-result-${m.gameweek}`}
                accessibilityRole={m.opponent ? 'button' : undefined}
                disabled={!m.opponent}
                onPress={() => m.opponent && openManager(m.opponent.entry, m.opponent.team_name)}
                style={({ pressed }) => [
                  styles.row,
                  i > 0 && { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: theme.hairline },
                  pressed && { backgroundColor: theme.backgroundSelected },
                ]}>
                <ResultChip result={m.result} />
                <View style={styles.grow}>
                  <ThemedText type="smallBold" numberOfLines={1}>
                    {m.opponent ? m.opponent.team_name : 'Bye'}
                  </ThemedText>
                  <ThemedText type="caption" themeColor="textSecondary">
                    Gameweek {m.gameweek}
                  </ThemedText>
                </View>
                <ThemedText type="smallBold" style={styles.num}>
                  {m.your_points}–{m.their_points}
                </ThemedText>
                {m.opponent ? <Chevron /> : <View style={styles.chevronSpace} />}
              </Pressable>
            ))}
          </Card>
          <ThemedText type="caption" themeColor="textSecondary">
            Tap a team to see their squad this gameweek.
          </ThemedText>
        </>
      ) : null}
    </>
  );
}

function Chevron() {
  return (
    <ThemedText type="headline" themeColor="textSecondary" style={styles.chevron} accessibilityElementsHidden>
      ›
    </ThemedText>
  );
}

const styles = StyleSheet.create({
  between: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: Spacing.two },
  table: { padding: 0, gap: 0, overflow: 'hidden' },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 16, paddingVertical: 10 },
  rank: { width: 24, textAlign: 'center' },
  num: { fontVariant: ['tabular-nums'] },
  chevron: { width: 12 },
  chevronSpace: { width: 12 },
  pressed: { opacity: 0.85 },
  grow: { flex: 1 },
});
