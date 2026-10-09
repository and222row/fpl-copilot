import { forwardRef, useState } from 'react';
import { StyleSheet, TextInput, type TextInputProps } from 'react-native';

import { Radius, Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';

/** The app's text input: a white field with a hairline that turns purple on focus. */
export const TextField = forwardRef<TextInput, TextInputProps & { large?: boolean }>(function TextField(
  { style, large = false, onFocus, onBlur, ...rest },
  ref,
) {
  const theme = useTheme();
  const [focused, setFocused] = useState(false);
  return (
    <TextInput
      ref={ref}
      placeholderTextColor={theme.textSecondary}
      onFocus={(e) => {
        setFocused(true);
        onFocus?.(e);
      }}
      onBlur={(e) => {
        setFocused(false);
        onBlur?.(e);
      }}
      style={[
        large ? styles.large : styles.field,
        {
          color: theme.text,
          backgroundColor: theme.backgroundElement,
          borderColor: focused ? theme.accent : theme.hairline,
        },
        style,
      ]}
      {...rest}
    />
  );
});

const styles = StyleSheet.create({
  field: {
    borderRadius: Radius.md,
    borderWidth: 1,
    paddingHorizontal: Spacing.three,
    paddingVertical: 12,
    fontSize: 16,
  },
  large: {
    borderRadius: Radius.md,
    borderWidth: 1.5,
    paddingHorizontal: Spacing.three,
    paddingVertical: Spacing.three,
    fontSize: 26,
    fontWeight: '700',
    letterSpacing: 3,
    textAlign: 'center',
  },
});
