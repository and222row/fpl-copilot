import { StyleSheet, View } from 'react-native';

import { ErrorView } from '@/components/error-view';
import { Banner, Card, Pill, Screen, SectionHeader } from '@/components/screen';
import { Stat, StatRow } from '@/components/stat';
import { ThemedText } from '@/components/themed-text';
import { useTheme } from '@/hooks/use-theme';
import type { AccuracySummary, OutcomeRow, PendingAdvice } from '@/lib/api';
import { useTeamId, useTrackRecord } from '@/lib/query';

const KINDS: Record<string, { title: string; hit: string }> = {
  captain: { title: 'Captain', hit: 'Best pick' },
  lineup: { title: 'Starting XI', hit: 'Matched or beat yours' },
  transfer: { title: 'Transfers', hit: 'Paid off' },
};

const pct = (v: number | null | undefined) => (v === null || v === undefined ? '—' : `${Math.round(v * 100)}%`);

export default function TrackRecord() {
  const teamId = useTeamId();
  const record = useTrackRecord(teamId);
  return (
    <Screen testID="track-record-screen" belowHeader onRefresh={() => record.refetch()} refreshing={record.isRefetching}>
      {record.isPending ? <ThemedText themeColor="textSecondary">Loading the track record…</ThemedText> : null}
      {record.isError ? <ErrorView error={record.error} onRetry={() => record.refetch()} /> : null}
      {record.data ? <Body summary={record.data.summary} history={record.data.history} pending={record.data.pending} /> : null}
    </Screen>
  );
}

function Body({ summary, history, pending }: { summary: AccuracySummary; history: OutcomeRow[]; pending: PendingAdvice }) {
  const theme = useTheme();
  const waiting = [...new Set(pending.pending.map((p) => p.gameweek))].sort((a, b) => a - b);
  return (
    <>
      <Card variant="hero">
        <ThemedText type="eyebrow" style={{ color: theme.brand }}>
          Graded honestly, every gameweek
        </ThemedText>
        <ThemedText type="subtitle" style={{ color: theme.onHero }}>
          {summary.gameweeks_scored === 0
            ? 'Nothing graded yet'
            : `${summary.gameweeks_scored} gameweek${summary.gameweeks_scored === 1 ? '' : 's'} graded`}
        </ThemedText>
        <ThemedText type="small" style={{ color: theme.onHeroMuted }}>
          The advice we gave before each deadline, compared with what actually happened, whether it flatters us or not.
        </ThemedText>
      </Card>

      {waiting.length > 0 ? (
        <Banner
          tone="info"
          title={`Advice for GW${waiting.join(', GW')} is waiting to be graded`}
          detail="It is graded automatically a day or two after the gameweek ends, once FPL confirms bonus points."
        />
      ) : null}

      {Object.entries(summary.categories).map(([kind, c]) => {
        const k = KINDS[kind] ?? { title: kind, hit: 'Right' };
        return (
          <Card key={kind} testID={`accuracy-${kind}`}>
            <ThemedText type="headline">{k.title}</ThemedText>
            <StatRow>
              <Stat label={k.hit} value={pct(c.hit_rate)} tone={c.hit_rate !== null && c.hit_rate >= 0.5 ? 'positive' : undefined} />
              <Stat label="Points missed" value={c.mean_regret.toFixed(1)} />
              <Stat label="Decisions" value={String(c.decisions)} />
            </StatRow>
            {c.points_lost_by_overriding !== null && c.points_lost_by_overriding !== 0 ? (
              <ThemedText type="caption" themeColor="textSecondary">
                {c.points_lost_by_overriding > 0
                  ? `Following the advice would have gained you ${c.points_lost_by_overriding.toFixed(1)} points.`
                  : `Going your own way gained you ${(-c.points_lost_by_overriding).toFixed(1)} points.`}
              </ThemedText>
            ) : null}
          </Card>
        );
      })}

      {history.length > 0 ? (
        <>
          <SectionHeader title="Gameweek by gameweek" />
          <Card style={styles.list}>
            {history.map((h, i) => (
              <View
                key={`${h.gameweek}-${h.kind}`}
                style={[styles.row, i > 0 && { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: theme.hairline }]}>
                <ThemedText type="smallBold" style={styles.gw}>
                  GW{h.gameweek}
                </ThemedText>
                <View style={styles.grow}>
                  <ThemedText type="smallBold">{KINDS[h.kind]?.title ?? h.kind}</ThemedText>
                  <ThemedText type="caption" themeColor="textSecondary">
                    Predicted {h.predicted.toFixed(1)} · scored {h.actual.toFixed(0)}
                    {h.regret > 0 ? ` · ${h.regret.toFixed(0)} short of the best` : ''}
                  </ThemedText>
                </View>
                {h.correct === null ? null : (
                  <Pill
                    label={h.correct ? 'Right' : 'Missed'}
                    color={h.correct ? 'highlight' : 'danger'}
                    soft={h.correct ? 'highlightSoft' : 'dangerSoft'}
                  />
                )}
              </View>
            ))}
          </Card>
        </>
      ) : summary.gameweeks_scored === 0 && waiting.length === 0 ? (
        <ThemedText themeColor="textSecondary">
          Open the app before a deadline and the advice it shows is saved, then graded once that gameweek finishes.
        </ThemedText>
      ) : null}
    </>
  );
}

const styles = StyleSheet.create({
  list: { paddingVertical: 4, gap: 0 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 10 },
  gw: { width: 44 },
  grow: { flex: 1 },
});
