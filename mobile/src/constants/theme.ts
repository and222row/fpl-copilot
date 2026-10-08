/**
 * Design tokens. FPL's own palette: deep purple, neon green, magenta. Light
 * mode puts white cards on a soft lilac-grey; dark mode is near-black purple.
 */

import { Platform, type ViewStyle } from 'react-native';

const brand = {
  purple: '#37003C',
  purpleDeep: '#28002C',
  green: '#00FF87',
  cyan: '#04F5FF',
  magenta: '#E90052',
};

export const Colors = {
  light: {
    text: '#1A0B1F',
    textSecondary: '#6E6678',
    background: '#F3F1F7',
    /** Cards and grouped surfaces. */
    backgroundElement: '#FFFFFF',
    /** Inset areas: segmented controls, inputs, selected rows. */
    backgroundSelected: '#ECE8F2',
    hairline: '#E6E1EC',
    accent: brand.purple,
    onAccent: '#FFFFFF',
    accentSoft: '#F1E6F3',
    brand: brand.green,
    onBrand: brand.purple,
    highlight: '#00A35C',
    highlightSoft: '#E1F8EC',
    danger: '#D7263D',
    dangerSoft: '#FCE7EA',
    warning: '#B26200',
    warningSoft: '#FFF2DE',
    hero: brand.purple,
    onHero: '#FFFFFF',
    onHeroMuted: 'rgba(255,255,255,0.68)',
  },
  dark: {
    text: '#F6F2F8',
    textSecondary: '#A79FB0',
    background: '#0D0811',
    backgroundElement: '#1A1320',
    backgroundSelected: '#271E2F',
    hairline: '#2E2537',
    accent: brand.green,
    onAccent: '#1A0B1F',
    accentSoft: '#173326',
    brand: brand.green,
    onBrand: brand.purple,
    highlight: brand.green,
    highlightSoft: '#123326',
    danger: '#FF5C6C',
    dangerSoft: '#3A1520',
    warning: '#FFB547',
    warningSoft: '#3A2A12',
    hero: '#2A0030',
    onHero: '#FFFFFF',
    onHeroMuted: 'rgba(255,255,255,0.68)',
  },
} as const;

export type ThemeColor = keyof typeof Colors.light & keyof typeof Colors.dark;
export type Theme = (typeof Colors)['light' | 'dark'];

export const Fonts = Platform.select({
  ios: {
    /** iOS `UIFontDescriptorSystemDesignDefault` */
    sans: 'system-ui',
    /** iOS `UIFontDescriptorSystemDesignSerif` */
    serif: 'ui-serif',
    /** iOS `UIFontDescriptorSystemDesignRounded` */
    rounded: 'ui-rounded',
    /** iOS `UIFontDescriptorSystemDesignMonospaced` */
    mono: 'ui-monospace',
  },
  default: {
    sans: 'normal',
    serif: 'serif',
    rounded: 'normal',
    mono: 'monospace',
  },
  web: {
    sans: 'system-ui, sans-serif',
    serif: 'Georgia, serif',
    rounded: 'system-ui, sans-serif',
    mono: 'ui-monospace, monospace',
  },
});

export const Spacing = {
  half: 2,
  one: 4,
  two: 8,
  three: 16,
  four: 24,
  five: 32,
  six: 64,
} as const;

export const Radius = {
  sm: 8,
  md: 14,
  lg: 20,
  pill: 999,
} as const;

/** A soft lift for cards on the light background; dark mode uses a hairline instead. */
export const CardShadow: ViewStyle = Platform.select({
  ios: { shadowColor: '#1A0B1F', shadowOpacity: 0.06, shadowRadius: 14, shadowOffset: { width: 0, height: 4 } },
  android: { elevation: 2 },
  default: {},
});

export const BottomTabInset = Platform.select({ ios: 50, android: 80 }) ?? 0;
export const MaxContentWidth = 800;
