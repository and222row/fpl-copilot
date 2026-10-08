import { router } from 'expo-router';
import { Pressable, StyleSheet, View } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { VerdictBadge } from '@/components/verdict-badge';
import { Radius, Spacing } from '@/constants/theme';
import type { PlayerBrief, Recommendation } from '@/lib/api';
import { availabilityLabel, pitchRows, verdictFor } from '@/lib/squad';

const GRASS = '#13803F';
const GRASS_STRIPE = '#18904A';
const LINE = 'rgba(255,255,255,0.32)';
const PLATE = '#37003C';
const POINTS = '#00FF87';
const STRIPES = 8;

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
  const verdict = verdictFor(player.player_id, rec);
  const availability = availabilityLabel(player.status, chance);
  // Every starter is a START; only a different call is worth a badge.
  const badge = verdict && verdict !== 'START' ? verdict : null;
  const flag = availability ? (player.status === 'd' ? '#FFB547' : '#FF5C6C') : null;
  return (
    <Pressable
      testID={`player-token-${player.player_id}`}
      accessibilityRole="button"
      accessibilityLabel={`${player.name}, ${player.team}, ${player.xpts.toFixed(1)} expected points${
        availability ? `, ${availability}` : ''
      }${verdict ? `, ${verdict}` : ''}`}
      onPress={() => openPlayer(player.player_id)}
      style={({ pressed }) => [styles.token, pressed && { opacity: 0.7 }]}>
      <View style={styles.shirt}>
        <ThemedText style={styles.shirtText}>{player.team}</ThemedText>
        {armband ? (
          <View style={[styles.armband, armband === 'C' ? styles.captain : styles.vice]}>
            <ThemedText style={[styles.armbandText, { color: armband === 'C' ? PLATE : '#FFFFFF' }]}>{armband}</ThemedText>
          </View>
        ) : null}
        {flag ? <View style={[styles.flag, { backgroundColor: flag }]} /> : null}
      </View>
      <View style={styles.plate}>
        <ThemedText numberOfLines={1} style={styles.name}>
          {player.name}
        </ThemedText>
      </View>
      <View style={styles.points}>
        <ThemedText style={styles.pointsText}>{player.xpts.toFixed(1)}</ThemedText>
      </View>
      {availability ? (
        <ThemedText numberOfLines={1} style={[styles.availability, { color: flag ?? '#FFFFFF' }]}>
          {availability}
        </ThemedText>
      ) : null}
      {badge ? <VerdictBadge verdict={badge} solid /> : null}
    </Pressable>
  );
}

export function Pitch({ rec }: { rec: Recommendation }) {
  const chance = chanceById(rec);
  const captainId = rec.captain.pick?.player_id;
  const viceId = rec.captain.vice?.player_id;
  return (
    <View testID="pitch" style={styles.pitch} accessibilityLabel={`Starting eleven, ${rec.lineup.formation}`}>
      <View style={StyleSheet.absoluteFill} pointerEvents="none">
        {Array.from({ length: STRIPES }, (_, i) => (
          <View key={i} style={[styles.stripe, { backgroundColor: i % 2 ? GRASS_STRIPE : GRASS }]} />
        ))}
        <View style={styles.box} />
        <View style={styles.halfway} />
        <View style={styles.circle} />
      </View>
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
      <ThemedText style={styles.legend}>Expected points next gameweek · tap a player for details</ThemedText>
    </View>
  );
}

const styles = StyleSheet.create({
  pitch: {
    borderRadius: Radius.lg,
    paddingTop: Spacing.four,
    paddingBottom: Spacing.three,
    gap: Spacing.four,
    overflow: 'hidden',
  },
  stripe: { flex: 1 },
  box: {
    position: 'absolute',
    top: -2,
    left: '22%',
    right: '22%',
    height: '16%',
    borderWidth: 2,
    borderColor: LINE,
  },
  halfway: { position: 'absolute', left: 0, right: 0, top: '58%', height: 2, backgroundColor: LINE },
  circle: {
    position: 'absolute',
    top: '58%',
    left: '50%',
    width: 92,
    height: 92,
    marginLeft: -46,
    marginTop: -46,
    borderRadius: 46,
    borderWidth: 2,
    borderColor: LINE,
  },
  row: { flexDirection: 'row', justifyContent: 'space-evenly', paddingHorizontal: Spacing.one },
  token: { width: 74, alignItems: 'center' },
  shirt: {
    width: 42,
    height: 42,
    borderRadius: 21,
    backgroundColor: '#FFFFFF',
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 4,
    shadowColor: '#000',
    shadowOpacity: 0.25,
    shadowRadius: 4,
    shadowOffset: { width: 0, height: 2 },
    elevation: 3,
  },
  shirtText: { fontSize: 11, lineHeight: 13, fontWeight: '800', color: PLATE },
  armband: {
    position: 'absolute',
    right: -7,
    top: -5,
    width: 20,
    height: 20,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 2,
    borderColor: '#FFFFFF',
  },
  captain: { backgroundColor: POINTS },
  vice: { backgroundColor: PLATE },
  armbandText: { fontSize: 10, lineHeight: 12, fontWeight: '900' },
  flag: {
    position: 'absolute',
    left: -3,
    top: -3,
    width: 12,
    height: 12,
    borderRadius: 6,
    borderWidth: 2,
    borderColor: '#FFFFFF',
  },
  plate: {
    backgroundColor: PLATE,
    borderTopLeftRadius: 6,
    borderTopRightRadius: 6,
    paddingHorizontal: 4,
    paddingVertical: 2,
    width: '100%',
    alignItems: 'center',
  },
  name: { fontSize: 11, lineHeight: 14, fontWeight: '700', color: '#FFFFFF' },
  points: {
    backgroundColor: POINTS,
    borderBottomLeftRadius: 6,
    borderBottomRightRadius: 6,
    width: '100%',
    alignItems: 'center',
    paddingVertical: 1,
    marginBottom: 3,
  },
  pointsText: { fontSize: 11, lineHeight: 14, fontWeight: '800', color: PLATE, fontVariant: ['tabular-nums'] },
  availability: { fontSize: 10, lineHeight: 13, fontWeight: '700', marginBottom: 2 },
  legend: { textAlign: 'center', fontSize: 11, lineHeight: 14, color: 'rgba(255,255,255,0.75)', fontWeight: '600' },
});
