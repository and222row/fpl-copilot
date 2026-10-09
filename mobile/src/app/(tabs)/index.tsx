import { useQuery } from '@tanstack/react-query';
import { router } from 'expo-router';
import { Pressable, StyleSheet, View } from 'react-native';

import { Button } from '@/components/button';
import { Carousel } from '@/components/carousel';
import { ErrorView } from '@/components/error-view';
import { openPlayer } from '@/components/pitch';
import { Card, ListGroup, ListRow, Pill, Screen, SectionHeader } from '@/components/screen';
import { SquadBanner } from '@/components/squad-banner';
import { Stat, StatRow } from '@/components/stat';
import { ThemedText } from '@/components/themed-text';
import { Radius, Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import type { AlertItem, Entitlement, Recommendation } from '@/lib/api';
import { useAlerts, useEntitlement, useMe, useRecommendation } from '@/lib/query';
import { pushState } from '@/lib/push';
import { money, signed } from '@/lib/squad';

function countdown(iso: string): string {
  const ms = new Date(iso).getTime() - Date.now();
  if (ms <= 0) return 'Deadline passed';
  const hours = Math.floor(ms / 3_600_000);
  if (hours >= 48) return `${Math.floor(hours / 24)} days`;
  if (hours >= 1) return `${hours}h ${Math.floor((ms % 3_600_000) / 60_000)}m`;
  return `${Math.max(1, Math.floor(ms / 60_000))} min`;
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
    <Screen
      testID="home-screen"
      title={account?.team_name ?? 'Home'}
      subtitle={daysLeft !== null ? <TrialStatus daysLeft={daysLeft} /> : undefined}
      onRefresh={refresh}
      refreshing={rec.isRefetching}>
      {rec.isPending ? <ThemedText themeColor="textSecondary">Working out your best moves…</ThemedText> : null}
      {rec.isError ? <ErrorView error={rec.error} onRetry={() => rec.refetch()} /> : null}
      {rec.data ? <RecommendationView rec={rec.data} /> : null}

      <AlertsView alerts={alerts.data} />

      <SectionHeader title="Tools" />
      <ListGroup>
        <ListRow
          testID="tool-leagues"
          title="Mini-leagues"
          subtitle="Your rank, the gaps, and what rivals own that you don't"
          onPress={() => router.push('/leagues')}
        />
        <ListRow testID="tool-chips" title="Chip advisor" subtitle="When to play each chip, doubles and blanks" onPress={() => router.push('/chips')} />
        <ListRow testID="tool-dream-team" title="Dream team" subtitle="The best 15 your budget can buy: a wildcard draft" onPress={() => router.push('/dream-team')} />
        <ListRow testID="tool-track-record" title="Track record" subtitle="How the advice has actually performed" onPress={() => router.push('/track-record')} />
        <ListRow title="Planner" subtitle="Your best transfers, gameweek by gameweek" onPress={() => router.push('/planner')} />
        <ListRow
          title="News and alerts"
          subtitle="Injuries, price changes and your alerts"
          onPress={() => router.push('/news')}
          last={push.data !== 'off'}
        />
        {push.data === 'off' ? (
          <ListRow
            title="Set up notifications"
            subtitle="Injuries in your squad, price moves, the deadline"
            onPress={() => router.push('/notifications')}
            last
          />
        ) : null}
      </ListGroup>
    </Screen>
  );
}

function TrialStatus({ daysLeft }: { daysLeft: number }) {
  return (
    <View style={styles.trialRow}>
      <View testID="trial-days">
        <Pill
          label={`Free trial · ${daysLeft} ${daysLeft === 1 ? 'day' : 'days'} left`}
          color={daysLeft <= 7 ? 'warning' : 'accent'}
          soft={daysLeft <= 7 ? 'warningSoft' : 'accentSoft'}
        />
      </View>
      <Button title="Upgrade" variant="brand" compact onPress={() => router.push('/paywall')} />
    </View>
  );
}

function RecommendationView({ rec }: { rec: Recommendation }) {
  const theme = useTheme();
  const t = rec.transfer;
  const deadline = new Date(rec.gameweek.deadline_time).toLocaleString(undefined, {
    weekday: 'short',
    hour: '2-digit',
    minute: '2-digit',
  });
  return (
    <>
      <SquadBanner warning={rec.stale_warning} />

      <Card variant="hero">
        <ThemedText type="eyebrow" style={{ color: theme.brand }}>
          {rec.gameweek.name}
        </ThemedText>
        <View>
          <ThemedText type="subtitle" style={{ color: theme.onHero }}>
            {countdown(rec.gameweek.deadline_time)}
          </ThemedText>
          <ThemedText type="small" style={{ color: theme.onHeroMuted }}>
            until the deadline · {deadline}
          </ThemedText>
        </View>
        <View style={[styles.heroDivider, { backgroundColor: 'rgba(255,255,255,0.14)' }]} />
        <StatRow>
          <Stat onHero label="Projected" value={`${rec.lineup.projected_total.toFixed(1)}`} />
          <Stat onHero label="Free transfers" value={String(rec.free_transfers)} />
          <Stat onHero label="Bank" value={money(rec.bank)} />
        </StatRow>
      </Card>

      <SectionHeader
        title="Recommended action"
        action={
          <ThemedText type="smallBold" themeColor="accent" onPress={() => router.push('/transfers')}>
            Details
          </ThemedText>
        }
      />
      <Card>
        <ThemedText testID="home-action" type="subtitle">
          {t.action}
        </ThemedText>
        {t.plan.moves.length > 0 ? (
          <View style={styles.moves}>
            {t.plan.moves.map((m) => (
              <View key={m.out.player_id} style={[styles.move, { backgroundColor: theme.backgroundSelected }]}>
                <View style={styles.grow}>
                  <ThemedText type="caption" themeColor="danger" style={styles.moveLabel}>
                    OUT
                  </ThemedText>
                  <ThemedText type="smallBold" numberOfLines={1}>
                    {m.out.name}
                  </ThemedText>
                </View>
                <ThemedText type="headline" themeColor="textSecondary">
                  →
                </ThemedText>
                <View style={[styles.grow, styles.alignEnd]}>
                  <ThemedText type="caption" themeColor="highlight" style={styles.moveLabel}>
                    IN
                  </ThemedText>
                  <ThemedText type="smallBold" numberOfLines={1}>
                    {m.in.name}
                  </ThemedText>
                </View>
              </View>
            ))}
          </View>
        ) : null}
        {t.plan.transfers > 0 ? (
          <StatRow>
            <Stat label={`Gain · ${t.horizon_gameweeks} GW`} value={`${signed(t.expected_net_gain)}`} tone="positive" />
            <Stat label="Cost" value={t.hit_taken ? `−${t.hit_taken}` : 'Free'} tone={t.hit_taken ? 'negative' : undefined} />
            <Stat label="Confidence" value={`${Math.round(t.confidence)}%`} />
          </StatRow>
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
        <>
          <SectionHeader title={`Squad warnings · ${rec.squad_issues.length}`} />
          <Carousel
            testID="warnings-carousel"
            pages={rec.squad_issues.map((p) => (
              <NoticeCard
                key={p.player_id}
                tone={p.chance_of_playing === 0 ? 'danger' : 'warning'}
                label={p.reason}
                title={p.name}
                body={p.news}
                onPress={() => openPlayer(p.player_id)}
              />
            ))}
          />
        </>
      ) : null}
    </>
  );
}

function AlertsView({ alerts }: { alerts: AlertItem[] | undefined }) {
  const important = (alerts ?? []).filter((a) => a.severity !== 'info').slice(0, 6);
  if (important.length === 0) return null;
  return (
    <>
      <SectionHeader
        title="Latest alerts"
        action={
          <ThemedText type="smallBold" themeColor="accent" onPress={() => router.push('/news')}>
            All
          </ThemedText>
        }
      />
      <Carousel
        testID="alerts-carousel"
        pages={important.map((a) => (
          <NoticeCard
            key={a.id}
            tone={a.severity === 'critical' ? 'danger' : 'warning'}
            label={a.severity === 'critical' ? 'Important' : 'Heads up'}
            title={a.title}
            body={a.body}
            onPress={a.player_id ? () => openPlayer(a.player_id!) : undefined}
          />
        ))}
      />
    </>
  );
}

/** One warning or alert as a carousel card: coloured label, title, detail. */
function NoticeCard({
  tone,
  label,
  title,
  body,
  onPress,
}: {
  tone: 'danger' | 'warning';
  label: string;
  title: string;
  body?: string | null;
  onPress?: () => void;
}) {
  const theme = useTheme();
  return (
    <Pressable accessibilityRole={onPress ? 'button' : undefined} disabled={!onPress} onPress={onPress}>
      <Card style={[styles.notice, { borderTopColor: theme[tone] }]}>
        <View style={[styles.noticeLabel, { backgroundColor: tone === 'danger' ? theme.dangerSoft : theme.warningSoft }]}>
          <ThemedText type="caption" style={{ color: theme[tone], fontWeight: '800' }}>
            {label}
          </ThemedText>
        </View>
        <ThemedText type="headline" numberOfLines={2}>
          {title}
        </ThemedText>
        {body ? (
          <ThemedText type="small" themeColor="textSecondary" numberOfLines={3}>
            {body}
          </ThemedText>
        ) : null}
        {onPress ? (
          <ThemedText type="caption" themeColor="accent" style={styles.noticeLink}>
            See player ›
          </ThemedText>
        ) : null}
      </Card>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  trialRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: Spacing.one },
  heroDivider: { height: StyleSheet.hairlineWidth, marginVertical: Spacing.one },
  moves: { gap: Spacing.two },
  move: { flexDirection: 'row', alignItems: 'center', gap: Spacing.two, borderRadius: Radius.md, padding: 12 },
  moveLabel: { fontWeight: '800', letterSpacing: 0.6 },
  notice: { borderTopWidth: 4, minHeight: 150 },
  noticeLabel: { alignSelf: 'flex-start', borderRadius: Radius.pill, paddingHorizontal: 10, paddingVertical: 3 },
  noticeLink: { marginTop: 'auto', fontWeight: '700' },
  grow: { flex: 1 },
  alignEnd: { alignItems: 'flex-end' },
});
