import { useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import { ChipGroup } from '@/components/chip';
import { ErrorView } from '@/components/error-view';
import { openPlayer } from '@/components/pitch';
import { Card, Pill, Screen, SectionHeader } from '@/components/screen';
import { ThemedText } from '@/components/themed-text';
import { useTheme } from '@/hooks/use-theme';
import type { TransferTrends, TrendPlayer } from '@/lib/api';
import { compact } from '@/lib/format';
import { useRecommendation, useTeamId, useTransferTrends } from '@/lib/query';
import { modelRatesHim, priceAdvice, priceLine, rankLine, rankPhrase } from '@/lib/trends';

type Tab = 'bought' | 'sold' | 'prices';
const TABS = [
  { label: 'Most bought', value: 'bought' },
  { label: 'Most sold', value: 'sold' },
  { label: 'Price changes', value: 'prices' },
] as const;

export default function TransferTrendsScreen() {
  const [tab, setTab] = useState<Tab>('bought');
  const trends = useTransferTrends();
  const rec = useRecommendation(useTeamId());
  const owned = new Set(rec.data ? [...rec.data.lineup.starting, ...rec.data.lineup.bench].map((p) => p.player_id) : []);

  return (
    <Screen testID="trends-screen" belowHeader onRefresh={() => trends.refetch()} refreshing={trends.isRefetching}>
      <ChipGroup options={TABS} value={tab} onChange={setTab} />
      {trends.isPending ? <ThemedText themeColor="textSecondary">Reading the transfer market…</ThemedText> : null}
      {trends.isError ? <ErrorView error={trends.error} onRetry={() => trends.refetch()} /> : null}
      {trends.data ? <Body data={trends.data} tab={tab} owned={owned} /> : null}
    </Screen>
  );
}

function Body({ data, tab, owned }: { data: TransferTrends; tab: Tab; owned: Set<number> }) {
  const horizon = `${data.horizon} GW`;
  if (tab === 'bought') {
    return (
      <>
        <ThemedText type="caption" themeColor="textSecondary">
          The crowd&apos;s buys for {data.gameweek?.name ?? 'this gameweek'}, and where the model sees better value for the same money.
        </ThemedText>
        <Card style={styles.list}>
          {data.most_bought.map((p, i) => (
            <Row key={p.player_id} player={p} first={i === 0} owned={owned.has(p.player_id)} count={`+${compact(p.transfers_in)}`} horizon={horizon}>
              {p.alternative ? (
                <Pressable accessibilityRole="button" onPress={() => openPlayer(p.alternative!.player_id)}>
                  <ThemedText type="caption" themeColor="accent" style={styles.note}>
                    {`The model prefers ${p.alternative.name} (£${p.alternative.price.toFixed(1)}m): ${p.alternative.xpts_horizon.toFixed(1)} vs ${p.xpts_horizon.toFixed(1)} over ${horizon}`}
                  </ThemedText>
                </Pressable>
              ) : modelRatesHim(p) ? (
                <ThemedText type="caption" themeColor="highlight" style={styles.note}>
                  The model agrees: {rankPhrase(p)}.
                </ThemedText>
              ) : null}
            </Row>
          ))}
        </Card>
      </>
    );
  }
  if (tab === 'sold') {
    return (
      <>
        <ThemedText type="caption" themeColor="textSecondary">
          The crowd&apos;s sells, and whether the model agrees.
        </ThemedText>
        <Card style={styles.list}>
          {data.most_sold.map((p, i) => (
            <Row key={p.player_id} player={p} first={i === 0} owned={owned.has(p.player_id)} count={`−${compact(p.transfers_out)}`} horizon={horizon}>
              <ThemedText type="caption" themeColor={modelRatesHim(p) ? 'highlight' : 'textSecondary'} style={styles.note}>
                {modelRatesHim(p) ? `${rankLine(p)}: selling may be a mistake.` : rankLine(p) ?? ''}
              </ThemedText>
            </Row>
          ))}
        </Card>
      </>
    );
  }
  return (
    <>
      <ThemedText type="caption" themeColor="textSecondary">
        From FPL&apos;s own forecast. Prices change overnight, by £0.1m.
      </ThemedText>
      {(['rising', 'falling'] as const).map((side) =>
        data[side].length ? (
          <View key={side}>
            <SectionHeader title={side === 'rising' ? 'Rising' : 'Falling'} />
            <Card style={styles.list}>
              {data[side].map((p, i) => {
                const advice = priceAdvice(p, owned.has(p.player_id));
                return (
                  <Row key={p.player_id} player={p} first={i === 0} owned={owned.has(p.player_id)} count={p.price_move ? priceLine(p.price_move) : ''} horizon={horizon}>
                    {advice ? (
                      <ThemedText type="caption" themeColor={side === 'rising' ? 'highlight' : 'danger'} style={styles.note}>
                        {advice}
                      </ThemedText>
                    ) : null}
                  </Row>
                );
              })}
            </Card>
          </View>
        ) : null,
      )}
    </>
  );
}

function Row({
  player,
  first,
  owned,
  count,
  horizon,
  children,
}: {
  player: TrendPlayer;
  first: boolean;
  owned: boolean;
  count: string;
  horizon: string;
  children?: React.ReactNode;
}) {
  const theme = useTheme();
  return (
    <View testID={`trend-${player.player_id}`} style={[styles.row, !first && { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: theme.hairline }]}>
      <Pressable accessibilityRole="button" onPress={() => openPlayer(player.player_id)} style={styles.main}>
        <View style={styles.grow}>
          <View style={styles.title}>
            <ThemedText type="smallBold">{player.name}</ThemedText>
            {owned ? <Pill label="Yours" /> : null}
            {player.status !== 'a' ? <Pill label="Flagged" color="warning" soft="warningSoft" /> : null}
          </View>
          <ThemedText type="caption" themeColor="textSecondary">
            {player.team} · {player.position} · £{player.price.toFixed(1)}m · {player.ownership}% own · {player.xpts_horizon.toFixed(1)} xPts / {horizon}
          </ThemedText>
        </View>
        <ThemedText type="smallBold" style={styles.count}>
          {count}
        </ThemedText>
      </Pressable>
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  list: { paddingVertical: 4, gap: 0 },
  row: { paddingVertical: 10, gap: 4 },
  main: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  title: { flexDirection: 'row', alignItems: 'center', gap: 6, flexWrap: 'wrap' },
  count: { maxWidth: 130, textAlign: 'right' },
  note: { fontWeight: '600' },
  grow: { flex: 1 },
});
