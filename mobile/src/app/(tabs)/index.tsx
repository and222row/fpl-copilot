import { useQuery } from '@tanstack/react-query';
import { router } from 'expo-router';
import { View } from 'react-native';

import { Button } from '@/components/button';
import { ErrorView } from '@/components/error-view';
import { Card, Screen } from '@/components/screen';
import { Stat, StatRow } from '@/components/stat';
import { ThemedText } from '@/components/themed-text';
import type { AlertItem, Entitlement, Recommendation } from '@/lib/api';
import { useAlerts, useEntitlement, useMe, useRecommendation } from '@/lib/query';
import { pushState } from '@/lib/push';
import { money } from '@/lib/squad';

function timeUntil(iso: string): string {
  const ms = new Date(iso).getTime() - Date.now();
  if (ms <= 0) return 'passed';
  const hours = Math.floor(ms / 3_600_000);
  if (hours >= 48) return `in ${Math.floor(hours / 24)} days`;
  if (hours >= 1) return `in ${hours}h ${Math.floor((ms % 3_600_000) / 60_000)}m`;
  return `in ${Math.max(1, Math.floor(ms / 60_000))} min`;
}

function trialDaysLeft(e: Entitlement | undefined): number | null {
  if (e?.status !== 'TRIALING' || !e.trial_ends_at) return null;
  return Math.max(0, Math.ceil((new Date(e.trial_ends_at).getTime() - Date.now()) / 86_400_000));
}

export default function Home() {
  const me = useMe(true);
  const entitlement = useEntitlement(true);
  const account = me.data?.fpl_accounts[0];
  const teamId = account?.fpl_entry_id;

  const rec = useRecommendation(teamId);
  const alerts = useAlerts(teamId);
  const push = useQuery({ queryKey: ['push-state'], queryFn: pushState });

  const daysLeft = trialDaysLeft(entitlement.data);
  const refresh = () => {
    rec.refetch();
    alerts.refetch();
    entitlement.refetch();
  };

  return (
    <Screen title={account?.team_name ?? 'Home'} onRefresh={refresh} refreshing={rec.isRefetching}>
      {daysLeft !== null ? (
        <ThemedText type="small" themeColor="textSecondary">
          Free trial · {daysLeft} {daysLeft === 1 ? 'day' : 'days'} left
        </ThemedText>
      ) : null}

      {rec.isPending ? <ThemedText themeColor="textSecondary">Working out your best moves…</ThemedText> : null}
      {rec.isError ? <ErrorView error={rec.error} onRetry={() => rec.refetch()} /> : null}
      {rec.data ? <RecommendationView rec={rec.data} /> : null}

      <AlertsView alerts={alerts.data} />
      <Button title="News and alerts" variant="secondary" onPress={() => router.push('/news')} />
      {push.data === 'off' ? (
        <Card>
          <ThemedText type="small">Get a notification when a player in your squad is injured, a price moves, or the deadline is close.</ThemedText>
          <Button title="Set up notifications" variant="secondary" onPress={() => router.push('/notifications')} />
        </Card>
      ) : null}
    </Screen>
  );
}

function RecommendationView({ rec }: { rec: Recommendation }) {
  const t = rec.transfer;
  return (
    <>
      {rec.stale_warning ? (
        <Card>
          <ThemedText type="small" themeColor="warning">
            {rec.stale_warning}
          </ThemedText>
        </Card>
      ) : null}

      <Card>
        <ThemedText type="smallBold">{rec.gameweek.name}</ThemedText>
        <ThemedText themeColor="textSecondary">
          Deadline{' '}
          {new Date(rec.gameweek.deadline_time).toLocaleString(undefined, {
            weekday: 'short',
            hour: '2-digit',
            minute: '2-digit',
          })}{' '}
          · {timeUntil(rec.gameweek.deadline_time)}
        </ThemedText>
        <StatRow>
          <Stat label="Projected" value={`${rec.lineup.projected_total.toFixed(1)} pts`} />
          <Stat label="Free transfers" value={String(rec.free_transfers)} />
          <Stat label="Bank" value={money(rec.bank)} />
        </StatRow>
      </Card>

      <Card>
        <ThemedText type="small" themeColor="textSecondary">
          Recommended action
        </ThemedText>
        <ThemedText type="subtitle">{t.action}</ThemedText>
        {t.plan.moves.map((m) => (
          <ThemedText key={m.out.player_id}>
            Sell {m.out.name} → Buy {m.in.name}
          </ThemedText>
        ))}
        {t.plan.transfers > 0 ? (
          <ThemedText themeColor="textSecondary">
            {t.expected_net_gain >= 0 ? '+' : ''}
            {t.expected_net_gain.toFixed(1)} pts over {t.horizon_gameweeks} GW
            {t.hit_taken ? ` · −${t.hit_taken} hit` : ''} · {Math.round(t.confidence)}% confidence
          </ThemedText>
        ) : (
          <ThemedText themeColor="textSecondary">{t.plan.note}</ThemedText>
        )}
      </Card>

      <Card>
        <StatRow>
          <Stat label="Captain" value={rec.captain.pick?.name ?? '—'} />
          <Stat label="Vice" value={rec.captain.vice?.name ?? '—'} />
          <Stat label="Formation" value={rec.lineup.formation} />
        </StatRow>
      </Card>

      {rec.squad_issues.length > 0 ? (
        <Card>
          <ThemedText type="smallBold">Squad warnings</ThemedText>
          {rec.squad_issues.map((p) => (
            <ThemedText key={p.player_id} type="small">
              {p.name} · {p.reason}
              {p.news ? ` — ${p.news}` : ''}
            </ThemedText>
          ))}
        </Card>
      ) : null}
    </>
  );
}

function AlertsView({ alerts }: { alerts: AlertItem[] | undefined }) {
  const important = (alerts ?? []).filter((a) => a.severity !== 'info').slice(0, 3);
  if (important.length === 0) return null;
  return (
    <Card>
      <ThemedText type="smallBold">Latest alerts</ThemedText>
      {important.map((a) => (
        <View key={a.id}>
          <ThemedText type="small" themeColor={a.severity === 'critical' ? 'danger' : 'warning'}>
            {a.title}
          </ThemedText>
          {a.body ? (
            <ThemedText type="small" themeColor="textSecondary">
              {a.body}
            </ThemedText>
          ) : null}
        </View>
      ))}
    </Card>
  );
}

