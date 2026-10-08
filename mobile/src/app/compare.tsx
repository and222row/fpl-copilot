import { useLocalSearchParams } from 'expo-router';
import { StyleSheet, View } from 'react-native';

import { ErrorView } from '@/components/error-view';
import { PlayerPhoto } from '@/components/player-photo';
import { Card, Screen } from '@/components/screen';
import { ThemedText } from '@/components/themed-text';
import { Spacing } from '@/constants/theme';
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
  return (
    <Card>
      <View style={styles.row}>
        <View style={styles.label} />
        {[l, r].map((p) => (
          <View key={p.id} style={styles.head}>
            <PlayerPhoto uri={p.photo} position={p.position} size={48} />
            <ThemedText type="smallBold" numberOfLines={1}>
              {p.name}
            </ThemedText>
            <ThemedText type="small" themeColor="textSecondary">
              {p.team} · {p.position}
            </ThemedText>
          </View>
        ))}
      </View>
      {ROWS.map((row) => {
        const lv = row.value(l);
        const rv = row.value(r);
        const best = betterSide(row.better, lv, rv);
        return (
          <View key={row.label} style={styles.row}>
            <ThemedText type="small" themeColor="textSecondary" style={styles.label}>
              {row.label}
            </ThemedText>
            {([['left', lv], ['right', rv]] as const).map(([side, v]) => (
              <ThemedText
                key={side}
                type={best === side ? 'smallBold' : 'small'}
                themeColor={best === side ? 'highlight' : 'text'}
                style={styles.cell}>
                {row.format(v)}
              </ThemedText>
            ))}
          </View>
        );
      })}
    </Card>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', paddingVertical: Spacing.one, gap: Spacing.two },
  label: { flex: 1.2 },
  head: { flex: 1, alignItems: 'center', gap: Spacing.half },
  cell: { flex: 1, textAlign: 'center' },
});
