import { router } from 'expo-router';
import { useMemo, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, View } from 'react-native';

import { Button } from '@/components/button';
import { errorMessage, ErrorView } from '@/components/error-view';
import { Banner, Card, Screen, SectionHeader } from '@/components/screen';
import { Stat, StatRow } from '@/components/stat';
import { TextField } from '@/components/text-field';
import { ThemedText } from '@/components/themed-text';
import { Radius, Spacing } from '@/constants/theme';
import { useDebounced } from '@/hooks/use-debounced';
import { useTheme } from '@/hooks/use-theme';
import { api } from '@/lib/api';
import { refreshSquadDerived, usePlayers, useRecommendation, useTeamId } from '@/lib/query';
import { bankAfter, blockedReason, hitCost, POSITION_NUMBER, squadAfter, type Move, type Pick } from '@/lib/record';

const ORDER: Pick['position'][] = ['GKP', 'DEF', 'MID', 'FWD'];

/**
 * Record transfers already made in FPL. FPL hides them until the deadline, so
 * without this every screen would advise on a squad the manager no longer has.
 */
export default function RecordTransfers() {
  const teamId = useTeamId();
  const rec = useRecommendation(teamId);
  const [moves, setMoves] = useState<Move[]>([]);
  const [selling, setSelling] = useState<Pick | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const squad: Pick[] = useMemo(
    () => (rec.data ? [...rec.data.lineup.starting, ...rec.data.lineup.bench] : []),
    [rec.data],
  );
  const bank = rec.data ? rec.data.bank / 10 : 0;
  const free = rec.data?.free_transfers ?? 0;
  const current = squadAfter(squad, moves);

  async function save() {
    if (!teamId || moves.length === 0) return;
    setSaving(true);
    setError(null);
    try {
      await api.recordTransfers(teamId, moves.map((m) => ({ out: m.out.player_id, in: m.in.player_id })));
      await refreshSquadDerived();
      router.back();
    } catch (e) {
      setError(errorMessage(e));
      setSaving(false);
    }
  }

  if (rec.isError) {
    return (
      <Screen belowHeader>
        <ErrorView error={rec.error} onRetry={() => rec.refetch()} />
      </Screen>
    );
  }
  if (!rec.data) {
    return (
      <Screen belowHeader>
        <ThemedText themeColor="textSecondary">Loading your squad…</ThemedText>
      </Screen>
    );
  }

  if (selling) {
    return (
      <BuyPicker
        selling={selling}
        squad={squad}
        moves={moves}
        bank={bank}
        onCancel={() => setSelling(null)}
        onPick={(buying) => {
          setMoves((m) => [...m, { out: selling, in: buying }]);
          setSelling(null);
        }}
      />
    );
  }

  return (
    <Screen
      testID="record-transfers-screen"
      belowHeader
      footer={
        <Button
          title={moves.length ? `Save ${moves.length} transfer${moves.length > 1 ? 's' : ''}` : 'Pick a player to sell'}
          onPress={save}
          loading={saving}
          disabled={moves.length === 0}
        />
      }>
      <Banner
        tone="info"
        title="Made transfers in FPL already?"
        detail="FPL keeps transfers private until the deadline passes, so tell us what you did and every screen will advise on the squad you actually have. It resets itself once the gameweek starts."
      />

      {moves.length > 0 ? (
        <>
          <SectionHeader title="Your transfers" />
          <Card>
            {moves.map((m, i) => (
              <View key={m.out.player_id} style={styles.moveRow}>
                <View style={styles.grow}>
                  <ThemedText type="smallBold">
                    {m.out.name} → {m.in.name}
                  </ThemedText>
                  <ThemedText type="caption" themeColor="textSecondary">
                    {m.out.position} · £{m.out.price.toFixed(1)}m → £{m.in.price.toFixed(1)}m
                  </ThemedText>
                </View>
                <ThemedText
                  type="smallBold"
                  themeColor="danger"
                  accessibilityRole="button"
                  accessibilityLabel={`Remove ${m.out.name} to ${m.in.name}`}
                  onPress={() => setMoves((all) => all.filter((_, j) => j !== i))}>
                  Remove
                </ThemedText>
              </View>
            ))}
            <StatRow>
              <Stat label="Bank after" value={`£${bankAfter(bank, moves).toFixed(1)}m`} />
              <Stat label="Free transfers" value={String(free)} />
              <Stat
                label="Points hit"
                value={hitCost(moves.length, free) ? `−${hitCost(moves.length, free)}` : 'None'}
                tone={hitCost(moves.length, free) ? 'negative' : undefined}
              />
            </StatRow>
          </Card>
        </>
      ) : null}

      {error ? <ErrorView error={new Error(error)} /> : null}

      <SectionHeader title="Who did you sell?" />
      {ORDER.map((position) => {
        const players = current.filter((p) => p.position === position);
        return (
          <Card key={position} style={styles.list}>
            <ThemedText type="eyebrow" themeColor="textSecondary" style={styles.groupLabel}>
              {position}
            </ThemedText>
            {players.map((p) => {
              const boughtNow = moves.some((m) => m.in.player_id === p.player_id);
              return (
                <PlayerLine
                  key={p.player_id}
                  testID={`sell-${p.player_id}`}
                  player={p}
                  note={boughtNow ? 'Just added' : undefined}
                  disabled={boughtNow}
                  onPress={() => setSelling(p)}
                />
              );
            })}
          </Card>
        );
      })}
    </Screen>
  );
}

function BuyPicker({
  selling,
  squad,
  moves,
  bank,
  onCancel,
  onPick,
}: {
  selling: Pick;
  squad: Pick[];
  moves: Move[];
  bank: number;
  onCancel: () => void;
  onPick: (p: Pick) => void;
}) {
  const [search, setSearch] = useState('');
  const q = useDebounced(search.trim(), 300);
  const budget = bankAfter(bank, moves) + selling.price;
  const players = usePlayers({
    q: q || undefined,
    position: POSITION_NUMBER[selling.position],
    max_price: Math.round(budget * 10) / 10,
    sort: 'xpts',
  });
  const rows = players.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <Screen testID="buy-picker-screen" belowHeader footer={<Button title="Back" variant="secondary" onPress={onCancel} />}>
      <Card variant="inset">
        <ThemedText type="small">
          Replacing <ThemedText type="smallBold">{selling.name}</ThemedText> ({selling.position}, £
          {selling.price.toFixed(1)}m). Up to £{budget.toFixed(1)}m to spend.
        </ThemedText>
      </Card>
      <TextField
        testID="buy-search"
        value={search}
        onChangeText={setSearch}
        placeholder={`Search ${selling.position}s`}
        autoCorrect={false}
        autoCapitalize="none"
        accessibilityLabel="Search players to buy"
      />
      {players.isError ? <ErrorView error={players.error} onRetry={() => players.refetch()} /> : null}
      <Card style={styles.list}>
        {rows.map((r) => {
          const candidate: Pick = { player_id: r.player_id, name: r.name, team: r.team, position: r.position, price: r.price };
          const blocked = blockedReason(candidate, selling, squad, moves, bank);
          return (
            <PlayerLine
              key={r.player_id}
              testID={`buy-${r.player_id}`}
              player={candidate}
              note={blocked ?? (r.xpts !== null ? `${r.xpts.toFixed(1)} xPts next GW` : undefined)}
              disabled={blocked !== null}
              onPress={() => onPick(candidate)}
            />
          );
        })}
        {players.isFetching ? <ActivityIndicator style={styles.spinner} /> : null}
        {players.isSuccess && rows.length === 0 ? (
          <ThemedText themeColor="textSecondary" style={styles.empty}>
            No affordable {selling.position}s match.
          </ThemedText>
        ) : null}
      </Card>
      {players.hasNextPage ? (
        <Button title="Show more" variant="secondary" compact onPress={() => players.fetchNextPage()} />
      ) : null}
    </Screen>
  );
}

function PlayerLine({
  player,
  note,
  disabled = false,
  onPress,
  testID,
}: {
  player: Pick;
  note?: string;
  disabled?: boolean;
  onPress: () => void;
  testID?: string;
}) {
  const theme = useTheme();
  return (
    <Pressable
      testID={testID}
      accessibilityRole="button"
      accessibilityState={{ disabled }}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [
        styles.line,
        { borderTopColor: theme.hairline, opacity: disabled ? 0.45 : 1 },
        pressed && { backgroundColor: theme.backgroundSelected },
      ]}>
      <View style={styles.grow}>
        <ThemedText type="smallBold">{player.name}</ThemedText>
        <ThemedText type="caption" themeColor="textSecondary">
          {player.team} · £{player.price.toFixed(1)}m{note ? ` · ${note}` : ''}
        </ThemedText>
      </View>
      {!disabled ? (
        <ThemedText type="headline" themeColor="textSecondary">
          ›
        </ThemedText>
      ) : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  list: { paddingVertical: Spacing.two, gap: 0 },
  groupLabel: { paddingBottom: 4 },
  line: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.two,
    paddingVertical: 10,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderRadius: Radius.sm,
  },
  moveRow: { flexDirection: 'row', alignItems: 'center', gap: Spacing.two },
  spinner: { padding: Spacing.three },
  empty: { padding: Spacing.three, textAlign: 'center' },
  grow: { flex: 1 },
});
