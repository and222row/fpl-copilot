import { StyleSheet, View } from 'react-native';

import { KitPitch } from '@/components/kit-pitch';
import { Card, Pill, SectionHeader } from '@/components/screen';
import { Stat, StatRow } from '@/components/stat';
import { ThemedText } from '@/components/themed-text';
import { Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import type { LiveView } from '@/lib/api';
import { chipName, liveBadge, liveCaption } from '@/lib/live';

/**
 * A team in the gameweek being played: the points, how they compare, and the
 * squad on a pitch with each player's points. Yours on the live screen, any
 * other manager's from a league.
 */
export function LiveTeamView({ data, whose = 'Your' }: { data: LiveView; whose?: 'Your' | 'Their' }) {
  const theme = useTheme();
  const badge = liveBadge(data);
  const chip = chipName(data.chip);
  const extras = [
    data.provisional_bonus ? `includes ${data.provisional_bonus} provisional bonus` : null,
    data.transfer_cost ? `−${data.transfer_cost} for transfers` : null,
  ].filter(Boolean);

  return (
    <>
      <Card variant="hero">
        <View style={styles.badges}>
          <ThemedText type="eyebrow" style={{ color: theme.brand }}>
            {data.gameweek.name}
          </ThemedText>
          <Pill label={badge.label} color={badge.color} soft={badge.soft} />
        </View>
        <View>
          <ThemedText testID="live-points" type="title" style={{ color: theme.onHero }}>
            {data.points} pts
          </ThemedText>
          {extras.length ? (
            <ThemedText type="small" style={{ color: theme.onHeroMuted }}>
              {extras.join(' · ')}
            </ThemedText>
          ) : null}
        </View>
        <StatRow>
          <Stat onHero label="Average" value={data.gameweek.average !== null ? String(data.gameweek.average) : '—'} />
          <Stat onHero label="Highest" value={data.gameweek.highest !== null ? String(data.gameweek.highest) : '—'} />
          <Stat onHero label="Still to play" value={String(data.players_left)} />
        </StatRow>
        <ThemedText type="caption" style={{ color: theme.onHeroMuted }}>
          Season total {data.total.toLocaleString()}
          {chip ? ` · ${chip} played` : ''}
        </ThemedText>
      </Card>

      {data.armband && data.captain && data.armband !== data.captain ? (
        <Card>
          <ThemedText type="smallBold">
            {data.captain} didn&apos;t play, so {data.armband} takes the armband.
          </ThemedText>
        </Card>
      ) : null}

      {data.auto_subs.length > 0 ? (
        <>
          <SectionHeader title="Projected substitutions" />
          <Card testID="live-subs">
            {data.auto_subs.map((s) => (
              <ThemedText key={`${s.out}-${s.in}`} type="smallBold">
                {s.in} on for {s.out}
              </ThemedText>
            ))}
          </Card>
        </>
      ) : null}

      <SectionHeader title={`${whose} team`} />
      <KitPitch whose={whose} squad={data.squad} caption={liveCaption} />
    </>
  );
}

const styles = StyleSheet.create({
  badges: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: Spacing.two },
});
