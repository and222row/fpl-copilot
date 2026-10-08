import type { ReactNode } from 'react';
import { RefreshControl, ScrollView, StyleSheet, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ThemedText } from '@/components/themed-text';
import { MaxContentWidth, Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';

interface Props {
  children: ReactNode;
  title?: string;
  onRefresh?: () => void;
  refreshing?: boolean;
  footer?: ReactNode;
}

export function Screen({ children, title, onRefresh, refreshing = false, footer }: Props) {
  const theme = useTheme();
  return (
    <SafeAreaView style={[styles.safe, { backgroundColor: theme.background }]} edges={['top', 'left', 'right']}>
      <ScrollView
        contentContainerStyle={styles.content}
        keyboardShouldPersistTaps="handled"
        refreshControl={
          onRefresh ? <RefreshControl refreshing={refreshing} onRefresh={onRefresh} /> : undefined
        }>
        {title ? (
          <ThemedText type="subtitle" accessibilityRole="header" style={styles.title}>
            {title}
          </ThemedText>
        ) : null}
        {children}
      </ScrollView>
      {footer ? <View style={styles.footer}>{footer}</View> : null}
    </SafeAreaView>
  );
}

export function Card({ children }: { children: ReactNode }) {
  const theme = useTheme();
  return <View style={[styles.card, { backgroundColor: theme.backgroundElement }]}>{children}</View>;
}

const styles = StyleSheet.create({
  safe: { flex: 1 },
  content: {
    padding: Spacing.three,
    gap: Spacing.three,
    width: '100%',
    maxWidth: MaxContentWidth,
    alignSelf: 'center',
  },
  title: { marginBottom: Spacing.one },
  footer: { padding: Spacing.three, gap: Spacing.two },
  card: { borderRadius: 16, padding: Spacing.three, gap: Spacing.two },
});
