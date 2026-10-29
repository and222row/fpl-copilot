import { Image } from 'expo-image';
import { router } from 'expo-router';
import { useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { CardShadow, Radius, Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';

// The photo panel's ground: FPL's headshots are cut-outs, so they sit on a colour.
const GROUND = '#37003C';

/** Open the article behind a squad warning or alert. */
export function openStory(playerId: number, alertId?: number) {
  router.push({ pathname: '/story/[id]', params: { id: String(playerId), ...(alertId ? { alert: String(alertId) } : {}) } });
}

/**
 * A squad warning or alert as a news card: the player's photo, a label,
 * the headline, a short summary and a line of context. Tap for the article.
 */
export function NewsCard({
  photo,
  initials,
  tone,
  label,
  title,
  summary,
  meta,
  onPress,
  testID,
}: {
  photo?: string | null;
  initials: string;
  tone: 'danger' | 'warning';
  label: string;
  title: string;
  summary?: string | null;
  meta?: string | null;
  onPress?: () => void;
  testID?: string;
}) {
  const theme = useTheme();
  const [failed, setFailed] = useState(false);
  return (
    <Pressable
      testID={testID}
      accessibilityRole={onPress ? 'button' : undefined}
      accessibilityLabel={`${label}. ${title}. ${summary ?? ''}`}
      disabled={!onPress}
      onPress={onPress}
      style={({ pressed }) => [styles.card, CardShadow, { backgroundColor: theme.backgroundElement }, pressed && styles.pressed]}>
      <View style={styles.media}>
        {photo && !failed ? (
          <Image
            source={{ uri: photo }}
            style={styles.photo}
            contentFit="contain"
            contentPosition="bottom"
            cachePolicy="memory-disk"
            onError={() => setFailed(true)}
            accessibilityIgnoresInvertColors
          />
        ) : (
          <ThemedText style={styles.initials}>{initials}</ThemedText>
        )}
        <View style={[styles.label, { backgroundColor: tone === 'danger' ? theme.danger : theme.warning }]}>
          <ThemedText type="caption" style={styles.labelText}>
            {label}
          </ThemedText>
        </View>
      </View>
      <View style={styles.body}>
        <ThemedText type="headline" numberOfLines={2}>
          {title}
        </ThemedText>
        {summary ? (
          <ThemedText type="small" themeColor="textSecondary" numberOfLines={2}>
            {summary}
          </ThemedText>
        ) : null}
        <View style={styles.footer}>
          <ThemedText type="caption" themeColor="textSecondary" numberOfLines={1} style={styles.grow}>
            {meta ?? ''}
          </ThemedText>
          {onPress ? (
            <ThemedText type="caption" themeColor="accent" style={styles.more}>
              Read more ›
            </ThemedText>
          ) : null}
        </View>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: { borderRadius: Radius.lg, overflow: 'hidden' },
  pressed: { opacity: 0.85 },
  media: { height: 150, backgroundColor: GROUND, alignItems: 'center', justifyContent: 'flex-end' },
  photo: { width: '100%', height: 150 },
  initials: { color: '#FFFFFF', fontSize: 40, lineHeight: 48, fontWeight: '900', marginBottom: 40 },
  label: { position: 'absolute', top: Spacing.three, left: Spacing.three, borderRadius: Radius.pill, paddingHorizontal: 10, paddingVertical: 3 },
  labelText: { color: '#FFFFFF', fontWeight: '800' },
  body: { padding: Spacing.three, gap: 4, minHeight: 120 },
  footer: { flexDirection: 'row', alignItems: 'center', gap: Spacing.two, marginTop: 'auto', paddingTop: 4 },
  more: { fontWeight: '700' },
  grow: { flex: 1 },
});
