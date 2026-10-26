import { router } from 'expo-router';
import { StyleSheet, View } from 'react-native';

import { ErrorView } from '@/components/error-view';
import { KitPitch } from '@/components/kit-pitch';
import { Card, ListGroup, ListRow, Pill, Screen, SectionHeader } from '@/components/screen';
import { Stat, StatRow } from '@/components/stat';
import { ThemedText } from '@/components/themed-text';
import { Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import type { LiveView } from '@/lib/api';
import { chipName, liveBadge, liveCaption } from '@/lib/live';
import { useLeagues, useLive, useTeamId } from '@/lib/query';

export default function Live() {
  const teamId = useTeamId();
  const live = useLive(teamId);
  const leagues = useLeagues(teamId);
  const mine = leagues.data?.leagues.filter((l) => l.private) ?? [];

  return (
    <Screen
      testID="live-screen"
      belowHeader
      onRefresh={() => {
        live.refetch();
        leagues.refetch();
      }}
      refreshing={live.isRefetching}>
      {live.isPending ? <ThemedText themeColor="textSecondary">Reading the live scores…</ThemedText> : null}
      {live.isError ? <ErrorView error={live.error} onRetry={() => live.refetch()} /> : null}
      {live.data ? <LiveBody data={live.data} /> : null}
      {live.data?.finished ? (
        <ListGroup>
          <ListRow
            testID="live-review"
            title="Your gameweek review"
            subtitle="Best and worst picks, your captain, how the advice did"
            onPress={() => router.push('/review')}
            last
          />
        </ListGroup>
      ) : null}

      {mine.length > 0 ? (
        <>
          <SectionHeader title="Live mini-leagues" />
          <ListGroup>
            {mine.map((l, i) => (
              <ListRow
                key={l.id}
                testID={`live-league-${l.id}`}
                title={l.name}
                subtitle="The table as it stands right now"
                onPress={() => router.push({ pathname: '/live-league/[id]', params: { id: String(l.id), name: l.name } })}
                last={i === mine.length - 1}
              />
            ))}
          </ListGroup>
        </>
      ) : null}

      <ThemedText type="caption" themeColor="textSecondary">
        Bonus is provisional until FPL confirms it, about an hour after full time. Automatic substitutions and the
        vice-captain are projected from who has played; FPL makes them as matches finish. Updates every minute while
        a match is on.
      </ThemedText>
    </Screen>
  );
}

function LiveBody({ data }: { data: LiveView }) {
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

      <SectionHeader title="Your team" />
      <KitPitch whose="Your" squad={data.squad} caption={liveCaption} />
    </>
  );
}

const styles = StyleSheet.create({
  badges: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: Spacing.two },
});
