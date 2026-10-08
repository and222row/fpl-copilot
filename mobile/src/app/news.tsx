import { useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import { Button } from '@/components/button';
import { ChipGroup } from '@/components/chip';
import { errorMessage, ErrorView } from '@/components/error-view';
import { openPlayer } from '@/components/pitch';
import { Card, Screen } from '@/components/screen';
import { ThemedText } from '@/components/themed-text';
import { Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import { api, type AlertItem, type NewsCategory, type NewsEvent, type PriceWatchItem } from '@/lib/api';
import { timeAgo } from '@/lib/format';
import { queryClient, queryKeys, useAlerts, useNewsEvents, usePriceWatch, useTeamId } from '@/lib/query';

type Section = 'alerts' | 'news' | 'prices';

const SECTIONS = [
  { label: 'My alerts', value: 'alerts' },
  { label: 'All news', value: 'news' },
  { label: 'Prices', value: 'prices' },
] as const;

const CATEGORY_LABELS: Record<NewsCategory, string> = {
  INJURY: 'Injury',
  RETURN_FROM_INJURY: 'Return',
  SUSPENSION: 'Suspension',
  TRANSFER: 'Transfer',
  PRICE_CHANGE: 'Price',
  OTHER: 'Update',
};

const CATEGORY_FILTERS = [
  { label: 'All', value: undefined },
  { label: 'Injuries', value: 'INJURY' },
  { label: 'Returns', value: 'RETURN_FROM_INJURY' },
  { label: 'Suspensions', value: 'SUSPENSION' },
  { label: 'Transfers', value: 'TRANSFER' },
] as const;

export default function News() {
  const [section, setSection] = useState<Section>('alerts');
  return (
    <Screen belowHeader>
      <ChipGroup options={SECTIONS} value={section} onChange={setSection} />
      {section === 'alerts' ? <Alerts /> : section === 'news' ? <Feed /> : <Prices />}
    </Screen>
  );
}

function Alerts() {
  const teamId = useTeamId();
  const alerts = useAlerts(teamId);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const unread = alerts.data?.filter((a) => !a.read).length ?? 0;

  async function markAllRead() {
    if (!teamId) return;
    setBusy(true);
    setError(null);
    try {
      await api.markAlertsRead(teamId);
      await queryClient.invalidateQueries({ queryKey: queryKeys.alerts(teamId) });
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  if (alerts.isError) return <ErrorView error={alerts.error} onRetry={() => alerts.refetch()} />;
  if (alerts.isPending) return <ThemedText themeColor="textSecondary">Loading…</ThemedText>;
  if (alerts.data.length === 0) {
    return (
      <ThemedText themeColor="textSecondary">
        No alerts. You will see one here when something changes for a player in your squad.
      </ThemedText>
    );
  }
  return (
    <>
      {unread > 0 ? (
        <Button title={`Mark ${unread} as read`} variant="secondary" loading={busy} onPress={markAllRead} />
      ) : null}
      {error ? <ThemedText themeColor="danger">{error}</ThemedText> : null}
      {alerts.data.map((a) => (
        <AlertRow key={a.id} alert={a} />
      ))}
    </>
  );
}

function AlertRow({ alert }: { alert: AlertItem }) {
  const theme = useTheme();
  const color = alert.severity === 'critical' ? theme.danger : alert.severity === 'warning' ? theme.warning : theme.textSecondary;
  return (
    <Pressable
      accessibilityRole="button"
      disabled={!alert.player_id}
      onPress={() => alert.player_id && openPlayer(alert.player_id)}>
      <Card>
        <View style={styles.titleRow}>
          {!alert.read ? <View style={[styles.dot, { backgroundColor: color }]} accessibilityLabel="Unread" /> : null}
          <ThemedText type="smallBold" style={[styles.grow, { color }]}>
            {alert.title}
          </ThemedText>
        </View>
        {alert.body ? <ThemedText type="small">{alert.body}</ThemedText> : null}
        <ThemedText type="small" themeColor="textSecondary">
          {timeAgo(alert.created_at)}
        </ThemedText>
      </Card>
    </Pressable>
  );
}

function Feed() {
  const events = useNewsEvents();
  const [category, setCategory] = useState<NewsCategory | undefined>();

  if (events.isError) return <ErrorView error={events.error} onRetry={() => events.refetch()} />;
  if (events.isPending) return <ThemedText themeColor="textSecondary">Loading…</ThemedText>;

  // Price moves have their own tab; here they would bury the availability news.
  const items = events.data.filter(
    (e) => e.category !== 'PRICE_CHANGE' && (category === undefined || e.category === category),
  );
  return (
    <>
      <ChipGroup options={CATEGORY_FILTERS} value={category} onChange={setCategory} />
      <ThemedText type="small" themeColor="textSecondary">
        From FPL&apos;s official player news, checked every 30 minutes. Last 7 days.
      </ThemedText>
      {items.length === 0 ? <ThemedText themeColor="textSecondary">Nothing in the last week.</ThemedText> : null}
      {items.map((e) => (
        <EventRow key={e.id} event={e} />
      ))}
    </>
  );
}

function EventRow({ event }: { event: NewsEvent }) {
  const theme = useTheme();
  const color =
    event.direction === 'negative' ? theme.danger : event.direction === 'positive' ? theme.highlight : theme.textSecondary;
  return (
    <Pressable accessibilityRole="button" onPress={() => openPlayer(event.player_id)}>
      <Card>
        <View style={styles.titleRow}>
          <ThemedText type="smallBold" style={styles.grow}>
            {event.name} · {event.team}
          </ThemedText>
          <ThemedText type="small" style={{ color }}>
            {CATEGORY_LABELS[event.category]}
          </ThemedText>
        </View>
        {event.news ? <ThemedText type="small">{event.news}</ThemedText> : null}
        {event.confidence === 'low' ? (
          <ThemedText type="small" themeColor="warning">
            We could not read this update automatically. Check FPL before acting on it.
          </ThemedText>
        ) : null}
        <ThemedText type="small" themeColor="textSecondary">
          {event.source_label} · {timeAgo(event.detected_at)}
        </ThemedText>
      </Card>
    </Pressable>
  );
}

function Prices() {
  const prices = usePriceWatch();
  if (prices.isError) return <ErrorView error={prices.error} onRetry={() => prices.refetch()} />;
  if (prices.isPending) return <ThemedText themeColor="textSecondary">Loading…</ThemedText>;
  return (
    <>
      <ThemedText type="small" themeColor="textSecondary">
        Players at least halfway to a price change, from FPL&apos;s own transfer data.
      </ThemedText>
      {prices.data.length === 0 ? <ThemedText themeColor="textSecondary">No price changes look close.</ThemedText> : null}
      {prices.data.map((p) => (
        <PriceRow key={p.player_id} item={p} />
      ))}
    </>
  );
}

function PriceRow({ item }: { item: PriceWatchItem }) {
  const theme = useTheme();
  const rising = item.direction === 'rise';
  return (
    <Pressable accessibilityRole="button" onPress={() => openPlayer(item.player_id)} style={styles.priceRow}>
      <View style={styles.grow}>
        <ThemedText type="smallBold">{item.name}</ThemedText>
        <ThemedText type="small" themeColor="textSecondary">
          {item.team} · £{item.price.toFixed(1)}m
        </ThemedText>
      </View>
      <ThemedText type="smallBold" style={{ color: rising ? theme.highlight : theme.danger }}>
        {rising ? '▲' : '▼'} {Math.abs(Math.round(item.percent_to_threshold))}%
      </ThemedText>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  titleRow: { flexDirection: 'row', alignItems: 'center', gap: Spacing.two },
  dot: { width: 8, height: 8, borderRadius: 4 },
  priceRow: { flexDirection: 'row', alignItems: 'center', paddingVertical: Spacing.two },
  grow: { flex: 1 },
});
