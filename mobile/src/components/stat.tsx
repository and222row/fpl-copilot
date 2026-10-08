import { StyleSheet, View } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';

/** A labelled number. `onHero` for use on the purple hero card. */
export function Stat({
  label,
  value,
  onHero = false,
  tone,
}: {
  label: string;
  value: string;
  onHero?: boolean;
  tone?: 'positive' | 'negative';
}) {
  const theme = useTheme();
  const valueColor = onHero
    ? theme.onHero
    : tone === 'positive'
      ? theme.highlight
      : tone === 'negative'
        ? theme.danger
        : theme.text;
  return (
    <View style={styles.stat}>
      <ThemedText type="eyebrow" style={{ color: onHero ? theme.onHeroMuted : theme.textSecondary }}>
        {label}
      </ThemedText>
      <ThemedText type="stat" style={{ color: valueColor }} numberOfLines={1} adjustsFontSizeToFit>
        {value}
      </ThemedText>
    </View>
  );
}

/** Stats in equal columns, so values line up across rows. */
export function StatRow({ children }: { children: React.ReactNode }) {
  return <View style={styles.row}>{children}</View>;
}

const styles = StyleSheet.create({
  stat: { flex: 1, gap: 2 },
  row: { flexDirection: 'row', gap: Spacing.three },
});
