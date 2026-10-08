import { StyleSheet, View } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { useTheme } from '@/hooks/use-theme';
import type { Verdict } from '@/lib/squad';

export function VerdictBadge({ verdict }: { verdict: Verdict }) {
  const theme = useTheme();
  const color =
    verdict === 'SELL' ? theme.danger : verdict === 'BUY' || verdict === 'START' ? theme.highlight : theme.textSecondary;
  return (
    <View style={[styles.badge, { borderColor: color }]} accessibilityLabel={`Recommendation: ${verdict}`}>
      <ThemedText type="smallBold" style={[styles.text, { color }]}>
        {verdict}
      </ThemedText>
    </View>
  );
}

const styles = StyleSheet.create({
  badge: { borderWidth: 1, borderRadius: 6, paddingHorizontal: 5, alignSelf: 'flex-start' },
  text: { fontSize: 10, lineHeight: 15 },
});
