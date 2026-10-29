import { Stack, useLocalSearchParams } from 'expo-router';

import { ErrorView } from '@/components/error-view';
import { LiveTeamView } from '@/components/live-team';
import { Loading } from '@/components/loading';
import { Screen } from '@/components/screen';
import { ThemedText } from '@/components/themed-text';
import { useLiveManager, useTeamId } from '@/lib/query';

/** Another manager's team this gameweek on a pitch, scored live: from a head-to-head league. */
export default function ManagerScreen() {
  const { id, name } = useLocalSearchParams<{ id: string; name?: string }>();
  const team = useLiveManager(useTeamId(), Number(id));
  return (
    <Screen testID="manager-screen" belowHeader onRefresh={() => team.refetch()} refreshing={team.isRefetching}>
      <Stack.Screen options={{ title: name ?? 'Their team' }} />
      {team.isPending ? <Loading /> : null}
      {team.isError ? <ErrorView error={team.error} onRetry={() => team.refetch()} /> : null}
      {team.data ? <LiveTeamView data={team.data} whose="Their" /> : null}
      {team.data ? (
        <ThemedText type="caption" themeColor="textSecondary">
          Their squad as FPL locked it at the deadline. Bonus is provisional until FPL confirms it.
        </ThemedText>
      ) : null}
    </Screen>
  );
}
