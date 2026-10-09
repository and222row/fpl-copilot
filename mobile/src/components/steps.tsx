import type { ReactNode } from 'react';
import { StyleSheet, View } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';

/** A numbered list with circled numbers: instructions, onboarding steps. */
export function Steps({ items }: { items: { title?: string; body: ReactNode }[] }) {
  const theme = useTheme();
  return (
    <View style={styles.list}>
      {items.map((item, i) => (
        <View key={i} style={styles.item}>
          <View style={[styles.number, { backgroundColor: theme.accent }]}>
            <ThemedText type="caption" style={{ color: theme.onAccent, fontWeight: '800' }}>
              {i + 1}
            </ThemedText>
          </View>
          <View style={styles.text}>
            {item.title ? <ThemedText type="headline">{item.title}</ThemedText> : null}
            {typeof item.body === 'string' ? (
              <ThemedText type={item.title ? 'small' : 'default'} themeColor={item.title ? 'textSecondary' : 'text'}>
                {item.body}
              </ThemedText>
            ) : (
              item.body
            )}
          </View>
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  list: { gap: Spacing.three },
  item: { flexDirection: 'row', gap: 12, alignItems: 'flex-start' },
  number: { width: 26, height: 26, borderRadius: 13, alignItems: 'center', justifyContent: 'center', marginTop: 1 },
  text: { flex: 1, gap: 2 },
});
