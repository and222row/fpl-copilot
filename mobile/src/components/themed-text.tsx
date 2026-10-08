import { Platform, StyleSheet, Text, type TextProps } from 'react-native';

import { Fonts, ThemeColor } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';

export type TextType =
  | 'default'
  | 'title'
  | 'subtitle'
  | 'headline'
  | 'stat'
  | 'eyebrow'
  | 'small'
  | 'smallBold'
  | 'caption'
  | 'link'
  | 'linkPrimary'
  | 'code';

export type ThemedTextProps = TextProps & {
  type?: TextType;
  themeColor?: ThemeColor;
};

export function ThemedText({ style, type = 'default', themeColor, ...rest }: ThemedTextProps) {
  const theme = useTheme();
  return <Text style={[{ color: theme[themeColor ?? 'text'] }, styles[type], style]} {...rest} />;
}

const styles = StyleSheet.create({
  /** Screen titles. */
  title: { fontSize: 34, lineHeight: 40, fontWeight: '800', letterSpacing: -0.6 },
  /** Big statements: the recommended action, a price. */
  subtitle: { fontSize: 28, lineHeight: 34, fontWeight: '800', letterSpacing: -0.5 },
  /** Card titles. */
  headline: { fontSize: 17, lineHeight: 22, fontWeight: '700', letterSpacing: -0.2 },
  /** Numbers in stat blocks. */
  stat: { fontSize: 20, lineHeight: 26, fontWeight: '800', letterSpacing: -0.3, fontVariant: ['tabular-nums'] },
  /** Small uppercase labels above values and sections. */
  eyebrow: { fontSize: 12, lineHeight: 16, fontWeight: '700', letterSpacing: 0.6, textTransform: 'uppercase' },
  default: { fontSize: 16, lineHeight: 23, fontWeight: '500' },
  small: { fontSize: 14, lineHeight: 20, fontWeight: '500' },
  smallBold: { fontSize: 14, lineHeight: 20, fontWeight: '700' },
  caption: { fontSize: 12, lineHeight: 16, fontWeight: '500' },
  link: { lineHeight: 30, fontSize: 14 },
  linkPrimary: { lineHeight: 30, fontSize: 14, color: '#3c87f7' },
  code: {
    fontFamily: Fonts.mono,
    fontWeight: Platform.select({ android: '700', default: '500' }),
    fontSize: 12,
  },
});
