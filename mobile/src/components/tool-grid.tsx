import { SymbolView, type SymbolViewProps } from 'expo-symbols';
import { Pressable, StyleSheet, View } from 'react-native';

import { SectionHeader } from '@/components/screen';
import { ThemedText } from '@/components/themed-text';
import { CardShadow, Radius, Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';

export interface Tool {
  testID: string;
  title: string;
  /** One short line: the tile has room for little more. */
  subtitle: string;
  /** SF Symbol on iOS, Material Symbol on Android. */
  icon: { ios: string; android: string };
  onPress: () => void;
}

/** Tools in titled groups, two tiles to a row, each with an icon. */
export function ToolGrid({ groups }: { groups: { title: string; tools: Tool[] }[] }) {
  return (
    <>
      {groups.map((g) => (
        <View key={g.title} style={styles.group}>
          <SectionHeader title={g.title} />
          <View style={styles.grid}>
            {g.tools.map((t) => (
              <ToolTile key={t.testID} tool={t} />
            ))}
          </View>
        </View>
      ))}
    </>
  );
}

function ToolTile({ tool }: { tool: Tool }) {
  const theme = useTheme();
  return (
    <Pressable
      testID={tool.testID}
      accessibilityRole="button"
      accessibilityLabel={`${tool.title}. ${tool.subtitle}`}
      onPress={tool.onPress}
      style={({ pressed }) => [
        styles.tile,
        CardShadow,
        { backgroundColor: theme.backgroundElement },
        pressed && { opacity: 0.75, transform: [{ scale: 0.98 }] },
      ]}>
      <View style={[styles.icon, { backgroundColor: theme.accentSoft }]}>
        <SymbolView
          name={tool.icon as SymbolViewProps['name']}
          size={22}
          tintColor={theme.accent}
          fallback={<ThemedText style={[styles.fallback, { color: theme.accent }]}>{tool.title[0]}</ThemedText>}
        />
      </View>
      <ThemedText type="smallBold" numberOfLines={1}>
        {tool.title}
      </ThemedText>
      <ThemedText type="caption" themeColor="textSecondary" numberOfLines={2}>
        {tool.subtitle}
      </ThemedText>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  group: { gap: Spacing.two },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.two },
  tile: { flexBasis: '48%', flexGrow: 1, borderRadius: Radius.md, padding: Spacing.three, gap: 4, minHeight: 116 },
  icon: { width: 40, height: 40, borderRadius: 12, alignItems: 'center', justifyContent: 'center', marginBottom: 4 },
  fallback: { fontSize: 18, fontWeight: '800' },
});
