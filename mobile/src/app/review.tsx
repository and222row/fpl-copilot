import { router } from 'expo-router';
import { Pressable, StyleSheet, View } from 'react-native';

import { Loading } from '@/components/loading';
import { ErrorView } from '@/components/error-view';
import { openPlayer } from '@/components/pitch';
import { Card, Screen, SectionHeader } from '@/components/screen';
import { SeasonChart } from '@/components/season-chart';
import { Stat, StatRow } from '@/components/stat';
import { ThemedText } from '@/components/themed-text';
import { useTheme } from '@/hooks/use-theme';
import type { GameweekReview, ReviewPlayer } from '@/lib/api';
import { chipName } from '@/lib/live';
import { useMe, useReview, useTeamId } from '@/lib/query';
import { adviceLine, rankMove } from '@/lib/review';
import { reviewCard } from '@/lib/share-card';
import { ShareCardButton } from '@/components/share-card';

export default function Review() {
  const review = useReview(useTeamId());
  const team = useMe(true).data?.fpl_accounts[0]?.team_name ?? '';
  return (
    <Screen testID="review-screen" belowHeader onRefresh={() => review.refetch()} refreshing={review.isRefetching}>
      {review.isPending ? <Loading /> : null}
      {review.isError ? <ErrorView error={review.error} onRetry={() => review.refetch()} /> : null}
      {review.data ? (
        <>
          <Body data={review.data} />
          <ShareCardButton card={reviewCard(review.data, team)} title="Share your gameweek" />
        </>
      ) : null}
    </Screen>
  );
}

function Body({ data }: { data: GameweekReview }) {
  const theme = useTheme();
  const move = rankMove(data.previous_overall_rank, data.overall_rank);
  const average = data.gameweek.average;
  const chip = chipName(data.chip);
  const cap = data.captain;

  return (
    <>
      <Card variant="hero">
        <ThemedText type="eyebrow" style={{ color: theme.brand }}>
          {data.gameweek.name} review
        </ThemedText>
        <ThemedText testID="review-points" type="title" style={{ color: theme.onHero }}>
          {data.points} pts
        </ThemedText>
        <ThemedText type="small" style={{ color: theme.onHeroMuted }}>
          {average !== null ? (data.points >= average ? `${data.points - average} above` : `${average - data.points} below`) + ' the average' : ''}
          {data.transfer_cost ? ` · −${data.transfer_cost} for transfers` : ''}
          {chip ? ` · ${chip}` : ''}
        </ThemedText>
        <StatRow>
          <Stat onHero label="Average" value={average !== null ? String(average) : '—'} />
          <Stat onHero label="Highest" value={data.gameweek.highest !== null ? String(data.gameweek.highest) : '—'} />
          <Stat onHero label="GW rank" value={data.gameweek_rank ? data.gameweek_rank.toLocaleString() : '—'} />
        </StatRow>
        {data.overall_rank ? (
          <ThemedText type="small" style={{ color: theme.onHero }}>
            Overall rank {data.overall_rank.toLocaleString()}
            {move ? (
              // The theme's danger red is too dark to read on the purple hero.
              <ThemedText type="smallBold" style={{ color: move.up ? theme.brand : '#FF8FA3' }}>
                {`  ${move.text}`}
              </ThemedText>
            ) : null}
          </ThemedText>
        ) : null}
        {!data.finished ? (
          <ThemedText type="caption" style={{ color: theme.onHeroMuted }}>
            Bonus is still provisional.
          </ThemedText>
        ) : null}
      </Card>

      {cap.pick ? (
        <>
          <SectionHeader title="Your captain" />
          <Card testID="review-captain">
            <ThemedText type="headline">
              {cap.pick.name} {cap.pick.contribution} pts
            </ThemedText>
            <ThemedText type="small" themeColor="textSecondary">
              {cap.missed > 0 && cap.best
                ? `${cap.best.name} scored ${cap.best.points}: with the armband he would have given you ${cap.missed} more.`
                : 'The best captain your team had. Nothing left on the table.'}
            </ThemedText>
          </Card>
        </>
      ) : null}

      <SectionHeader title="Best and worst" />
      <Card style={styles.list}>
        {data.best.map((p, i) => (
          <PlayerLine key={`b${p.player_id}`} player={p} first={i === 0} tone="highlight" />
        ))}
        {data.worst.map((p) => (
          <PlayerLine key={`w${p.player_id}`} player={p} first={false} tone="danger" />
        ))}
      </Card>
      {data.bench_points > 0 ? (
        <ThemedText type="caption" themeColor="textSecondary">
          {data.bench_points} points stayed on your bench
          {data.bench[0] && data.bench[0].points > 0 ? `, ${data.bench[0].points} of them from ${data.bench[0].name}` : ''}.
        </ThemedText>
      ) : null}

      {data.advice.length > 0 ? (
        <>
          <SectionHeader title="How the advice did" />
          <Card testID="review-advice">
            {data.advice.map((a) => (
              <ThemedText key={a.kind} type="small">
                {adviceLine(a)}
              </ThemedText>
            ))}
          </Card>
        </>
      ) : null}

      {data.leagues.length > 0 ? (
        <>
          <SectionHeader title="Your leagues" />
          <Card style={styles.list}>
            {data.leagues.map((l, i) => {
              const m = rankMove(l.last_rank, l.rank);
              return (
                <Pressable
                  key={l.id}
                  accessibilityRole="button"
                  onPress={() => router.push({ pathname: '/league/[id]', params: { id: String(l.id), name: l.name } })}
                  style={[styles.row, i > 0 && { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: theme.hairline }]}>
                  <ThemedText type="smallBold" style={styles.grow} numberOfLines={1}>
                    {l.name}
                  </ThemedText>
                  <ThemedText type="smallBold">
                    {l.rank ? `${l.rank}${l.size ? ` of ${l.size}` : ''}` : '—'}
                  </ThemedText>
                  {m ? (
                    <ThemedText type="caption" style={{ color: m.up ? theme.highlight : theme.danger }}>
                      {m.text}
                    </ThemedText>
                  ) : null}
                </Pressable>
              );
            })}
          </Card>
        </>
      ) : null}

      {data.season.length > 1 ? (
        <>
          <SectionHeader title="Your season" />
          <Card testID="review-season">
            <SeasonChart season={data.season} current={data.gameweek.id} />
          </Card>
        </>
      ) : null}
    </>
  );
}

function PlayerLine({ player, first, tone }: { player: ReviewPlayer; first: boolean; tone: 'highlight' | 'danger' }) {
  const theme = useTheme();
  return (
    <Pressable
      accessibilityRole="button"
      onPress={() => openPlayer(player.player_id)}
      style={[styles.row, !first && { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: theme.hairline }]}>
      <View style={[styles.dot, { backgroundColor: theme[tone] }]} />
      <View style={styles.grow}>
        <ThemedText type="smallBold">
          {player.name}
          {player.multiplier > 1 ? ' (C)' : ''}
        </ThemedText>
        <ThemedText type="caption" themeColor="textSecondary">
          {player.team} · {player.position} · {player.minutes} min
        </ThemedText>
      </View>
      <ThemedText type="headline">{player.contribution}</ThemedText>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  list: { paddingVertical: 4, gap: 0 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 10 },
  dot: { width: 8, height: 8, borderRadius: 4 },
  grow: { flex: 1 },
});
