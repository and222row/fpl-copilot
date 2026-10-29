import { ActivityIndicator, StyleSheet, View } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';

/**
 * A spinner while a screen loads. The optional line underneath is for the
 * slow ones (a league reading thirty squads, the optimiser), so a long wait
 * says why; quick screens pass nothing.
 */
export function Loading({ label, testID = 'loading' }: { label?: string; testID?: string }) {
  const theme = useTheme();
  return (
    <View testID={testID} style={styles.wrap} accessibilityRole="progressbar" accessibilityLabel={label ?? 'Loading'}>
      <ActivityIndicator size="large" color={theme.accent} />
      {label ? (
        <ThemedText type="small" themeColor="textSecondary" style={styles.label}>
          {label}
        </ThemedText>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { alignItems: 'center', justifyContent: 'center', gap: Spacing.three, paddingVertical: Spacing.five * 2 },
  label: { textAlign: 'center', maxWidth: 280 },
});
