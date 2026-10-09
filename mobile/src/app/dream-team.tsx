import { useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import { Segmented } from '@/components/chip';
import { ErrorView } from '@/components/error-view';
import { Card, Pill, Screen, SectionHeader } from '@/components/screen';
import { Stat, StatRow } from '@/components/stat';
import { ThemedText } from '@/components/themed-text';
import { useTheme } from '@/hooks/use-theme';
import type { DreamPick, DreamTeam as DreamTeamData } from '@/lib/api';
import { useDreamTeam, useRecommendation, useTeamId } from '@/lib/query';

const HORIZONS = [
  { label: 'Next GW', value: 1 },
  { label: '3 GW', value: 3 },
  { label: '5 GW', value: 5 },
] as const;

/** Squad value plus bank: what a wildcard could spend. */
export function wildcardBudget(prices: number[], bankTenths: number): number {
  const total = prices.reduce((s, p) => s + p, 0) + bankTenths / 10;
  return Math.min(120, Math.max(50, Math.round(total * 10) / 10));
}

export default function DreamTeam() {
  const teamId = useTeamId();
  const rec = useRecommendation(teamId);
  const [horizon, setHorizon] = useState<1 | 3 | 5>(3);
  const squad = rec.data ? [...rec.data.lineup.starting, ...rec.data.lineup.bench] : [];
  const budget = rec.data ? wildcardBudget(squad.map((p) => p.price), rec.data.bank) : undefined;
  const dream = useDreamTeam(budget, horizon);
  const owned = new Set(squad.map((p) => p.player_id));

  return (
    <Screen testID="dream-team-screen" belowHeader onRefresh={() => dream.refetch()} refreshing={dream.isRefetching}>
      <Segmented options={HORIZONS} value={horizon} onChange={setHorizon} />
      {dream.isPending ? <ThemedText themeColor="textSecondary">Picking the best 15 from every player…</ThemedText> : null}
      {dream.isError ? <ErrorView error={dream.error} onRetry={() => dream.refetch()} /> : null}
      {rec.isError ? <ErrorView error={rec.error} onRetry={() => rec.refetch()} /> : null}
      {dream.data ? <Body data={dream.data} owned={owned} /> : null}
    </Screen>
  );
}

function Body({ data, owned }: { data: DreamTeamData; owned: Set<number> }) {
  const theme = useTheme();
  const keep = [...data.starting, ...data.bench].filter((p) => owned.has(p.player_id)).length;
  return (
    <>
      <Card variant="hero">
        <ThemedText type="eyebrow" style={{ color: theme.brand }}>
          Wildcard draft · £{data.budget.toFixed(1)}m
        </ThemedText>
        <StatRow>
          <Stat onHero label={data.horizon > 1 ? `${data.horizon} GW total` : 'Next GW'} value={(data.horizon > 1 ? data.projected_horizon : data.projected_next_gw).toFixed(1)} />
          <Stat onHero label="Formation" value={data.formation} />
          <Stat onHero label="Left over" value={`£${data.money_left.toFixed(1)}m`} />
        </StatRow>
        <ThemedText type="small" style={{ color: theme.onHeroMuted }}>
          {keep} of these 15 are already in your team, so a wildcard would change {15 - keep}.
        </ThemedText>
      </Card>

      <SectionHeader title="Starting XI" />
      <Card style={styles.list}>
        {data.starting.map((p, i) => (
          <Row key={p.player_id} pick={p} owned={owned.has(p.player_id)} first={i === 0} />
        ))}
      </Card>
      <SectionHeader title="Bench" />
      <Card style={styles.list}>
        {data.bench.map((p, i) => (
          <Row key={p.player_id} pick={p} owned={owned.has(p.player_id)} first={i === 0} />
        ))}
      </Card>
      <ThemedText type="caption" themeColor="textSecondary">
        {data.explanation_note}
        {data.proven_optimal === false ? ' The solver ran out of time before proving nothing better exists.' : ''}
      </ThemedText>
    </>
  );
}

function Row({ pick, owned, first }: { pick: DreamPick; owned: boolean; first: boolean }) {
  const theme = useTheme();
  const [open, setOpen] = useState(false);
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ expanded: open }}
      onPress={() => setOpen((o) => !o)}
      style={[styles.row, !first && { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: theme.hairline }]}>
      <View style={styles.line}>
        <ThemedText type="caption" themeColor="textSecondary" style={styles.pos}>
          {pick.position}
        </ThemedText>
        <View style={styles.grow}>
          <ThemedText type="smallBold">
            {pick.name}
            {pick.is_captain ? ' (C)' : pick.is_vice_captain ? ' (V)' : ''}
          </ThemedText>
          <ThemedText type="caption" themeColor="textSecondary">
            {pick.team} · £{pick.price.toFixed(1)}m · {pick.gw_xpts.toFixed(1)} xPts next GW
          </ThemedText>
        </View>
        {owned ? <Pill label="Yours" color="accent" soft="accentSoft" /> : null}
      </View>
      {open
        ? pick.reasons.map((r) => (
            <ThemedText key={r} type="caption" themeColor="textSecondary" style={styles.reason}>
              • {r}
            </ThemedText>
          ))
        : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  list: { paddingVertical: 4, gap: 0 },
  row: { paddingVertical: 10, gap: 4 },
  line: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  pos: { width: 32, fontWeight: '700' },
  reason: { marginLeft: 42 },
  grow: { flex: 1 },
});
