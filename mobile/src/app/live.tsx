import { router } from 'expo-router';

import { Loading } from '@/components/loading';
import { ErrorView } from '@/components/error-view';
import { LiveTeamView } from '@/components/live-team';
import { ListGroup, ListRow, Screen, SectionHeader } from '@/components/screen';
import { ThemedText } from '@/components/themed-text';
import { useLeagues, useLive, useMe, useTeamId } from '@/lib/query';
import { liveCard } from '@/lib/share-card';
import { ShareCardButton } from '@/components/share-card';

export default function Live() {
  const teamId = useTeamId();
  const live = useLive(teamId);
  const leagues = useLeagues(teamId);
  const team = useMe(true).data?.fpl_accounts[0]?.team_name ?? '';
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
      {live.isPending ? <Loading /> : null}
      {live.isError ? <ErrorView error={live.error} onRetry={() => live.refetch()} /> : null}
      {live.data ? <LiveTeamView data={live.data} /> : null}
      {live.data ? <ShareCardButton card={liveCard(live.data, team)} title="Share your score" /> : null}
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
