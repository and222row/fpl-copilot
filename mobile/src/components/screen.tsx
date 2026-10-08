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
  /** Set on screens with a navigation header, which already clears the status bar. */
  belowHeader?: boolean;
  /** For end-to-end tests to confirm which screen is showing. */
  testID?: string;
}

export function Screen({ children, title, onRefresh, refreshing = false, footer, belowHeader = false, testID }: Props) {
  const theme = useTheme();
  return (
    <SafeAreaView
      testID={testID}
      style={[styles.safe, { backgroundColor: theme.background }]}
      // Tab screens leave the bottom to the tab bar; footers on full-screen
      // pages need it so buttons clear the home indicator.
      edges={[...(belowHeader ? [] : ['top' as const]), 'left', 'right', ...(belowHeader || footer ? ['bottom' as const] : [])]}>
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
