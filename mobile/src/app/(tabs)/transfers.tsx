import { router } from 'expo-router';
import { useState } from 'react';
import { Alert, StyleSheet, View } from 'react-native';

import { Button } from '@/components/button';
import { Segmented } from '@/components/chip';
import { errorMessage, ErrorView } from '@/components/error-view';
import { Banner, Card, ListGroup, ListRow, Screen, SectionHeader } from '@/components/screen';
import { SquadBanner } from '@/components/squad-banner';
import { Stat, StatRow } from '@/components/stat';
import { Swap } from '@/components/swap';
import { ThemedText } from '@/components/themed-text';
import { useTheme } from '@/hooks/use-theme';
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
    <Screen testID="transfers-screen" title="Transfers" onRefresh={() => query.refetch()} refreshing={query.isRefetching}>
      <Segmented options={HORIZONS} value={horizon as 1 | 3 | 5} onChange={setHorizon} />
      {query.isPending ? <ThemedText themeColor="textSecondary">Running the optimiser…</ThemedText> : null}
      {query.isError ? <ErrorView error={query.error} onRetry={() => query.refetch()} /> : null}
      {data && teamId ? <TransferView data={data} teamId={teamId} /> : null}
      <ListGroup>
        <ListRow
          title="Plan ahead, gameweek by gameweek"
          subtitle="When to use transfers and whether a hit pays off"
          onPress={() => router.push('/planner')}
          last
        />
      </ListGroup>
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
        <Banner
          tone="info"
          title={`Using the ${data.transfers_applied.length} transfer${data.transfers_applied.length === 1 ? '' : 's'} you recorded`}
          action={
            <Button
              title="Undo recorded transfers"
              variant="secondary"
              compact
              loading={busy}
              onPress={() => run(() => api.resetRecordedTransfers(teamId))}
            />
          }
        />
      ) : (
        <SquadBanner warning={data.stale_warning} />
      )}

      <Card>
        <ThemedText type="eyebrow" themeColor="textSecondary">
          Recommendation · {r.horizon_gameweeks} GW
        </ThemedText>
        <ThemedText testID="transfer-action" type="subtitle">
          {r.action}
        </ThemedText>
        <StatRow>
          <Stat label="Expected gain" value={`${signed(r.expected_net_gain)}`} tone="positive" />
          <Stat label="Confidence" value={`${Math.round(r.confidence)}%`} />
          <Stat label="Cost" value={r.hit_taken ? `−${r.hit_taken}` : 'Free'} tone={r.hit_taken ? 'negative' : undefined} />
        </StatRow>
        <StatRow>
          <Stat label="Free transfers" value={String(data.free_transfers)} />
          <Stat label="Bank now" value={money(data.bank)} />
          <Stat label="Bank after" value={money(plan.bank_after)} />
        </StatRow>
        {plan.moves.length === 0 ? <ThemedText themeColor="textSecondary">{plan.note}</ThemedText> : null}
        {r.notes.map((n) => (
          <ThemedText key={n} type="small" themeColor="textSecondary">
            {n}
          </ThemedText>
        ))}
      </Card>

      {plan.moves.length > 0 ? <SectionHeader title={`The ${plan.moves.length === 1 ? 'move' : 'moves'}`} /> : null}
      {plan.moves.map((m) => (
        <MoveCard key={m.out.player_id} move={m} horizon={r.horizon_gameweeks} />
      ))}

      {plan.moves.length > 0 ? (
        <Button title="I've made these transfers" variant="secondary" loading={busy} onPress={confirmRecord} />
      ) : null}

      {data.alternatives.length > 0 ? (
        <>
          <SectionHeader title="Other options" />
          <ListGroup>
            {data.alternatives.map((a, i) => (
              <ListRow
                key={`${a.transfers}-${a.hit}`}
                title={`${a.transfers === 0 ? 'Roll the transfer' : `${a.transfers} transfer${a.transfers > 1 ? 's' : ''}`}${
                  a.hit ? ` (−${a.hit})` : ''
                }`}
                subtitle={a.moves.map((m) => `${m.out.name} → ${m.in.name}`).join(', ') || undefined}
                value={`${signed(a.net_gain)} pts`}
                last={i === data.alternatives.length - 1}
              />
            ))}
          </ListGroup>
        </>
      ) : null}
    </>
  );
}

function MoveCard({ move, horizon }: { move: ExplainedMove; horizon: number }) {
  const theme = useTheme();
  const priceDiff = move.in.price - move.out.price;
  return (
    <Card>
      <Swap
        out={move.out}
        into={move.in}
        outDetail={`${move.out.horizon_xpts.toFixed(1)} xPts`}
        inDetail={`${move.in.horizon_xpts.toFixed(1)} xPts`}
      />
      <StatRow>
        <Stat label={`Gain · ${horizon} GW`} value={`${signed(move.xpts_gain)} pts`} tone="positive" />
        <Stat label="Budget" value={`${priceDiff > 0 ? '−' : '+'}£${Math.abs(priceDiff).toFixed(1)}m`} />
      </StatRow>
      <View style={styles.reasons}>
        {move.reasons.map((reason) => (
          <View key={reason} style={styles.reason}>
            <View style={[styles.bullet, { backgroundColor: theme.highlight }]} />
            <ThemedText type="small" themeColor="textSecondary" style={styles.grow}>
              {reason}
            </ThemedText>
          </View>
        ))}
      </View>
    </Card>
  );
}

const styles = StyleSheet.create({
  reasons: { gap: 6 },
  reason: { flexDirection: 'row', gap: 8, alignItems: 'flex-start' },
  bullet: { width: 6, height: 6, borderRadius: 3, marginTop: 7 },
  grow: { flex: 1 },
});
