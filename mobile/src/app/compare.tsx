import { useLocalSearchParams } from 'expo-router';
import { StyleSheet, View } from 'react-native';

import { ErrorView } from '@/components/error-view';
import { PlayerPhoto } from '@/components/player-photo';
import { Card, Screen } from '@/components/screen';
import { ThemedText } from '@/components/themed-text';
import { Radius, Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import type { PlayerDetail } from '@/lib/api';
import { usePlayer } from '@/lib/query';
import { betterSide } from '@/lib/squad';

type Row = {
  label: string;
  value: (p: PlayerDetail) => number;
  format: (n: number) => string;
  /** Which way is better, or null when neither is. */
  better: 'high' | 'low' | null;
};

const avgFdr = (p: PlayerDetail) => {
  const fixtures = p.projection.gameweeks.flatMap((g) => g.fixtures);
  return fixtures.length ? fixtures.reduce((s, f) => s + f.fdr, 0) / fixtures.length : 0;
};

const ROWS: Row[] = [
  { label: 'Price', value: (p) => p.price, format: (n) => `£${n.toFixed(1)}m`, better: 'low' },
  { label: 'xPts next GW', value: (p) => p.projection.gameweeks[0]?.xpts ?? 0, format: (n) => n.toFixed(1), better: 'high' },
  { label: 'xPts 5 GW', value: (p) => p.projection.total_xpts, format: (n) => n.toFixed(1), better: 'high' },
  {
    label: 'Start chance',
    value: (p) => p.projection.gameweeks[0]?.p_start ?? 0,
    format: (n) => `${Math.round(n * 100)}%`,
    better: 'high',
  },
  { label: 'Avg difficulty', value: avgFdr, format: (n) => n.toFixed(1), better: 'low' },
  { label: 'Form', value: (p) => p.form, format: (n) => String(n), better: 'high' },
  { label: 'Points', value: (p) => p.total_points, format: (n) => String(n), better: 'high' },
  { label: 'Owned', value: (p) => p.selected_by_percent, format: (n) => `${n.toFixed(1)}%`, better: null },
];

export default function Compare() {
  const { a, b } = useLocalSearchParams<{ a: string; b: string }>();
  const left = usePlayer(Number(a));
  const right = usePlayer(Number(b));
  const error = left.error ?? right.error;

  return (
    <Screen testID="compare-screen" belowHeader>
      {error ? <ErrorView error={error} onRetry={() => (left.refetch(), right.refetch())} /> : null}
      {left.data && right.data ? <Table l={left.data} r={right.data} /> : null}
      {!error && (!left.data || !right.data) ? <ThemedText themeColor="textSecondary">Loading…</ThemedText> : null}
    </Screen>
  );
}

function Table({ l, r }: { l: PlayerDetail; r: PlayerDetail }) {
  const theme = useTheme();
  return (
    <>
      <Card variant="hero">
        <View style={styles.heads}>
          {[l, r].map((p) => (
            <View key={p.id} style={styles.head}>
              <PlayerPhoto uri={p.photo} position={p.position} size={60} />
              <ThemedText type="headline" numberOfLines={1} style={{ color: theme.onHero }}>
                {p.name}
              </ThemedText>
              <ThemedText type="caption" style={{ color: theme.onHeroMuted }}>
                {p.team} · {p.position}
              </ThemedText>
            </View>
          ))}
          <View style={[styles.vs, { backgroundColor: theme.brand }]} pointerEvents="none">
            <ThemedText type="caption" style={{ color: theme.onBrand, fontWeight: '900' }}>
              VS
            </ThemedText>
          </View>
        </View>
      </Card>
      <Card style={styles.table}>
        {ROWS.map((row, idx) => {
          const lv = row.value(l);
          const rv = row.value(r);
          const best = betterSide(row.better, lv, rv);
          return (
            <View
              key={row.label}
              style={[styles.row, idx > 0 && { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: theme.hairline }]}>
              {([['left', lv], ['right', rv]] as const).map(([side, v]) => (
                <View key={side} style={styles.cellBox}>
                  <View style={[styles.cell, best === side && { backgroundColor: theme.highlightSoft }]}>
                    <ThemedText
                      type={best === side ? 'smallBold' : 'small'}
                      themeColor={best === side ? 'highlight' : 'text'}
                      style={styles.number}>
                      {row.format(v)}
                    </ThemedText>
                  </View>
                </View>
              ))}
              <ThemedText type="caption" themeColor="textSecondary" style={styles.label}>
                {row.label}
              </ThemedText>
            </View>
          );
        })}
      </Card>
    </>
  );
}

const styles = StyleSheet.create({
  heads: { flexDirection: 'row', alignItems: 'flex-start' },
  head: { flex: 1, alignItems: 'center', gap: 4 },
  vs: {
    position: 'absolute',
    left: '50%',
    top: 22,
    marginLeft: -16,
    width: 32,
    height: 32,
    borderRadius: 16,
    alignItems: 'center',
    justifyContent: 'center',
  },
  table: { paddingVertical: 4, gap: 0 },
  row: { flexDirection: 'row', alignItems: 'center', paddingVertical: Spacing.two },
  label: { position: 'absolute', left: 0, right: 0, textAlign: 'center' },
  cellBox: { flex: 1, alignItems: 'center' },
  cell: { borderRadius: Radius.pill, paddingHorizontal: 12, paddingVertical: 3, minWidth: 64, alignItems: 'center' },
  number: { fontVariant: ['tabular-nums'] },
});
