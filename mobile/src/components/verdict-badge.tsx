import { StyleSheet, View } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { Radius } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import type { Verdict } from '@/lib/squad';

export function VerdictBadge({ verdict, solid = false }: { verdict: Verdict; solid?: boolean }) {
  const theme = useTheme();
  const [color, soft] =
    verdict === 'SELL'
      ? [theme.danger, theme.dangerSoft]
      : verdict === 'BUY' || verdict === 'START'
        ? [theme.highlight, theme.highlightSoft]
        : [theme.textSecondary, theme.backgroundSelected];
  return (
    <View
      style={[styles.badge, { backgroundColor: solid ? color : soft }]}
      accessibilityLabel={`Recommendation: ${verdict}`}>
      <ThemedText type="caption" style={[styles.text, { color: solid ? '#FFFFFF' : color }]}>
        {verdict}
      </ThemedText>
    </View>
  );
}

const styles = StyleSheet.create({
  badge: { borderRadius: Radius.pill, paddingHorizontal: 8, paddingVertical: 2, alignSelf: 'flex-start' },
  text: { fontSize: 10, lineHeight: 14, fontWeight: '800', letterSpacing: 0.4 },
});
