import { useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import { ChipGroup } from '@/components/chip';
import { ErrorView } from '@/components/error-view';
import { openPlayer, Pitch } from '@/components/pitch';
import { Card, Screen } from '@/components/screen';
import { Stat, StatRow } from '@/components/stat';
import { ThemedText } from '@/components/themed-text';
import { VerdictBadge } from '@/components/verdict-badge';
import { Spacing } from '@/constants/theme';
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
    <Screen title="My Team" onRefresh={() => rec.refetch()} refreshing={rec.isRefetching}>
      {rec.isPending ? <ThemedText themeColor="textSecondary">Picking your best XI…</ThemedText> : null}
      {rec.isError ? <ErrorView error={rec.error} onRetry={() => rec.refetch()} /> : null}
      {rec.data ? (
        <>
          {rec.data.stale_warning ? (
            <ThemedText type="small" themeColor="warning">
              {rec.data.stale_warning}
            </ThemedText>
          ) : null}
          <Card>
            <StatRow>
              <Stat label="Formation" value={rec.data.lineup.formation} />
              <Stat label="Projected" value={`${rec.data.lineup.projected_total.toFixed(1)} pts`} />
              <Stat label="Bench" value={`${rec.data.lineup.bench_xpts.toFixed(1)} pts`} />
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

function Bench({ rec }: { rec: Recommendation }) {
  const labels = benchLabels(rec.lineup.bench);
  const chance = new Map(rec.squad_issues.map((i) => [i.player_id, i.chance_of_playing]));
  return (
    <Card>
      <ThemedText type="smallBold">Bench order</ThemedText>
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
            style={styles.benchRow}>
            <ThemedText type="smallBold" style={styles.benchSlot}>
              {labels[i]}
            </ThemedText>
            <View style={styles.grow}>
              <ThemedText type="small">
                {p.name} · {p.team}
              </ThemedText>
              <ThemedText type="small" themeColor={availability ? 'warning' : 'textSecondary'}>
                {p.xpts.toFixed(1)} xPts · {Math.round(p.p_start * 100)}% to start
                {availability ? ` · ${availability}` : ''}
              </ThemedText>
            </View>
            {verdict ? <VerdictBadge verdict={verdict} /> : null}
          </Pressable>
        );
      })}
    </Card>
  );
}

function Captaincy({ teamId }: { teamId: number | undefined }) {
  const captain = useCaptain(teamId);
  const [mode, setMode] = useState<CaptainMode>('balanced');
  const option = captain.data?.modes[mode];

  return (
    <Card>
      <ThemedText type="smallBold">Captain</ThemedText>
      <ChipGroup options={MODES} value={mode} onChange={setMode} />
      {captain.isError ? <ErrorView error={captain.error} onRetry={() => captain.refetch()} /> : null}
      {option?.ranking.map((c, i) => (
        <Pressable
          key={c.player_id}
          accessibilityRole="button"
          onPress={() => openPlayer(c.player_id)}
          style={styles.captainRow}>
          <ThemedText type="smallBold" style={styles.benchSlot}>
            {i === 0 ? 'C' : i === 1 ? 'VC' : String(i + 1)}
          </ThemedText>
          <ThemedText type="small" style={styles.grow}>
            {c.name} · {c.team}
          </ThemedText>
          <ThemedText type="smallBold">{c.expected_captain_points.toFixed(1)}</ThemedText>
        </Pressable>
      ))}
      {option?.ranking[0] ? (
        <ThemedText type="small" themeColor="textSecondary">
          Ranked by {option.ranking[0].rationale}. Points include the armband
          {option.confidence ? ` · ${Math.round(option.confidence.confidence)}% confidence` : ''}.
        </ThemedText>
      ) : null}
    </Card>
  );
}

const styles = StyleSheet.create({
  benchRow: { flexDirection: 'row', alignItems: 'center', gap: Spacing.two, paddingVertical: Spacing.one },
  captainRow: { flexDirection: 'row', alignItems: 'center', gap: Spacing.two, paddingVertical: Spacing.one },
  benchSlot: { width: 28 },
  grow: { flex: 1 },
});
