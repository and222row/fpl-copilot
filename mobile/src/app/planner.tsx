import { useState } from 'react';
import { StyleSheet, View } from 'react-native';

import { Segmented } from '@/components/chip';
import { ErrorView } from '@/components/error-view';
import { Banner, Card, Screen, SectionHeader } from '@/components/screen';
import { Stat, StatRow } from '@/components/stat';
import { Swap } from '@/components/swap';
import { ThemedText } from '@/components/themed-text';
import { Radius, Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import type { Plan, PlanStep } from '@/lib/api';
import { alternativesAt, pairByPosition, priceRisks } from '@/lib/planner';
import { usePlanner, useTeamId } from '@/lib/query';
import { signed } from '@/lib/squad';

const HORIZONS = [
  { label: '1 GW', value: 1 },
  { label: '3 GW', value: 3 },
  { label: '5 GW', value: 5 },
] as const;

export default function Planner() {
  const teamId = useTeamId();
  const [horizon, setHorizon] = useState<1 | 3 | 5>(3);
  const plan = usePlanner(teamId, horizon);

  return (
    <Screen testID="planner-screen" belowHeader onRefresh={() => plan.refetch()} refreshing={plan.isRefetching}>
      <Segmented options={HORIZONS} value={horizon} onChange={setHorizon} />
      {plan.isPending ? (
        <ThemedText themeColor="textSecondary">
          Searching transfer paths across {horizon} gameweek{horizon > 1 ? 's' : ''}. This takes a few seconds.
        </ThemedText>
      ) : null}
      {plan.isError ? <ErrorView error={plan.error} onRetry={() => plan.refetch()} /> : null}
      {plan.data ? <PlanView plan={plan.data} /> : null}
    </Screen>
  );
}

function PlanView({ plan }: { plan: Plan }) {
  const theme = useTheme();
  const best = plan.best_path;
  return (
    <>
      <Card variant="hero">
        <ThemedText testID="plan-summary" type="eyebrow" style={{ color: theme.brand }}>
          Best path · GW{plan.horizon[0]}
          {plan.horizon.length > 1 ? `–${plan.horizon[plan.horizon.length - 1]}` : ''}
        </ThemedText>
        <StatRow>
          <Stat onHero label="Projected" value={`${best.total_xpts.toFixed(1)} pts`} />
          <Stat onHero label="Transfers" value={String(best.total_transfers)} />
          <Stat onHero label="Hits" value={best.total_hits ? `−${best.total_hits}` : 'None'} />
        </StatRow>
        <StatRow>
          <Stat onHero label="Free transfers now" value={String(plan.starting_free_transfers)} />
          <Stat onHero label="Bank now" value={`£${plan.starting_bank.toFixed(1)}m`} />
        </StatRow>
        <ThemedText type="caption" style={{ color: theme.onHeroMuted }}>
          Points are net of hits and assume today&apos;s prices.
        </ThemedText>
      </Card>
      {plan.truncation_note ? <Banner title="Shorter than asked" detail={plan.truncation_note} /> : null}

      <SectionHeader title="Gameweek by gameweek" />
      {best.steps.map((s, i) => (
        <StepCard key={s.id} step={s} index={i} tree={plan.tree} last={i === best.steps.length - 1} />
      ))}
    </>
  );
}

function StepCard({ step, index, tree, last }: { step: PlanStep; index: number; tree: PlanStep[]; last: boolean }) {
  const theme = useTheme();
  const risks = priceRisks(step, index);
  const alternatives = alternativesAt(step, tree).slice(0, 2);
  const pairs = pairByPosition(step.out, step.in);
  return (
    <View style={styles.step}>
      <View style={styles.rail}>
        <View style={[styles.node, { backgroundColor: theme.accent }]}>
          <ThemedText type="caption" style={[styles.nodeText, { color: theme.onAccent }]}>
            GW{step.gameweek}
          </ThemedText>
        </View>
        {!last ? <View style={[styles.line, { backgroundColor: theme.hairline }]} /> : null}
      </View>
      <Card style={styles.grow}>
        <ThemedText type="headline" themeColor={step.hit ? 'warning' : 'text'}>
          {step.action}
        </ThemedText>

        {pairs.map(([o, i]) => (
          <Swap key={o.player_id} out={o} into={i} />
        ))}

        <StatRow>
          <Stat label="GW points" value={step.gw_xpts.toFixed(1)} />
          <Stat label="Running total" value={step.cumulative_xpts.toFixed(1)} />
        </StatRow>
        <StatRow>
          <Stat label="Bank after" value={`£${step.bank.toFixed(1)}m`} />
          <Stat label="FT next GW" value={String(step.free_transfers)} />
        </StatRow>

        {risks.map((p) => (
          <ThemedText key={p.player_id} type="small" themeColor="warning">
            {p.name} is {Math.round(p.price_change_percent)}% of the way to a price rise and may cost more by
            GW{step.gameweek}.
          </ThemedText>
        ))}

        {alternatives.length > 0 ? (
          <ThemedText type="caption" themeColor="textSecondary">
            Also considered:{' '}
            {alternatives.map((a) => `${a.step.action} (${signed(a.delta)} pts)`).join(', ')}
          </ThemedText>
        ) : null}
      </Card>
    </View>
  );
}

const styles = StyleSheet.create({
  step: { flexDirection: 'row', gap: 10 },
  rail: { alignItems: 'center', width: 48 },
  node: { borderRadius: Radius.pill, paddingHorizontal: 8, paddingVertical: 5, marginTop: Spacing.three },
  nodeText: { fontWeight: '800' },
  line: { flex: 1, width: 2, marginTop: 4, marginBottom: -Spacing.three },
  grow: { flex: 1 },
});
