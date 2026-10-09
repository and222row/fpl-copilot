import { Pressable, StyleSheet, View } from 'react-native';

import { openPlayer } from '@/components/pitch';
import { ThemedText } from '@/components/themed-text';
import { Radius, Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';

interface SwapPlayer {
  player_id: number;
  name: string;
  team: string;
  price: number;
}

/** One side of a transfer: a tinted panel, red to sell, green to buy. */
export function SwapSide({
  side,
  player,
  detail,
}: {
  side: 'SELL' | 'BUY';
  player: SwapPlayer;
  /** Extra text after team and price, e.g. "7.5 xPts". */
  detail?: string;
}) {
  const theme = useTheme();
  const [color, soft] = side === 'SELL' ? [theme.danger, theme.dangerSoft] : [theme.highlight, theme.highlightSoft];
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`${side} ${player.name}`}
      onPress={() => openPlayer(player.player_id)}
      style={({ pressed }) => [styles.side, { backgroundColor: soft }, pressed && { opacity: 0.7 }]}>
      <ThemedText type="caption" style={[styles.label, { color }]}>
        {side}
      </ThemedText>
      <ThemedText type="headline" numberOfLines={1}>
        {player.name}
      </ThemedText>
      <ThemedText type="caption" themeColor="textSecondary" numberOfLines={1}>
        {player.team} · £{player.price.toFixed(1)}m{detail ? ` · ${detail}` : ''}
      </ThemedText>
    </Pressable>
  );
}

/** A sell → buy pair. */
export function Swap({ out, into, outDetail, inDetail }: { out: SwapPlayer; into: SwapPlayer; outDetail?: string; inDetail?: string }) {
  return (
    <View style={styles.row}>
      <SwapSide side="SELL" player={out} detail={outDetail} />
      <ThemedText type="headline" themeColor="textSecondary">
        →
      </ThemedText>
      <SwapSide side="BUY" player={into} detail={inDetail} />
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', gap: Spacing.two },
  side: { flex: 1, borderRadius: Radius.md, padding: 12, gap: 2 },
  label: { fontWeight: '800', letterSpacing: 0.6 },
});
