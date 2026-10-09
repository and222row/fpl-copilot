import { Image } from 'expo-image';
import { Pressable, StyleSheet, View } from 'react-native';

import { openPlayer } from '@/components/pitch';
import { ThemedText } from '@/components/themed-text';
import { Radius, Spacing } from '@/constants/theme';
import type { Position, SquadSlot } from '@/lib/api';

const GRASS = '#0E8A43';
const GRASS_STRIPE = '#12974A';
const LINE = 'rgba(255,255,255,0.45)';
const BENCH = '#DDF3E5';
const PLATE = '#37003C';
const ORDER: Position[] = ['GKP', 'DEF', 'MID', 'FWD'];

function fixtureText(p: SquadSlot): string {
  return p.fixtures && p.fixtures.length ? p.fixtures.join(', ') : 'No fixture';
}

/** A squad drawn the way the FPL app draws it: shirts on a pitch, bench below. */
export function KitPitch({ squad }: { squad: SquadSlot[] }) {
  const starters = squad.filter((p) => p.starting);
  const bench = squad.filter((p) => !p.starting).sort((a, b) => a.slot - b.slot);
  const rows = ORDER.map((pos) => starters.filter((p) => p.position === pos)).filter((r) => r.length);

  return (
    <View testID="kit-pitch" style={styles.wrap}>
      <View style={styles.pitch} accessibilityLabel="Their starting eleven">
        <View style={StyleSheet.absoluteFill} pointerEvents="none">
          {Array.from({ length: 8 }, (_, i) => (
            <View key={i} style={[styles.stripe, { backgroundColor: i % 2 ? GRASS_STRIPE : GRASS }]} />
          ))}
          <View style={styles.box} />
          <View style={styles.goalBox} />
          <View style={styles.halfway} />
          <View style={styles.circle} />
        </View>
        {rows.map((row) => (
          <View key={row[0].position} style={styles.row}>
            {row.map((p) => (
              <Shirt key={p.player_id} player={p} />
            ))}
          </View>
        ))}
      </View>
      {bench.length ? (
        <View style={styles.bench} accessibilityLabel="Their bench">
          {bench.map((p) => (
            <View key={p.player_id} style={styles.benchSlot}>
              <ThemedText style={styles.benchLabel}>{p.position}</ThemedText>
              <Shirt player={p} />
            </View>
          ))}
        </View>
      ) : null}
    </View>
  );
}

function Shirt({ player }: { player: SquadSlot }) {
  const badge = player.is_captain ? 'C' : player.is_vice_captain ? 'V' : null;
  return (
    <Pressable
      testID={`kit-${player.player_id}`}
      accessibilityRole="button"
      accessibilityLabel={`${player.name}, ${player.team}, ${fixtureText(player)}${badge === 'C' ? ', captain' : badge === 'V' ? ', vice captain' : ''}${player.you_own ? ', you own him too' : ''}`}
      onPress={() => openPlayer(player.player_id)}
      style={({ pressed }) => [styles.token, pressed && { opacity: 0.7 }]}>
      <View>
        {player.kit ? (
          <Image source={{ uri: player.kit }} style={styles.kit} contentFit="contain" cachePolicy="memory-disk" />
        ) : (
          <View style={[styles.kit, styles.kitFallback]}>
            <ThemedText style={styles.kitFallbackText}>{player.team}</ThemedText>
          </View>
        )}
        {badge ? (
          <View style={[styles.badge, badge === 'C' ? styles.captain : styles.vice]}>
            <ThemedText style={styles.badgeText}>{badge}</ThemedText>
          </View>
        ) : null}
        {player.you_own ? <View style={styles.yours} accessibilityElementsHidden /> : null}
      </View>
      <View style={styles.name}>
        <ThemedText numberOfLines={1} style={styles.nameText}>
          {player.name}
        </ThemedText>
      </View>
      <View style={styles.fixture}>
        <ThemedText numberOfLines={1} style={styles.fixtureText}>
          {fixtureText(player)}
        </ThemedText>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  wrap: { borderRadius: Radius.lg, overflow: 'hidden' },
  pitch: { paddingTop: Spacing.four, paddingBottom: Spacing.three, gap: Spacing.three },
  stripe: { flex: 1 },
  box: { position: 'absolute', top: -2, left: '20%', right: '20%', height: '17%', borderWidth: 2, borderColor: LINE },
  goalBox: { position: 'absolute', top: -2, left: '36%', right: '36%', height: '7%', borderWidth: 2, borderColor: LINE },
  halfway: { position: 'absolute', left: 0, right: 0, top: '62%', height: 2, backgroundColor: LINE },
  circle: {
    position: 'absolute',
    top: '62%',
    left: '50%',
    width: 96,
    height: 96,
    marginLeft: -48,
    marginTop: -48,
    borderRadius: 48,
    borderWidth: 2,
    borderColor: LINE,
  },
  row: { flexDirection: 'row', justifyContent: 'space-evenly', paddingHorizontal: Spacing.one },
  token: { width: 72, alignItems: 'center' },
  kit: { width: 50, height: 50 },
  kitFallback: { borderRadius: 25, backgroundColor: '#FFFFFF', alignItems: 'center', justifyContent: 'center' },
  kitFallbackText: { fontSize: 10, fontWeight: '800', color: PLATE },
  badge: {
    position: 'absolute',
    left: -6,
    top: -2,
    width: 18,
    height: 18,
    borderRadius: 9,
    alignItems: 'center',
    justifyContent: 'center',
  },
  captain: { backgroundColor: PLATE },
  vice: { backgroundColor: '#5B2A61' },
  badgeText: { fontSize: 10, lineHeight: 12, fontWeight: '900', color: '#FFFFFF' },
  yours: {
    position: 'absolute',
    right: -4,
    top: 0,
    width: 12,
    height: 12,
    borderRadius: 6,
    backgroundColor: '#00FF87',
    borderWidth: 2,
    borderColor: '#FFFFFF',
  },
  name: {
    backgroundColor: '#FFFFFF',
    width: '100%',
    alignItems: 'center',
    borderTopLeftRadius: 4,
    borderTopRightRadius: 4,
    paddingVertical: 2,
    marginTop: 2,
  },
  nameText: { fontSize: 11, lineHeight: 14, fontWeight: '700', color: '#1A0B1F' },
  fixture: {
    backgroundColor: 'rgba(255,255,255,0.85)',
    width: '100%',
    alignItems: 'center',
    borderBottomLeftRadius: 4,
    borderBottomRightRadius: 4,
    paddingVertical: 1,
  },
  fixtureText: { fontSize: 10, lineHeight: 13, fontWeight: '600', color: '#37003C' },
  bench: { flexDirection: 'row', justifyContent: 'space-evenly', backgroundColor: BENCH, paddingVertical: Spacing.three },
  benchSlot: { alignItems: 'center', gap: 4 },
  benchLabel: { fontSize: 11, fontWeight: '800', color: PLATE },
});
