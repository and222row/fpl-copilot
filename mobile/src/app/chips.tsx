import { StyleSheet, View } from 'react-native';

import { ErrorView } from '@/components/error-view';
import { Banner, Card, Pill, Screen, SectionHeader } from '@/components/screen';
import { Stat, StatRow } from '@/components/stat';
import { ThemedText } from '@/components/themed-text';
import type { ThemeColor } from '@/constants/theme';
import type { ChipAdvice, ChipItem } from '@/lib/api';
import { useChips, useTeamId } from '@/lib/query';

const VERDICTS: Record<string, { label: string; color: ThemeColor; soft: ThemeColor }> = {
  use_now: { label: 'Play this week', color: 'highlight', soft: 'highlightSoft' },
  use_soon: { label: 'Play soon', color: 'highlight', soft: 'highlightSoft' },
  consider: { label: 'Worth considering', color: 'warning', soft: 'warningSoft' },
  hold: { label: 'Hold', color: 'textSecondary', soft: 'backgroundSelected' },
  used: { label: 'Used', color: 'textSecondary', soft: 'backgroundSelected' },
  not_yet: { label: 'Not yet available', color: 'textSecondary', soft: 'backgroundSelected' },
  expired: { label: 'Expired', color: 'textSecondary', soft: 'backgroundSelected' },
};

export function verdictFor(chip: ChipItem) {
  if (chip.verdict === 'used' && chip.used_in_gameweek) {
    return { ...VERDICTS.used, label: `Used in GW${chip.used_in_gameweek}` };
  }
  return VERDICTS[chip.verdict] ?? { label: 'No call yet', color: 'textSecondary' as ThemeColor, soft: 'backgroundSelected' as ThemeColor };
}

export default function Chips() {
  const teamId = useTeamId();
  const chips = useChips(teamId);
  return (
    <Screen testID="chips-screen" belowHeader onRefresh={() => chips.refetch()} refreshing={chips.isRefetching}>
      {chips.isPending ? <ThemedText themeColor="textSecondary">Valuing each chip over the coming gameweeks…</ThemedText> : null}
      {chips.isError ? <ErrorView error={chips.error} onRetry={() => chips.refetch()} /> : null}
      {chips.data ? <ChipsBody data={chips.data} /> : null}
    </Screen>
  );
}

function shapeLines(map: Record<string, string[]>): string[] {
  return Object.entries(map).map(([gw, teams]) => `GW${gw}: ${teams.join(', ')}`);
}

function ChipsBody({ data }: { data: ChipAdvice }) {
  const doubles = shapeLines(data.fixture_shape.doubles);
  const blanks = shapeLines(data.fixture_shape.blanks);
  const order = (c: ChipItem) => (['use_now', 'use_soon', 'consider', 'hold'].indexOf(c.verdict) + 5) % 5;
  return (
    <>
      <Card>
        <ThemedText type="eyebrow" themeColor="textSecondary">
          Gameweek {data.target_gameweek} · your squad
        </ThemedText>
        <StatRow>
          <Stat label="Playing" value={String(data.squad_this_gameweek.playing)} />
          <Stat label="Doubles" value={String(data.squad_this_gameweek.doubling)} tone={data.squad_this_gameweek.doubling ? 'positive' : undefined} />
          <Stat label="Blanks" value={String(data.squad_this_gameweek.blank)} tone={data.squad_this_gameweek.blank ? 'negative' : undefined} />
        </StatRow>
      </Card>

      {doubles.length || blanks.length ? (
        <>
          <SectionHeader title="Doubles and blanks ahead" />
          <Card>
            {doubles.map((l) => (
              <ThemedText key={l} type="small">
                <ThemedText type="smallBold" themeColor="highlight">Double </ThemedText>
                {l}
              </ThemedText>
            ))}
            {blanks.map((l) => (
              <ThemedText key={l} type="small">
                <ThemedText type="smallBold" themeColor="danger">Blank </ThemedText>
                {l}
              </ThemedText>
            ))}
          </Card>
        </>
      ) : null}

      <SectionHeader title="Your chips" />
      {[...data.chips].sort((a, b) => order(a) - order(b)).map((chip) => {
        const v = verdictFor(chip);
        return (
          <Card key={`${chip.name}-${chip.window.start}`} testID={`chip-${chip.name}`}>
            <View style={styles.head}>
              <ThemedText type="headline" style={styles.grow}>
                {chip.label}
              </ThemedText>
              <Pill label={v.label} color={v.color} soft={v.soft} />
            </View>
            {chip.available ? (
              <StatRow>
                <Stat label="Worth now" value={chip.value_now !== null ? chip.value_now.toFixed(1) : '—'} />
                <Stat
                  label="Best ahead"
                  value={chip.best_value !== null ? `${chip.best_value.toFixed(1)}${chip.best_gameweek ? ` · GW${chip.best_gameweek}` : ''}` : '—'}
                />
                <Stat label="Weeks left" value={String(chip.weeks_remaining)} />
              </StatRow>
            ) : null}
            {chip.reasons.slice(0, 3).map((r) => (
              <ThemedText key={r} type="small" themeColor="textSecondary">
                • {r}
              </ThemedText>
            ))}
          </Card>
        );
      })}

      <Banner title="How far to trust this" detail={data.caveat} />
    </>
  );
}

const styles = StyleSheet.create({
  head: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  grow: { flex: 1 },
});
