import { useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import { ChipGroup } from '@/components/chip';
import { ErrorView } from '@/components/error-view';
import { openPlayer } from '@/components/pitch';
import { Card, Screen } from '@/components/screen';
import { Stat, StatRow } from '@/components/stat';
import { ThemedText } from '@/components/themed-text';
import { Spacing } from '@/constants/theme';
import type { Plan, PlanPlayer, PlanStep } from '@/lib/api';
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
    <Screen belowHeader onRefresh={() => plan.refetch()} refreshing={plan.isRefetching}>
      <ChipGroup options={HORIZONS} value={horizon} onChange={setHorizon} />
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
  const best = plan.best_path;
  return (
    <>
      <Card>
        <ThemedText type="small" themeColor="textSecondary">
          Best path · GW{plan.horizon[0]}
          {plan.horizon.length > 1 ? `–${plan.horizon[plan.horizon.length - 1]}` : ''}
        </ThemedText>
        <StatRow>
          <Stat label="Projected" value={`${best.total_xpts.toFixed(1)} pts`} />
          <Stat label="Transfers" value={String(best.total_transfers)} />
          <Stat label="Hits" value={best.total_hits ? `−${best.total_hits}` : 'None'} />
        </StatRow>
        <StatRow>
          <Stat label="Free transfers now" value={String(plan.starting_free_transfers)} />
          <Stat label="Bank now" value={`£${plan.starting_bank.toFixed(1)}m`} />
        </StatRow>
        <ThemedText type="small" themeColor="textSecondary">
          Points are net of hits and assume today&apos;s prices.
        </ThemedText>
        {plan.truncation_note ? (
          <ThemedText type="small" themeColor="warning">
            {plan.truncation_note}
          </ThemedText>
        ) : null}
      </Card>

      {best.steps.map((s, i) => (
        <StepCard key={s.id} step={s} index={i} tree={plan.tree} />
      ))}
    </>
  );
}

function StepCard({ step, index, tree }: { step: PlanStep; index: number; tree: PlanStep[] }) {
  const risks = priceRisks(step, index);
  const alternatives = alternativesAt(step, tree).slice(0, 2);
  return (
    <Card>
      <View style={styles.stepHead}>
        <ThemedText type="smallBold">GW{step.gameweek}</ThemedText>
        <ThemedText type="smallBold" themeColor={step.hit ? 'warning' : 'text'}>
          {step.action}
        </ThemedText>
      </View>

      {pairByPosition(step.out, step.in).map(([o, i]) => (
        <View key={o.player_id} style={styles.move}>
          <PlayerName player={o} />
          <ThemedText type="small" themeColor="textSecondary">
            →
          </ThemedText>
          <PlayerName player={i} />
        </View>
      ))}

      <StatRow>
        <Stat label="GW points" value={step.gw_xpts.toFixed(1)} />
        <Stat label="Running total" value={step.cumulative_xpts.toFixed(1)} />
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
        <ThemedText type="small" themeColor="textSecondary">
          Also considered:{' '}
          {alternatives.map((a) => `${a.step.action} (${signed(a.delta)} pts)`).join(', ')}
        </ThemedText>
      ) : null}
    </Card>
  );
}

function PlayerName({ player }: { player: PlanPlayer }) {
  return (
    <Pressable accessibilityRole="button" onPress={() => openPlayer(player.player_id)} style={styles.player}>
      <ThemedText type="small" numberOfLines={1}>
        {player.name}
      </ThemedText>
      <ThemedText type="small" themeColor="textSecondary">
        {player.team} · £{player.price.toFixed(1)}m
      </ThemedText>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  stepHead: { flexDirection: 'row', justifyContent: 'space-between' },
  move: { flexDirection: 'row', alignItems: 'center', gap: Spacing.two },
  player: { flex: 1 },
});
