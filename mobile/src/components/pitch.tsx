import { router } from 'expo-router';
import { Pressable, StyleSheet, View } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { VerdictBadge } from '@/components/verdict-badge';
import { Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import type { PlayerBrief, Recommendation } from '@/lib/api';
import { availabilityLabel, pitchRows, verdictFor } from '@/lib/squad';

const GRASS = '#1F7A3D';
const LINE = 'rgba(255,255,255,0.35)';

export function openPlayer(playerId: number) {
  router.push({ pathname: '/player/[id]', params: { id: String(playerId) } });
}

function chanceById(rec: Recommendation): Map<number, number | null> {
  return new Map(rec.squad_issues.map((i) => [i.player_id, i.chance_of_playing]));
}

export function PlayerToken({
  player,
  rec,
  chance,
  armband,
}: {
  player: PlayerBrief;
  rec: Recommendation;
  chance: number | null | undefined;
  armband?: 'C' | 'V';
}) {
  const theme = useTheme();
  const verdict = verdictFor(player.player_id, rec);
  const availability = availabilityLabel(player.status, chance);
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`${player.name}, ${player.team}, ${player.xpts.toFixed(1)} expected points${
        availability ? `, ${availability}` : ''
      }${verdict ? `, ${verdict}` : ''}`}
      onPress={() => openPlayer(player.player_id)}
      style={styles.token}>
      <View style={[styles.shirt, { backgroundColor: theme.background }]}>
        <ThemedText type="smallBold" style={styles.shirtText}>
          {player.team}
        </ThemedText>
        {armband ? (
          <View style={[styles.armband, { backgroundColor: theme.accent }]}>
            <ThemedText style={[styles.armbandText, { color: theme.onAccent }]}>{armband}</ThemedText>
          </View>
        ) : null}
      </View>
      <View style={[styles.label, { backgroundColor: theme.background }]}>
        <ThemedText type="smallBold" numberOfLines={1} style={styles.name}>
          {player.name}
        </ThemedText>
        <ThemedText style={styles.meta} themeColor="textSecondary">
          £{player.price.toFixed(1)} · {player.xpts.toFixed(1)}
        </ThemedText>
        {availability ? (
          <ThemedText style={styles.meta} themeColor={player.status === 'd' ? 'warning' : 'danger'}>
            {availability}
          </ThemedText>
        ) : null}
      </View>
      {verdict ? <VerdictBadge verdict={verdict} /> : null}
    </Pressable>
  );
}

export function Pitch({ rec }: { rec: Recommendation }) {
  const chance = chanceById(rec);
  const captainId = rec.captain.pick?.player_id;
  const viceId = rec.captain.vice?.player_id;
  return (
    <View style={styles.pitch} accessibilityLabel={`Starting eleven, ${rec.lineup.formation}`}>
      <View style={styles.halfway} />
      {pitchRows(rec.lineup.starting).map((row) => (
        <View key={row[0].position} style={styles.row}>
          {row.map((p) => (
            <PlayerToken
              key={p.player_id}
              player={p}
              rec={rec}
              chance={chance.get(p.player_id)}
              armband={p.player_id === captainId ? 'C' : p.player_id === viceId ? 'V' : undefined}
            />
          ))}
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  pitch: {
    backgroundColor: GRASS,
    borderRadius: 16,
    paddingVertical: Spacing.three,
    gap: Spacing.three,
    borderWidth: 2,
    borderColor: LINE,
    overflow: 'hidden',
  },
  halfway: { position: 'absolute', left: 0, right: 0, top: '50%', height: 2, backgroundColor: LINE },
  row: { flexDirection: 'row', justifyContent: 'space-evenly' },
  token: { width: 68, alignItems: 'center', gap: 2 },
  shirt: {
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: 'center',
    justifyContent: 'center',
  },
  shirtText: { fontSize: 10, lineHeight: 12 },
  armband: {
    position: 'absolute',
    right: -6,
    top: -4,
    width: 18,
    height: 18,
    borderRadius: 9,
    alignItems: 'center',
    justifyContent: 'center',
  },
  armbandText: { fontSize: 10, lineHeight: 12, fontWeight: '700' },
  label: { borderRadius: 6, paddingHorizontal: 4, alignItems: 'center', width: '100%' },
  name: { fontSize: 11, lineHeight: 14 },
  meta: { fontSize: 10, lineHeight: 13 },
});
