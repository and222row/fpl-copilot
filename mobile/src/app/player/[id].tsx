import { Stack, useLocalSearchParams } from 'expo-router';
import { StyleSheet, View } from 'react-native';

import { ErrorView } from '@/components/error-view';
import { PlayerPhoto } from '@/components/player-photo';
import { Card, Screen } from '@/components/screen';
import { Stat, StatRow } from '@/components/stat';
import { ThemedText } from '@/components/themed-text';
import { VerdictBadge } from '@/components/verdict-badge';
import { Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import type { PlayerDetail, Recommendation } from '@/lib/api';
import { usePlayer, useRecommendation, useTeamId } from '@/lib/query';
import { availabilityLabel, marketVerdict, type Verdict } from '@/lib/squad';

const SOURCES: Record<string, string> = { fpl_api: 'FPL official' };

// FPL resets price-change progress after each change; past ±50% a move is near.
const PRICE_WATCH = 50;

export default function PlayerScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const playerId = Number(id);
  const player = usePlayer(playerId);
  const rec = useRecommendation(useTeamId());

  return (
    <Screen belowHeader onRefresh={() => player.refetch()} refreshing={player.isRefetching}>
      <Stack.Screen options={{ title: player.data?.name ?? '' }} />
      {player.isPending ? <ThemedText themeColor="textSecondary">Loading…</ThemedText> : null}
      {player.isError ? <ErrorView error={player.error} onRetry={() => player.refetch()} /> : null}
      {player.data ? <PlayerView p={player.data} rec={rec.data} /> : null}
    </Screen>
  );
}

function verdictText(verdict: Verdict | null, p: PlayerDetail, rec: Recommendation | undefined): string[] {
  const move = rec?.transfer.plan.moves.find(
    (m) => m.out.player_id === p.id || m.in.player_id === p.id,
  );
  if (verdict === 'SELL' || verdict === 'BUY') {
    const other = verdict === 'SELL' ? move?.in.name : move?.out.name;
    return [
      verdict === 'SELL' ? `Recommended transfer out, for ${other}.` : `Recommended transfer in, for ${other}.`,
      ...(move?.reasons ?? []),
    ];
  }
  if (verdict === 'HOLD') return ['In your squad. No change recommended this gameweek.'];
  return ['Not in your recommended transfers this gameweek.'];
}

function fdrColor(fdr: number, theme: ReturnType<typeof useTheme>): string {
  if (fdr <= 2.5) return theme.highlight;
  if (fdr >= 3.5) return theme.danger;
  return theme.textSecondary;
}

function PlayerView({ p, rec }: { p: PlayerDetail; rec: Recommendation | undefined }) {
  const theme = useTheme();
  const verdict = marketVerdict(p.id, rec);
  const availability = availabilityLabel(p.status, p.chance_this);
  const progress = p.price_change.percent_to_threshold;

  return (
    <>
      <View style={styles.header}>
        <PlayerPhoto uri={p.photo} position={p.position} size={72} />
        <View style={styles.grow}>
          <ThemedText type="smallBold">{p.full_name}</ThemedText>
          <ThemedText themeColor="textSecondary">
            {p.team_full} · {p.position}
          </ThemedText>
          <ThemedText type="subtitle">£{p.price.toFixed(1)}m</ThemedText>
        </View>
      </View>

      {availability || p.news ? (
        <Card>
          <ThemedText type="smallBold" themeColor={p.status === 'd' ? 'warning' : 'danger'}>
            {availability ?? p.status_label}
          </ThemedText>
          {p.news ? <ThemedText type="small">{p.news}</ThemedText> : null}
        </Card>
      ) : null}

      <Card>
        <View style={styles.verdictRow}>
          {verdict ? <VerdictBadge verdict={verdict} /> : null}
          <ThemedText type="smallBold">Recommendation</ThemedText>
        </View>
        {verdictText(verdict, p, rec).map((line) => (
          <ThemedText key={line} type="small" themeColor="textSecondary">
            {line}
          </ThemedText>
        ))}
      </Card>

      <Card>
        <StatRow>
          <Stat label="Form" value={String(p.form)} />
          <Stat label="Owned" value={`${p.selected_by_percent.toFixed(1)}%`} />
          <Stat label="Points" value={String(p.total_points)} />
          <Stat label="Minutes" value={String(p.minutes)} />
        </StatRow>
        <StatRow>
          <Stat label="Goals" value={String(p.goals)} />
          <Stat label="Assists" value={String(p.assists)} />
          <Stat label="xG" value={p.expected_goals.toFixed(1)} />
          <Stat label="xA" value={p.expected_assists.toFixed(1)} />
        </StatRow>
        {Math.abs(progress) >= PRICE_WATCH ? (
          <ThemedText type="small" themeColor="warning">
            Price likely to {progress > 0 ? 'rise' : 'fall'} soon ({Math.abs(Math.round(progress))}% of the way).
          </ThemedText>
        ) : null}
      </Card>

      <Card>
        <ThemedText type="smallBold">
          Next {p.projection.gameweeks.length} gameweeks · {p.projection.total_xpts.toFixed(1)} xPts
        </ThemedText>
        {p.projection.gameweeks.map((g) => (
          <View key={g.gameweek} style={styles.tableRow}>
            <ThemedText type="small" style={styles.gw}>
              GW{g.gameweek}
            </ThemedText>
            <View style={styles.grow}>
              {g.fixtures.length === 0 ? (
                <ThemedText type="small" themeColor="textSecondary">
                  No fixture
                </ThemedText>
              ) : (
                g.fixtures.map((f, i) => (
                  <ThemedText key={i} type="small" style={{ color: fdrColor(f.fdr, theme) }}>
                    {f.opponent} ({f.is_home ? 'H' : 'A'}) · {f.fdr.toFixed(1)}
                  </ThemedText>
                ))
              )}
            </View>
            <ThemedText type="small" themeColor="textSecondary" style={styles.cell}>
              {Math.round(g.p_start * 100)}%
            </ThemedText>
            <ThemedText type="smallBold" style={styles.cell}>
              {g.xpts.toFixed(1)}
            </ThemedText>
          </View>
        ))}
        <ThemedText type="small" themeColor="textSecondary">
          Difficulty 1 is easiest · % is the chance he starts
        </ThemedText>
      </Card>

      <Card>
        <ThemedText type="smallBold">Recent matches</ThemedText>
        {p.recent === null ? (
          <ThemedText type="small" themeColor="textSecondary">
            FPL didn&apos;t respond. Pull down to try again.
          </ThemedText>
        ) : p.recent.length === 0 ? (
          <ThemedText type="small" themeColor="textSecondary">
            No matches yet this season.
          </ThemedText>
        ) : (
          p.recent.map((m) => (
            <View key={`${m.gameweek}-${m.opponent}`} style={styles.tableRow}>
              <ThemedText type="small" style={styles.gw}>
                GW{m.gameweek}
              </ThemedText>
              <ThemedText type="small" style={styles.grow}>
                {m.opponent} ({m.is_home ? 'H' : 'A'}) · {m.minutes}&apos;
                {m.goals ? ` · ${m.goals}G` : ''}
                {m.assists ? ` · ${m.assists}A` : ''}
                {m.bonus ? ` · ${m.bonus}B` : ''}
              </ThemedText>
              <ThemedText type="smallBold" style={styles.cell}>
                {m.points}
              </ThemedText>
            </View>
          ))
        )}
      </Card>

      {p.availability_news.length > 0 ? (
        <Card>
          <ThemedText type="smallBold">News</ThemedText>
          {p.availability_news.map((n) => (
            <View key={`${n.detected_at}-${n.event_type}`} style={styles.news}>
              <ThemedText type="small">{n.text || n.status}</ThemedText>
              <ThemedText type="small" themeColor="textSecondary">
                {SOURCES[n.source] ?? n.source} · {new Date(n.detected_at).toLocaleString()}
              </ThemedText>
            </View>
          ))}
        </Card>
      ) : null}
    </>
  );
}

const styles = StyleSheet.create({
  header: { flexDirection: 'row', gap: Spacing.three, alignItems: 'center' },
  verdictRow: { flexDirection: 'row', alignItems: 'center', gap: Spacing.two },
  tableRow: { flexDirection: 'row', alignItems: 'center', gap: Spacing.two, paddingVertical: Spacing.half },
  gw: { width: 44 },
  cell: { width: 40, textAlign: 'right' },
  news: { gap: Spacing.half },
  grow: { flex: 1 },
});
