import { ActivityIndicator, Pressable, StyleSheet, type PressableProps } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { Radius, Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';

/**
 * primary     the main action on a screen (purple; green in dark mode)
 * brand       upgrade and subscribe: FPL green with purple text
 * secondary   everything else
 * destructive irreversible actions
 */
type Variant = 'primary' | 'brand' | 'secondary' | 'destructive';

type Props = Omit<PressableProps, 'children'> & {
  title: string;
  variant?: Variant;
  loading?: boolean;
  /** Smaller, for actions inside a card or banner. */
  compact?: boolean;
};

export function Button({ title, variant = 'primary', loading = false, compact = false, disabled, style, ...rest }: Props) {
  const theme = useTheme();
  const palette = {
    primary: { background: theme.accent, color: theme.onAccent, border: theme.accent },
    brand: { background: theme.brand, color: theme.onBrand, border: theme.brand },
    secondary: { background: theme.backgroundElement, color: theme.text, border: theme.hairline },
    destructive: { background: theme.dangerSoft, color: theme.danger, border: theme.dangerSoft },
  }[variant];
  const inactive = disabled || loading;

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled: !!inactive, busy: loading }}
      disabled={inactive}
      style={(state) => [
        compact ? styles.compact : styles.base,
        {
          backgroundColor: palette.background,
          borderColor: palette.border,
          opacity: inactive ? 0.5 : 1,
          transform: [{ scale: state.pressed ? 0.98 : 1 }],
        },
        typeof style === 'function' ? style(state) : style,
      ]}
      {...rest}>
      {loading ? (
        <ActivityIndicator color={palette.color} />
      ) : (
        <ThemedText type={compact ? 'smallBold' : 'headline'} style={{ color: palette.color }}>
          {title}
        </ThemedText>
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  base: {
    minHeight: 52,
    borderRadius: Radius.md,
    borderWidth: StyleSheet.hairlineWidth,
    paddingHorizontal: Spacing.four,
    alignItems: 'center',
    justifyContent: 'center',
  },
  compact: {
    minHeight: 36,
    borderRadius: Radius.pill,
    borderWidth: StyleSheet.hairlineWidth,
    paddingHorizontal: Spacing.three,
    alignItems: 'center',
    justifyContent: 'center',
    alignSelf: 'flex-start',
  },
});
