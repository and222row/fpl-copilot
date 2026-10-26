import { useState } from 'react';
import { ScrollView, StyleSheet, View } from 'react-native';

import { ChipGroup } from '@/components/chip';
import { ErrorView } from '@/components/error-view';
import { Card, Screen } from '@/components/screen';
import { ThemedText } from '@/components/themed-text';
import { Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import type { FixturePlanner, FixtureView, PlannerMatch, PlannerTeam } from '@/lib/api';
import { byEase, colours, DIFFICULTY_COLOURS, ownedByClub } from '@/lib/fixtures';
import { useFixturePlanner, useRecommendation, useTeamId } from '@/lib/query';

const VIEWS = [
  { label: 'Overall', value: 'overall' },
  { label: 'For attackers', value: 'attack' },
  { label: 'For defenders', value: 'defence' },
] as const;
const WINDOWS = [
  { label: 'Next 3', value: 3 },
  { label: 'Next 6', value: 6 },
  { label: 'Next 8', value: 8 },
] as const;

const TEAM_WIDTH = 64;
const CELL_WIDTH = 54;
const CELL_HEIGHT = 40;

export default function FixturePlannerScreen() {
  const [view, setView] = useState<FixtureView>('overall');
  const [weeks, setWeeks] = useState<number>(6);
  const planner = useFixturePlanner(weeks);
  const rec = useRecommendation(useTeamId());
  const owned = ownedByClub(rec.data ? [...rec.data.lineup.starting, ...rec.data.lineup.bench] : []);

  return (
    <Screen testID="fixture-planner-screen" belowHeader onRefresh={() => planner.refetch()} refreshing={planner.isRefetching}>
      <ChipGroup options={VIEWS} value={view} onChange={setView} />
      <ChipGroup options={WINDOWS} value={weeks} onChange={setWeeks} />
      {planner.isPending ? <ThemedText themeColor="textSecondary">Rating the fixtures…</ThemedText> : null}
      {planner.isError ? <ErrorView error={planner.error} onRetry={() => planner.refetch()} /> : null}
      {planner.data ? <Grid data={planner.data} view={view} owned={owned} /> : null}
    </Screen>
  );
}

function Grid({ data, view, owned }: { data: FixturePlanner; view: FixtureView; owned: Record<string, number> }) {
  const theme = useTheme();
  if (!data.teams.length) {
    return <ThemedText themeColor="textSecondary">No fixtures ahead yet.</ThemedText>;
  }
  return (
    <>
      <Card style={styles.card}>
        <ScrollView horizontal showsHorizontalScrollIndicator={false}>
          <View>
            <View style={styles.row}>
              <View style={[styles.teamCell, styles.headerCell]}>
                <ThemedText type="caption" themeColor="textSecondary">
                  Club
                </ThemedText>
              </View>
              {data.gameweeks.map((gw) => (
                <View key={gw} style={[styles.cell, styles.headerCell]}>
                  <ThemedText type="caption" themeColor="textSecondary">
                    GW{gw}
                  </ThemedText>
                </View>
              ))}
            </View>
            {byEase(data.teams, view).map((t) => (
              <TeamRow key={t.team_id} team={t} view={view} owned={owned[t.team] ?? 0} />
            ))}
          </View>
        </ScrollView>
      </Card>

      <View style={styles.legend}>
        <ThemedText type="caption" themeColor="textSecondary">
          Easy
        </ThemedText>
        {DIFFICULTY_COLOURS.map((c) => (
          <View key={c.bg} style={[styles.swatch, { backgroundColor: c.bg }]} />
        ))}
        <ThemedText type="caption" themeColor="textSecondary">
          Hard
        </ThemedText>
        <View style={[styles.ownedBadge, { backgroundColor: theme.accent }]}>
          <ThemedText style={[styles.ownedText, { color: theme.onAccent }]}>2</ThemedText>
        </View>
        <ThemedText type="caption" themeColor="textSecondary">
          your players
        </ThemedText>
      </View>
      <ThemedText type="caption" themeColor="textSecondary">
        {data.source === 'model'
          ? 'Rated by our team-strength model: for attackers, the goals a club is expected to score; for defenders, the goals it is expected to concede. '
          : "FPL's own difficulty, until our team ratings are built. "}
        Ranked by the whole run: a double counts twice, a blank counts nothing. Home fixtures in capitals.
      </ThemedText>
    </>
  );
}

function TeamRow({ team, view, owned }: { team: PlannerTeam; view: FixtureView; owned: number }) {
  const theme = useTheme();
  return (
    <View testID={`planner-${team.team}`} style={styles.row}>
      <View style={styles.teamCell}>
        <ThemedText type="smallBold">{team.team}</ThemedText>
        {owned ? (
          <View style={[styles.ownedBadge, { backgroundColor: theme.accent }]} accessibilityLabel={`${owned} of your players`}>
            <ThemedText style={[styles.ownedText, { color: theme.onAccent }]}>{owned}</ThemedText>
          </View>
        ) : null}
      </View>
      {team.fixtures.map((f) => (
        <View key={f.gameweek} style={styles.cell}>
          {f.matches.length ? (
            f.matches.map((m, i) => <Match key={i} match={m} view={view} double={f.matches.length > 1} />)
          ) : (
            <View style={[styles.blank, { backgroundColor: theme.backgroundSelected }]} accessibilityLabel="Blank: no fixture">
              <ThemedText type="caption" themeColor="textSecondary">
                —
              </ThemedText>
            </View>
          )}
        </View>
      ))}
    </View>
  );
}

function Match({ match, view, double }: { match: PlannerMatch; view: FixtureView; double: boolean }) {
  const c = colours(match[view]);
  const label = match.home ? match.opponent.toUpperCase() : match.opponent.toLowerCase();
  return (
    <View
      style={[styles.match, double && styles.half, { backgroundColor: c.bg }]}
      accessibilityLabel={`${match.opponent} ${match.home ? 'at home' : 'away'}, difficulty ${match[view].toFixed(1)}`}>
      <ThemedText style={[styles.matchText, { color: c.fg }]}>{label}</ThemedText>
    </View>
  );
}

const styles = StyleSheet.create({
  card: { padding: Spacing.two, gap: 0 },
  row: { flexDirection: 'row', alignItems: 'center' },
  headerCell: { height: 24 },
  teamCell: { width: TEAM_WIDTH, height: CELL_HEIGHT, flexDirection: 'row', alignItems: 'center', gap: 4 },
  cell: { width: CELL_WIDTH, height: CELL_HEIGHT, padding: 2, alignItems: 'center', justifyContent: 'center', gap: 2 },
  match: { flex: 1, alignSelf: 'stretch', borderRadius: 4, alignItems: 'center', justifyContent: 'center' },
  half: { flex: 1 },
  matchText: { fontSize: 11, lineHeight: 13, fontWeight: '800' },
  blank: { flex: 1, alignSelf: 'stretch', borderRadius: 4, alignItems: 'center', justifyContent: 'center' },
  ownedBadge: { minWidth: 16, height: 16, borderRadius: 8, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 3 },
  ownedText: { fontSize: 10, lineHeight: 12, fontWeight: '900' },
  legend: { flexDirection: 'row', alignItems: 'center', gap: 6, flexWrap: 'wrap' },
  swatch: { width: 18, height: 12, borderRadius: 3 },
});
