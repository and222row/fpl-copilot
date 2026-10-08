import { useState, type ReactNode } from 'react';
import {
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  View,
  useColorScheme,
  type StyleProp,
  type ViewStyle,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ThemedText } from '@/components/themed-text';
import { CardShadow, MaxContentWidth, Radius, Spacing, type ThemeColor } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';

interface Props {
  children: ReactNode;
  title?: string;
  /** A line under the title: the trial status, a count. */
  subtitle?: ReactNode;
  onRefresh?: () => void;
  refreshing?: boolean;
  footer?: ReactNode;
  /** Set on screens with a navigation header, which already clears the status bar. */
  belowHeader?: boolean;
  /** For end-to-end tests to confirm which screen is showing. */
  testID?: string;
}

export function Screen({ children, title, subtitle, onRefresh, refreshing = false, footer, belowHeader = false, testID }: Props) {
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
          <View style={styles.header}>
            <ThemedText type="title" accessibilityRole="header">
              {title}
            </ThemedText>
            {typeof subtitle === 'string' ? (
              <ThemedText type="small" themeColor="textSecondary">
                {subtitle}
              </ThemedText>
            ) : (
              subtitle
            )}
          </View>
        ) : null}
        {children}
      </ScrollView>
      {footer ? (
        <View style={[styles.footer, { backgroundColor: theme.background, borderTopColor: theme.hairline }]}>{footer}</View>
      ) : null}
    </SafeAreaView>
  );
}

type CardVariant = 'default' | 'hero' | 'inset';

export function Card({
  children,
  variant = 'default',
  style,
  testID,
}: {
  children: ReactNode;
  variant?: CardVariant;
  style?: StyleProp<ViewStyle>;
  testID?: string;
}) {
  const theme = useTheme();
  const dark = useColorScheme() === 'dark';
  const surface: ViewStyle =
    variant === 'hero'
      ? { backgroundColor: theme.hero }
      : variant === 'inset'
        ? { backgroundColor: theme.backgroundSelected }
        : dark
          ? { backgroundColor: theme.backgroundElement, borderWidth: StyleSheet.hairlineWidth, borderColor: theme.hairline }
          : { backgroundColor: theme.backgroundElement, ...CardShadow };
  return (
    <View testID={testID} style={[styles.card, surface, style]}>
      {children}
    </View>
  );
}

/** Small uppercase label above a group of cards or rows. */
export function SectionHeader({ title, action }: { title: string; action?: ReactNode }) {
  return (
    <View style={styles.section}>
      <ThemedText type="eyebrow" themeColor="textSecondary" accessibilityRole="header">
        {title}
      </ThemedText>
      {action}
    </View>
  );
}

/** A compact pill: "Free trial · 30 days", "GW6". */
export function Pill({ label, color = 'accent', soft = 'accentSoft' }: { label: string; color?: ThemeColor; soft?: ThemeColor }) {
  const theme = useTheme();
  return (
    <View style={[styles.pill, { backgroundColor: theme[soft] }]}>
      <ThemedText type="caption" style={{ color: theme[color], fontWeight: '700' }}>
        {label}
      </ThemedText>
    </View>
  );
}

/**
 * A one-line notice that expands to its full text on tap. For things worth
 * knowing but not worth half a screen, like which squad FPL lets us see.
 */
export function Banner({
  title,
  detail,
  tone = 'warning',
  action,
  testID,
}: {
  title: string;
  detail?: string | null;
  tone?: 'warning' | 'info';
  action?: ReactNode;
  testID?: string;
}) {
  const theme = useTheme();
  const [open, setOpen] = useState(false);
  const color = tone === 'warning' ? theme.warning : theme.accent;
  const background = tone === 'warning' ? theme.warningSoft : theme.accentSoft;
  return (
    <Pressable
      testID={testID}
      accessibilityRole={detail ? 'button' : undefined}
      accessibilityState={detail ? { expanded: open } : undefined}
      accessibilityHint={detail ? 'Shows more detail' : undefined}
      onPress={detail ? () => setOpen((o) => !o) : undefined}
      style={[styles.banner, { backgroundColor: background }]}>
      <View style={styles.bannerRow}>
        <View style={[styles.bannerDot, { backgroundColor: color }]} />
        <ThemedText type="smallBold" style={[styles.grow, { color }]}>
          {title}
        </ThemedText>
        {detail ? (
          <ThemedText type="caption" style={{ color }}>
            {open ? 'Less' : 'More'}
          </ThemedText>
        ) : null}
      </View>
      {open && detail ? (
        <ThemedText type="small" style={{ color: theme.text }}>
          {detail}
        </ThemedText>
      ) : null}
      {action}
    </Pressable>
  );
}

/** A grouped list, like iOS Settings. Children are ListRows. */
export function ListGroup({ children }: { children: ReactNode }) {
  return <Card style={styles.list}>{children}</Card>;
}

export function ListRow({
  title,
  subtitle,
  value,
  onPress,
  destructive = false,
  last = false,
  testID,
}: {
  title: string;
  subtitle?: string;
  value?: string;
  onPress?: () => void;
  destructive?: boolean;
  last?: boolean;
  testID?: string;
}) {
  const theme = useTheme();
  return (
    <Pressable
      testID={testID}
      accessibilityRole={onPress ? 'button' : undefined}
      accessibilityLabel={title}
      disabled={!onPress}
      onPress={onPress}
      style={({ pressed }) => [
        styles.row,
        !last && { borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: theme.hairline },
        pressed && { backgroundColor: theme.backgroundSelected },
      ]}>
      <View style={styles.grow}>
        <ThemedText type="default" themeColor={destructive ? 'danger' : 'text'}>
          {title}
        </ThemedText>
        {subtitle ? (
          <ThemedText type="small" themeColor="textSecondary">
            {subtitle}
          </ThemedText>
        ) : null}
      </View>
      {value ? (
        <ThemedText type="small" themeColor="textSecondary">
          {value}
        </ThemedText>
      ) : null}
      {onPress && !destructive ? (
        <ThemedText type="headline" themeColor="textSecondary" style={styles.chevron}>
          ›
        </ThemedText>
      ) : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1 },
  content: {
    padding: Spacing.three,
    paddingBottom: Spacing.six,
    gap: Spacing.three,
    width: '100%',
    maxWidth: MaxContentWidth,
    alignSelf: 'center',
  },
  header: { gap: Spacing.one, marginTop: Spacing.two, marginBottom: Spacing.one },
  footer: { padding: Spacing.three, gap: Spacing.two, borderTopWidth: StyleSheet.hairlineWidth },
  card: { borderRadius: Radius.lg, padding: 18, gap: 10 },
  section: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: Spacing.two,
    marginBottom: -Spacing.two,
    paddingHorizontal: Spacing.one,
  },
  pill: { borderRadius: Radius.pill, paddingHorizontal: 10, paddingVertical: 4, alignSelf: 'flex-start' },
  banner: { borderRadius: Radius.md, paddingHorizontal: 14, paddingVertical: 12, gap: Spacing.two },
  bannerRow: { flexDirection: 'row', alignItems: 'center', gap: Spacing.two },
  bannerDot: { width: 8, height: 8, borderRadius: 4 },
  list: { padding: 0, gap: 0, overflow: 'hidden' },
  row: { flexDirection: 'row', alignItems: 'center', gap: Spacing.two, paddingHorizontal: 18, paddingVertical: 14 },
  chevron: { fontSize: 22, marginTop: -2 },
  grow: { flex: 1 },
});
