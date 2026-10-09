import { router } from 'expo-router';

import { ErrorView } from '@/components/error-view';
import { ListGroup, ListRow, Screen, SectionHeader } from '@/components/screen';
import { ThemedText } from '@/components/themed-text';
import type { LeagueSummary } from '@/lib/api';
import { useLeagues, useTeamId } from '@/lib/query';

function movement(l: LeagueSummary): string {
  if (!l.rank) return 'Not ranked yet';
  const arrow = l.last_rank && l.last_rank !== l.rank ? (l.rank < l.last_rank ? ' ▲' : ' ▼') : '';
  return `${l.rank.toLocaleString()}${l.size ? ` of ${l.size.toLocaleString()}` : ''}${arrow}`;
}

export default function Leagues() {
  const teamId = useTeamId();
  const leagues = useLeagues(teamId);
  const mine = leagues.data?.leagues.filter((l) => l.private) ?? [];
  const fpl = leagues.data?.leagues.filter((l) => !l.private) ?? [];

  const open = (l: LeagueSummary) =>
    router.push({ pathname: '/league/[id]', params: { id: String(l.id), name: l.name } });

  return (
    <Screen testID="leagues-screen" belowHeader onRefresh={() => leagues.refetch()} refreshing={leagues.isRefetching}>
      {leagues.isPending ? <ThemedText themeColor="textSecondary">Loading your leagues…</ThemedText> : null}
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
