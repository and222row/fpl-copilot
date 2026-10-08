import { ActivityIndicator, Pressable, StyleSheet, type PressableProps } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';

type Variant = 'primary' | 'secondary' | 'destructive';

type Props = Omit<PressableProps, 'children'> & {
  title: string;
  variant?: Variant;
  loading?: boolean;
};

export function Button({ title, variant = 'primary', loading = false, disabled, style, ...rest }: Props) {
  const theme = useTheme();
  const background =
    variant === 'primary' ? theme.accent : theme.backgroundElement;
  const color =
    variant === 'primary' ? theme.onAccent : variant === 'destructive' ? theme.danger : theme.text;
  const inactive = disabled || loading;

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled: !!inactive, busy: loading }}
      disabled={inactive}
      style={(state) => [
        styles.base,
        { backgroundColor: background, opacity: inactive ? 0.5 : state.pressed ? 0.8 : 1 },
        typeof style === 'function' ? style(state) : style,
      ]}
      {...rest}>
      {loading ? (
        <ActivityIndicator color={color} />
      ) : (
        <ThemedText type="smallBold" style={{ color }}>
          {title}
        </ThemedText>
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  base: {
    minHeight: 50,
    borderRadius: 12,
    paddingHorizontal: Spacing.four,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
