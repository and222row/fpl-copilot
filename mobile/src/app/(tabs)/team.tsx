import { useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import { Segmented } from '@/components/chip';
import { ErrorView } from '@/components/error-view';
import { openPlayer, Pitch } from '@/components/pitch';
import { Card, Screen, SectionHeader } from '@/components/screen';
import { SquadBanner } from '@/components/squad-banner';
import { Stat, StatRow } from '@/components/stat';
import { ThemedText } from '@/components/themed-text';
import { VerdictBadge } from '@/components/verdict-badge';
import { useTheme } from '@/hooks/use-theme';
import type { CaptainMode, Recommendation } from '@/lib/api';
import { useCaptain, useRecommendation, useTeamId } from '@/lib/query';
import { availabilityLabel, benchLabels, verdictFor } from '@/lib/squad';

const MODES = [
  { label: 'Safe', value: 'safe' },
  { label: 'Balanced', value: 'balanced' },
  { label: 'Differential', value: 'differential' },
] as const;

export default function MyTeam() {
  const teamId = useTeamId();
  const rec = useRecommendation(teamId);

  return (
    <Screen testID="team-screen" title="My Team" onRefresh={() => rec.refetch()} refreshing={rec.isRefetching}>
      {rec.isPending ? <ThemedText themeColor="textSecondary">Picking your best XI…</ThemedText> : null}
      {rec.isError ? <ErrorView error={rec.error} onRetry={() => rec.refetch()} /> : null}
      {rec.data ? (
        <>
          <SquadBanner warning={rec.data.stale_warning} />
          <Card>
            <StatRow>
              <Stat label="Formation" value={rec.data.lineup.formation} />
              <Stat label="Projected" value={rec.data.lineup.projected_total.toFixed(1)} />
              <Stat label="Bench" value={rec.data.lineup.bench_xpts.toFixed(1)} />
            </StatRow>
          </Card>
          <Pitch rec={rec.data} />
          <Bench rec={rec.data} />
          <Captaincy teamId={teamId} />
        </>
      ) : null}
    </Screen>
  );
}

function Rank({ label, strong = false }: { label: string; strong?: boolean }) {
  const theme = useTheme();
  return (
    <View style={[styles.rank, { backgroundColor: strong ? theme.accent : theme.backgroundSelected }]}>
      <ThemedText type="caption" style={{ fontWeight: '800', color: strong ? theme.onAccent : theme.text }}>
        {label}
      </ThemedText>
    </View>
  );
}

function Bench({ rec }: { rec: Recommendation }) {
  const theme = useTheme();
  const labels = benchLabels(rec.lineup.bench);
  const chance = new Map(rec.squad_issues.map((i) => [i.player_id, i.chance_of_playing]));
  return (
    <>
      <SectionHeader title="Bench order" />
      <Card>
        <ThemedText type="small" themeColor="textSecondary">
          Ranked by expected points if called on, weighted by the chance each sub actually plays.
        </ThemedText>
        {rec.lineup.bench.map((p, i) => {
          const availability = availabilityLabel(p.status, chance.get(p.player_id));
          const verdict = verdictFor(p.player_id, rec);
          return (
            <Pressable
              key={p.player_id}
              accessibilityRole="button"
              onPress={() => openPlayer(p.player_id)}
              style={({ pressed }) => [
                styles.listRow,
                { borderTopColor: theme.hairline },
                pressed && { opacity: 0.6 },
              ]}>
              <Rank label={labels[i]} />
              <View style={styles.grow}>
                <ThemedText type="smallBold">
                  {p.name} <ThemedText type="small" themeColor="textSecondary">· {p.team}</ThemedText>
                </ThemedText>
                <ThemedText type="caption" themeColor={availability ? 'warning' : 'textSecondary'}>
                  {p.xpts.toFixed(1)} xPts · {Math.round(p.p_start * 100)}% to start
                  {availability ? ` · ${availability}` : ''}
                </ThemedText>
              </View>
              {verdict ? <VerdictBadge verdict={verdict} /> : null}
            </Pressable>
          );
        })}
      </Card>
    </>
  );
}

function Captaincy({ teamId }: { teamId: number | undefined }) {
  const theme = useTheme();
  const captain = useCaptain(teamId);
  const [mode, setMode] = useState<CaptainMode>('balanced');
  const option = captain.data?.modes[mode];

  return (
    <>
      <SectionHeader title="Captain" />
      <Card>
        <Segmented options={MODES} value={mode} onChange={setMode} />
        {captain.isError ? <ErrorView error={captain.error} onRetry={() => captain.refetch()} /> : null}
        {option?.ranking.map((c, i) => (
          <Pressable
            key={c.player_id}
            accessibilityRole="button"
            onPress={() => openPlayer(c.player_id)}
            style={({ pressed }) => [styles.listRow, { borderTopColor: theme.hairline }, pressed && { opacity: 0.6 }]}>
            <Rank label={i === 0 ? 'C' : i === 1 ? 'VC' : String(i + 1)} strong={i === 0} />
            <ThemedText type="smallBold" style={styles.grow}>
              {c.name} <ThemedText type="small" themeColor="textSecondary">· {c.team}</ThemedText>
            </ThemedText>
            <ThemedText type="headline" style={{ fontVariant: ['tabular-nums'] }}>
              {c.expected_captain_points.toFixed(1)}
            </ThemedText>
          </Pressable>
        ))}
        {option?.ranking[0] ? (
          <ThemedText type="caption" themeColor="textSecondary">
            Ranked by {option.ranking[0].rationale}. Points include the armband
            {option.confidence ? ` · ${Math.round(option.confidence.confidence)}% confidence` : ''}.
          </ThemedText>
        ) : null}
      </Card>
    </>
  );
}

const styles = StyleSheet.create({
  listRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingTop: 10,
    borderTopWidth: StyleSheet.hairlineWidth,
  },
  rank: { minWidth: 30, height: 30, borderRadius: 15, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 6 },
  grow: { flex: 1 },
});
