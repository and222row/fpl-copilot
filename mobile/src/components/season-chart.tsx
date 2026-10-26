import { useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { useTheme } from '@/hooks/use-theme';
import type { SeasonPoint } from '@/lib/api';

const HEIGHT = 120;

/**
 * Your points per gameweek as thin bars, with that gameweek's average as a
 * neutral tick. One series, so no legend: the caption names the tick. Tap a
 * bar to read its numbers; every bar also carries them for screen readers.
 */
export function SeasonChart({ season, current }: { season: SeasonPoint[]; current: number }) {
  const theme = useTheme();
  const [selected, setSelected] = useState(current);
  const top = Math.max(1, ...season.map((s) => Math.max(s.points, s.average ?? 0)));
  const shown = season.find((s) => s.gameweek === selected) ?? season[season.length - 1];
  const scale = (v: number) => Math.max(0, (v / top) * HEIGHT);

  return (
    <View>
      <ThemedText testID="season-readout" type="smallBold">
        {shown
          ? `GW${shown.gameweek}: ${shown.points} points${shown.average !== null ? ` · average ${shown.average}` : ''}${
              shown.overall_rank ? ` · rank ${shown.overall_rank.toLocaleString()}` : ''
            }`
          : ''}
      </ThemedText>
      <View style={[styles.plot, { borderBottomColor: theme.hairline }]}>
        {season.map((s) => {
          const active = s.gameweek === shown?.gameweek;
          return (
            <Pressable
              key={s.gameweek}
              testID={`season-bar-${s.gameweek}`}
              accessibilityRole="button"
              accessibilityLabel={`Gameweek ${s.gameweek}: ${s.points} points${s.average !== null ? `, average ${s.average}` : ''}`}
              onPress={() => setSelected(s.gameweek)}
              style={styles.slot}
              hitSlop={4}>
              <View style={[styles.bar, { height: scale(s.points), backgroundColor: theme.accent, opacity: active ? 1 : 0.55 }]} />
              {s.average !== null ? (
                <View style={[styles.tick, { bottom: scale(s.average), backgroundColor: theme.text }]} />
              ) : null}
            </Pressable>
          );
        })}
      </View>
      <View style={styles.axis}>
        <ThemedText type="caption" themeColor="textSecondary">
          GW{season[0]?.gameweek}
        </ThemedText>
        <ThemedText type="caption" themeColor="textSecondary">
          — gameweek average
        </ThemedText>
        <ThemedText type="caption" themeColor="textSecondary">
          GW{season[season.length - 1]?.gameweek}
        </ThemedText>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  plot: { height: HEIGHT, flexDirection: 'row', alignItems: 'flex-end', gap: 2, borderBottomWidth: StyleSheet.hairlineWidth, marginTop: 8 },
  slot: { flex: 1, height: HEIGHT, justifyContent: 'flex-end', alignItems: 'center' },
  bar: { width: '70%', maxWidth: 14, borderTopLeftRadius: 4, borderTopRightRadius: 4 },
  tick: { position: 'absolute', height: 2, width: '90%', maxWidth: 18, borderRadius: 1 },
  axis: { flexDirection: 'row', justifyContent: 'space-between', marginTop: 4 },
});
