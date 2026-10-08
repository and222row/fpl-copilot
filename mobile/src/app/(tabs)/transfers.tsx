import { router } from 'expo-router';
import { useState } from 'react';
import { Alert, Pressable, StyleSheet, View } from 'react-native';

import { Button } from '@/components/button';
import { ChipGroup } from '@/components/chip';
import { errorMessage, ErrorView } from '@/components/error-view';
import { openPlayer } from '@/components/pitch';
import { Card, Screen } from '@/components/screen';
import { Stat, StatRow } from '@/components/stat';
import { ThemedText } from '@/components/themed-text';
import { VerdictBadge } from '@/components/verdict-badge';
import { Spacing } from '@/constants/theme';
import { api, type ExplainedMove, type SquadMeta, type TransferPlan, type TransferRecommendation } from '@/lib/api';
import { refreshSquadDerived, useRecommendation, useTeamId, useTransfers } from '@/lib/query';
import { money, signed } from '@/lib/squad';

const HORIZONS = [
  { label: 'Next GW', value: 1 },
  { label: '3 GW', value: 3 },
  { label: '5 GW', value: 5 },
] as const;

// The full recommendation is already computed over five gameweeks, so that
// horizon reuses it instead of running the optimiser a second time.
const SHARED_HORIZON = 5;

interface TransferData extends SquadMeta {
  recommendation: TransferRecommendation;
  alternatives: TransferPlan[];
}

export default function Transfers() {
  const teamId = useTeamId();
  const [horizon, setHorizon] = useState<number>(SHARED_HORIZON);
  const rec = useRecommendation(teamId);
  const other = useTransfers(teamId, horizon, horizon !== SHARED_HORIZON);
  const query = horizon === SHARED_HORIZON ? rec : other;

  const data: TransferData | undefined =
    horizon === SHARED_HORIZON
      ? rec.data && {
          ...rec.data,
          recommendation: rec.data.transfer,
          alternatives: rec.data.transfer_alternatives,
        }
      : other.data;

  return (
    <Screen title="Transfers" onRefresh={() => query.refetch()} refreshing={query.isRefetching}>
      <ChipGroup options={HORIZONS} value={horizon as 1 | 3 | 5} onChange={setHorizon} />
      {query.isPending ? <ThemedText themeColor="textSecondary">Running the optimiser…</ThemedText> : null}
      {query.isError ? <ErrorView error={query.error} onRetry={() => query.refetch()} /> : null}
      {data && teamId ? <TransferView data={data} teamId={teamId} /> : null}
      <Button title="Plan ahead, gameweek by gameweek" variant="secondary" onPress={() => router.push('/planner')} />
    </Screen>
  );
}

function TransferView({ data, teamId }: { data: TransferData; teamId: number }) {
  const r = data.recommendation;
  const plan = r.plan;
  const [busy, setBusy] = useState(false);

  function confirmRecord() {
    Alert.alert(
      'Record these transfers?',
      "FPL doesn't show transfers until the deadline passes. Recording them keeps your advice about the squad you actually have.",
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'I made them',
          onPress: () =>
            run(() =>
              api.recordTransfers(
                teamId,
                plan.moves.map((m) => ({ out: m.out.player_id, in: m.in.player_id })),
              ),
            ),
        },
      ],
    );
  }

  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    try {
      await fn();
      await refreshSquadDerived();
    } catch (e) {
      Alert.alert('Something went wrong', errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      {data.squad_source === 'manager_override' && data.transfers_applied?.length ? (
        <Card>
          <ThemedText type="small">
            Advice uses the {data.transfers_applied.length} transfer
            {data.transfers_applied.length === 1 ? '' : 's'} you recorded for this gameweek.
          </ThemedText>
          <Button
            title="Undo recorded transfers"
            variant="secondary"
            loading={busy}
            onPress={() => run(() => api.resetRecordedTransfers(teamId))}
          />
        </Card>
      ) : data.stale_warning ? (
        <ThemedText type="small" themeColor="warning">
          {data.stale_warning}
        </ThemedText>
      ) : null}

      <Card>
        <ThemedText type="small" themeColor="textSecondary">
          Recommendation · {r.horizon_gameweeks} GW
        </ThemedText>
        <ThemedText type="subtitle">{r.action}</ThemedText>
        <StatRow>
          <Stat label="Expected gain" value={`${signed(r.expected_net_gain)} pts`} />
          <Stat label="Confidence" value={`${Math.round(r.confidence)}%`} />
          <Stat label="Cost" value={r.hit_taken ? `−${r.hit_taken} pts` : 'Free'} />
        </StatRow>
        <StatRow>
          <Stat label="Free transfers" value={String(data.free_transfers)} />
          <Stat label="Bank now" value={money(data.bank)} />
          <Stat label="Bank after" value={money(plan.bank_after)} />
        </StatRow>
        {plan.moves.length === 0 ? (
          <ThemedText themeColor="textSecondary">{plan.note}</ThemedText>
        ) : null}
        {r.notes.map((n) => (
          <ThemedText key={n} type="small" themeColor="textSecondary">
            {n}
          </ThemedText>
        ))}
      </Card>

      {plan.moves.map((m) => (
        <MoveCard key={m.out.player_id} move={m} horizon={r.horizon_gameweeks} />
      ))}

      {plan.moves.length > 0 ? (
        <Button title="I've made these transfers" variant="secondary" loading={busy} onPress={confirmRecord} />
      ) : null}

      {data.alternatives.length > 0 ? (
        <Card>
          <ThemedText type="smallBold">Other options</ThemedText>
          {data.alternatives.map((a) => (
            <View key={`${a.transfers}-${a.hit}`} style={styles.alternative}>
              <ThemedText type="small">
                {a.transfers === 0 ? 'Roll the transfer' : `${a.transfers} transfer${a.transfers > 1 ? 's' : ''}`}
                {a.hit ? ` (−${a.hit})` : ''} · {signed(a.net_gain)} pts
              </ThemedText>
              {a.moves.map((m) => (
                <ThemedText key={m.out.player_id} type="small" themeColor="textSecondary">
                  {m.out.name} → {m.in.name}
                </ThemedText>
              ))}
            </View>
          ))}
        </Card>
      ) : null}
    </>
  );
}

function MoveCard({ move, horizon }: { move: ExplainedMove; horizon: number }) {
  const priceDiff = move.in.price - move.out.price;
  return (
    <Card>
      <PlayerLine verdict="SELL" player={move.out} />
      <PlayerLine verdict="BUY" player={move.in} />
      <StatRow>
        <Stat label="Gain" value={`${signed(move.xpts_gain)} pts / ${horizon} GW`} />
        <Stat label="Budget" value={`${priceDiff > 0 ? '−' : '+'}£${Math.abs(priceDiff).toFixed(1)}m`} />
      </StatRow>
      {move.reasons.map((reason) => (
        <ThemedText key={reason} type="small" themeColor="textSecondary">
          • {reason}
        </ThemedText>
      ))}
    </Card>
  );
}

function PlayerLine({ verdict, player }: { verdict: 'SELL' | 'BUY'; player: ExplainedMove['out'] }) {
  return (
    <Pressable accessibilityRole="button" onPress={() => openPlayer(player.player_id)} style={styles.playerLine}>
      <VerdictBadge verdict={verdict} />
      <ThemedText type="smallBold" style={styles.grow}>
        {player.name}
      </ThemedText>
      <ThemedText type="small" themeColor="textSecondary">
        {player.team} · £{player.price.toFixed(1)}m · {player.horizon_xpts.toFixed(1)} xPts
      </ThemedText>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  playerLine: { flexDirection: 'row', alignItems: 'center', gap: Spacing.two },
  alternative: { gap: Spacing.half, paddingVertical: Spacing.one },
  grow: { flex: 1 },
});
