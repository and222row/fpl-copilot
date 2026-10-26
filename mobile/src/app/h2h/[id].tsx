import { Stack, useLocalSearchParams } from 'expo-router';
import { StyleSheet, View } from 'react-native';

import { ErrorView } from '@/components/error-view';
import { Card, Pill, Screen, SectionHeader } from '@/components/screen';
import { ThemedText } from '@/components/themed-text';
import { Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import { MatchScore, ResultChip, resultWord } from '@/components/h2h';
import type { H2HLeague } from '@/lib/api';
import { liveBadge } from '@/lib/live';
import { useH2HLeague, useTeamId } from '@/lib/query';

export default function H2HScreen() {
  const { id, name } = useLocalSearchParams<{ id: string; name?: string }>();
  const league = useH2HLeague(useTeamId(), Number(id));
  return (
    <Screen testID="h2h-screen" belowHeader onRefresh={() => league.refetch()} refreshing={league.isRefetching}>
      <Stack.Screen options={{ title: league.data?.league.name ?? name ?? 'Head to head' }} />
      {league.isPending ? <ThemedText themeColor="textSecondary">Reading your fixtures…</ThemedText> : null}
      {league.isError ? <ErrorView error={league.error} onRetry={() => league.refetch()} /> : null}
      {league.data ? <Body data={league.data} /> : null}
    </Screen>
  );
}

function Body({ data }: { data: H2HLeague }) {
  const theme = useTheme();
  const { W, D, L } = data.record;
  return (
    <>
      {data.current ? (
        <Card variant="hero" testID="h2h-current">
          <View style={styles.between}>
            <ThemedText type="eyebrow" style={{ color: theme.brand }}>
              Gameweek {data.current.gameweek}
            </ThemedText>
            {data.current_status ? (
              <Pill {...liveBadge(data.current_status)} />
            ) : data.current.result ? (
              <Pill label={resultWord(data.current.result)} color="onBrand" soft="brand" />
            ) : null}
          </View>
          <MatchScore match={data.current} onHero />
        </Card>
      ) : null}

      {data.next ? (
        <Card testID="h2h-next">
          <ThemedText type="caption" themeColor="textSecondary">
            Next · Gameweek {data.next.gameweek}
          </ThemedText>
          <ThemedText type="headline">{data.next.opponent ? `vs ${data.next.opponent.team_name}` : 'A bye'}</ThemedText>
          {data.next.opponent ? (
            <ThemedText type="small" themeColor="textSecondary">
              {data.next.opponent.manager_name}
            </ThemedText>
          ) : null}
        </Card>
      ) : null}

      <SectionHeader title="Table" />
      <Card style={styles.table}>
        {data.standings.map((r, i) => (
          <View
            key={r.entry}
            testID={`h2h-standing-${r.entry}`}
            style={[
              styles.row,
              i > 0 && { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: theme.hairline },
              r.is_you && { backgroundColor: theme.accentSoft },
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
          </View>
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
              <View
                key={m.gameweek}
                style={[styles.row, i > 0 && { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: theme.hairline }]}>
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
              </View>
            ))}
          </Card>
        </>
      ) : null}
    </>
  );
}

const styles = StyleSheet.create({
  between: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: Spacing.two },
  table: { padding: 0, gap: 0, overflow: 'hidden' },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 16, paddingVertical: 10 },
  rank: { width: 24, textAlign: 'center' },
  num: { fontVariant: ['tabular-nums'] },
  grow: { flex: 1 },
});
