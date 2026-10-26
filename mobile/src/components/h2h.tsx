import { StyleSheet, View } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import type { H2HMatch } from '@/lib/api';

export function resultWord(r: 'W' | 'D' | 'L'): string {
  return r === 'W' ? 'Won' : r === 'D' ? 'Drawn' : 'Lost';
}

/** You against them, side by side. */
export function MatchScore({ match, onHero = false }: { match: H2HMatch; onHero?: boolean }) {
  const theme = useTheme();
  const ink = onHero ? theme.onHero : theme.text;
  const muted = onHero ? theme.onHeroMuted : theme.textSecondary;
  return (
    <View style={styles.score}>
      <View style={styles.side}>
        <ThemedText type="caption" style={{ color: muted }}>
          You
        </ThemedText>
        <ThemedText type="title" style={[styles.num, { color: ink }]}>
          {match.your_points}
        </ThemedText>
      </View>
      <ThemedText type="headline" style={{ color: muted }}>
        –
      </ThemedText>
      <View style={[styles.side, styles.right]}>
        <ThemedText type="caption" style={{ color: muted }} numberOfLines={1}>
          {match.opponent?.team_name ?? 'Bye'}
        </ThemedText>
        <ThemedText type="title" style={[styles.num, { color: ink }]}>
          {match.their_points}
        </ThemedText>
      </View>
    </View>
  );
}

/** W, D or L in a ring: green, grey or red. */
export function ResultChip({ result }: { result: H2HMatch['result'] }) {
  const theme = useTheme();
  const tone = result === 'W' ? 'highlight' : result === 'L' ? 'danger' : 'textSecondary';
  return (
    <View style={[styles.chip, { borderColor: theme[tone] }]} accessibilityLabel={result ? resultWord(result) : 'Not played'}>
      <ThemedText type="caption" style={{ color: theme[tone], fontWeight: '800' }}>
        {result ?? '·'}
      </ThemedText>
    </View>
  );
}

const styles = StyleSheet.create({
  score: { flexDirection: 'row', alignItems: 'center', gap: Spacing.three },
  side: { flex: 1 },
  right: { alignItems: 'flex-end' },
  num: { fontVariant: ['tabular-nums'] },
  chip: { width: 26, height: 26, borderRadius: 13, borderWidth: 1.5, alignItems: 'center', justifyContent: 'center' },
});
