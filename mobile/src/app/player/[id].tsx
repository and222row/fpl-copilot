import { Stack, useLocalSearchParams } from 'expo-router';
import { StyleSheet, View } from 'react-native';

import { ErrorView } from '@/components/error-view';
import { PlayerPhoto } from '@/components/player-photo';
import { Banner, Card, Screen, SectionHeader } from '@/components/screen';
import { Stat, StatRow } from '@/components/stat';
import { ThemedText } from '@/components/themed-text';
import { VerdictBadge } from '@/components/verdict-badge';
import { Radius, Spacing, type Theme } from '@/constants/theme';
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
    <Screen testID="player-screen" belowHeader onRefresh={() => player.refetch()} refreshing={player.isRefetching}>
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

/** Fixture difficulty as a colour pair: green easy, red hard. */
function fdrColors(fdr: number, theme: Theme): [string, string] {
  if (fdr <= 2.5) return [theme.highlight, theme.highlightSoft];
  if (fdr >= 3.5) return [theme.danger, theme.dangerSoft];
  return [theme.textSecondary, theme.backgroundSelected];
}

function PlayerView({ p, rec }: { p: PlayerDetail; rec: Recommendation | undefined }) {
  const theme = useTheme();
  const verdict = marketVerdict(p.id, rec);
  const availability = availabilityLabel(p.status, p.chance_this);
  const progress = p.price_change.percent_to_threshold;

  return (
    <>
      <Card variant="hero">
        <View style={styles.header}>
          <PlayerPhoto uri={p.photo} position={p.position} size={76} />
          <View style={styles.grow}>
            <ThemedText type="headline" style={{ color: theme.onHero }}>
              {p.full_name}
            </ThemedText>
            <ThemedText type="small" style={{ color: theme.onHeroMuted }}>
              {p.team_full} · {p.position}
            </ThemedText>
            <ThemedText type="subtitle" style={{ color: theme.brand }}>
              £{p.price.toFixed(1)}m
            </ThemedText>
          </View>
        </View>
      </Card>

      {availability || p.news ? (
        <Banner title={availability ?? p.status_label} detail={p.news || null} />
      ) : null}

      <Card>
        <View style={styles.verdictRow}>
          <ThemedText testID="player-recommendation" type="eyebrow" themeColor="textSecondary" style={styles.grow}>
            Recommendation
          </ThemedText>
          {verdict ? <VerdictBadge verdict={verdict} /> : null}
        </View>
        {verdictText(verdict, p, rec).map((line, i) => (
          <ThemedText key={line} type={i === 0 ? 'headline' : 'small'} themeColor={i === 0 ? 'text' : 'textSecondary'}>
            {line}
          </ThemedText>
        ))}
      </Card>

      <SectionHeader title="This season" />
      <Card>
        <StatRow>
          <Stat label="Form" value={String(p.form)} />
          <Stat label="Owned" value={`${p.selected_by_percent.toFixed(1)}%`} />
          <Stat label="Points" value={String(p.total_points)} />
          <Stat label="Minutes" value={String(p.minutes)} />
        </StatRow>
        <View style={[styles.divider, { backgroundColor: theme.hairline }]} />
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

      <SectionHeader title={`Next ${p.projection.gameweeks.length} gameweeks · ${p.projection.total_xpts.toFixed(1)} xPts`} />
      <Card>
        {p.projection.gameweeks.map((g, idx) => (
          <View key={g.gameweek} style={[styles.tableRow, idx > 0 && { borderTopColor: theme.hairline, borderTopWidth: StyleSheet.hairlineWidth }]}>
            <ThemedText type="smallBold" style={styles.gw}>
              GW{g.gameweek}
            </ThemedText>
            <View style={[styles.grow, styles.fixtures]}>
              {g.fixtures.length === 0 ? (
                <ThemedText type="small" themeColor="textSecondary">
                  No fixture
                </ThemedText>
              ) : (
                g.fixtures.map((f, i) => {
                  const [color, soft] = fdrColors(f.fdr, theme);
                  return (
                    <View key={i} style={[styles.fixture, { backgroundColor: soft }]}>
                      <ThemedText type="caption" style={{ color, fontWeight: '700' }}>
                        {f.opponent} ({f.is_home ? 'H' : 'A'}) · {f.fdr.toFixed(1)}
                      </ThemedText>
                    </View>
                  );
                })
              )}
            </View>
            <ThemedText type="caption" themeColor="textSecondary" style={styles.cell}>
              {Math.round(g.p_start * 100)}%
            </ThemedText>
            <ThemedText type="headline" style={[styles.cell, styles.number]}>
              {g.xpts.toFixed(1)}
            </ThemedText>
          </View>
        ))}
        <ThemedText type="caption" themeColor="textSecondary">
          Difficulty 1 is easiest · % is the chance he starts
        </ThemedText>
      </Card>

      <SectionHeader title="Recent matches" />
      <Card>
        {p.recent === null ? (
          <ThemedText type="small" themeColor="textSecondary">
            FPL didn&apos;t respond. Pull down to try again.
          </ThemedText>
        ) : p.recent.length === 0 ? (
          <ThemedText type="small" themeColor="textSecondary">
            No matches yet this season.
          </ThemedText>
        ) : (
          p.recent.map((m, idx) => (
            <View
              key={`${m.gameweek}-${m.opponent}`}
              style={[styles.tableRow, idx > 0 && { borderTopColor: theme.hairline, borderTopWidth: StyleSheet.hairlineWidth }]}>
              <ThemedText type="smallBold" style={styles.gw}>
                GW{m.gameweek}
              </ThemedText>
              <ThemedText type="small" style={styles.grow}>
                {m.opponent} ({m.is_home ? 'H' : 'A'}) · {m.minutes}&apos;
                {m.goals ? ` · ${m.goals}G` : ''}
                {m.assists ? ` · ${m.assists}A` : ''}
                {m.bonus ? ` · ${m.bonus}B` : ''}
              </ThemedText>
              <View style={[styles.points, { backgroundColor: m.points >= 6 ? theme.highlightSoft : theme.backgroundSelected }]}>
                <ThemedText type="smallBold" style={[styles.number, { color: m.points >= 6 ? theme.highlight : theme.text }]}>
                  {m.points}
                </ThemedText>
              </View>
            </View>
          ))
        )}
      </Card>

      {p.availability_news.length > 0 ? (
        <>
          <SectionHeader title="News" />
          <Card>
            {p.availability_news.map((n) => (
              <View key={`${n.detected_at}-${n.event_type}`} style={styles.news}>
                <View style={[styles.dot, { backgroundColor: theme.warning }]} />
                <View style={styles.grow}>
                  <ThemedText type="small">{n.text || n.status}</ThemedText>
                  <ThemedText type="caption" themeColor="textSecondary">
                    {SOURCES[n.source] ?? n.source} · {new Date(n.detected_at).toLocaleString()}
                  </ThemedText>
                </View>
              </View>
            ))}
          </Card>
        </>
      ) : null}
    </>
  );
}

const styles = StyleSheet.create({
  header: { flexDirection: 'row', gap: Spacing.three, alignItems: 'center' },
  verdictRow: { flexDirection: 'row', alignItems: 'center', gap: Spacing.two },
  divider: { height: StyleSheet.hairlineWidth },
  tableRow: { flexDirection: 'row', alignItems: 'center', gap: Spacing.two, paddingVertical: Spacing.two },
  fixtures: { flexDirection: 'row', flexWrap: 'wrap', gap: 4 },
  fixture: { borderRadius: Radius.pill, paddingHorizontal: 8, paddingVertical: 3 },
  gw: { width: 44 },
  cell: { width: 44, textAlign: 'right' },
  number: { fontVariant: ['tabular-nums'] },
  points: { minWidth: 34, borderRadius: Radius.sm, alignItems: 'center', paddingVertical: 3 },
  news: { flexDirection: 'row', gap: 10, alignItems: 'flex-start' },
  dot: { width: 8, height: 8, borderRadius: 4, marginTop: 6 },
  grow: { flex: 1 },
});
