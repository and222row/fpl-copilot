import { router } from 'expo-router';
import { StyleSheet, View } from 'react-native';

import { Loading } from '@/components/loading';
import { ErrorView } from '@/components/error-view';
import { MatchScore, ResultChip } from '@/components/h2h';
import { Card, ListGroup, ListRow, Screen, SectionHeader } from '@/components/screen';
import { ThemedText } from '@/components/themed-text';
import type { H2HLeagues, LeagueSummary } from '@/lib/api';
import { useH2HLeagues, useLeagues, useTeamId } from '@/lib/query';

function movement(l: LeagueSummary): string {
  if (!l.rank) return 'Not ranked yet';
  const arrow = l.last_rank && l.last_rank !== l.rank ? (l.rank < l.last_rank ? ' ▲' : ' ▼') : '';
  return `${l.rank.toLocaleString()}${l.size ? ` of ${l.size.toLocaleString()}` : ''}${arrow}`;
}

export default function Leagues() {
  const teamId = useTeamId();
  const leagues = useLeagues(teamId);
  const h2h = useH2HLeagues(teamId);
  const mine = leagues.data?.leagues.filter((l) => l.private) ?? [];
  const fpl = leagues.data?.leagues.filter((l) => !l.private) ?? [];

  const open = (l: LeagueSummary) =>
    router.push({ pathname: '/league/[id]', params: { id: String(l.id), name: l.name } });

  return (
    <Screen
      testID="leagues-screen"
      belowHeader
      onRefresh={() => {
        leagues.refetch();
        h2h.refetch();
      }}
      refreshing={leagues.isRefetching}>
      {leagues.isPending ? <Loading /> : null}
      {leagues.isError ? <ErrorView error={leagues.error} onRetry={() => leagues.refetch()} /> : null}

      {mine.length > 0 ? (
        <>
          <SectionHeader title="Your leagues" />
          <ListGroup>
            {mine.map((l, i) => (
              <ListRow key={l.id} testID={`league-${l.id}`} title={l.name} subtitle={movement(l)} onPress={() => open(l)} last={i === mine.length - 1} />
            ))}
          </ListGroup>
        </>
      ) : leagues.isSuccess ? (
        <ThemedText themeColor="textSecondary">
          You are not in any private leagues. Join one on the FPL site with a code from a friend, and it shows up here.
        </ThemedText>
      ) : null}

      {h2h.data ? <HeadToHead data={h2h.data} /> : null}

      {fpl.length > 0 ? (
        <>
          <SectionHeader title="FPL leagues" />
          <ListGroup>
            {fpl.map((l, i) => (
              <ListRow key={l.id} title={l.name} subtitle={movement(l)} onPress={() => open(l)} last={i === fpl.length - 1} />
            ))}
          </ListGroup>
        </>
      ) : null}
    </Screen>
  );
}

function HeadToHead({ data }: { data: H2HLeagues }) {
  const cup = data.cup.matches;
  const latest = cup[cup.length - 1];
  return (
    <>
      {data.leagues.length > 0 ? (
        <>
          <SectionHeader title="Head-to-head leagues" />
          <ListGroup>
            {data.leagues.map((l, i) => (
              <ListRow
                key={l.id}
                testID={`h2h-league-${l.id}`}
                title={l.name}
                subtitle={l.rank ? `${movement(l)} · this week's match and your record` : "This week's match and your record"}
                onPress={() => router.push({ pathname: '/h2h/[id]', params: { id: String(l.id), name: l.name } })}
                last={i === data.leagues.length - 1}
              />
            ))}
          </ListGroup>
        </>
      ) : null}

      {latest ? (
        <>
          <SectionHeader title="FPL cup" />
          <Card testID="cup">
            <ThemedText type="caption" themeColor="textSecondary">
              {latest.knockout ?? 'Cup'} · Gameweek {latest.gameweek}
            </ThemedText>
            <MatchScore match={latest} />
            <View style={styles.history}>
              {cup.map((m) => (
                <ResultChip key={m.gameweek} result={m.result} />
              ))}
            </View>
          </Card>
        </>
      ) : data.cup.starts ? (
        <ThemedText type="caption" themeColor="textSecondary">
          The FPL cup starts in gameweek {data.cup.starts}.
        </ThemedText>
      ) : null}
    </>
  );
}

const styles = StyleSheet.create({
  history: { flexDirection: 'row', gap: 6, flexWrap: 'wrap' },
});
