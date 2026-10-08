import { router } from 'expo-router';
import { useMemo, useState } from 'react';
import { ActivityIndicator, FlatList, Pressable, StyleSheet, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Button } from '@/components/button';
import { ChipGroup } from '@/components/chip';
import { ErrorView } from '@/components/error-view';
import { PlayerPhoto } from '@/components/player-photo';
import { ThemedText } from '@/components/themed-text';
import { MaxContentWidth, Spacing } from '@/constants/theme';
import { useDebounced } from '@/hooks/use-debounced';
import { useTheme } from '@/hooks/use-theme';
import type { ExplorerFilters, ExplorerRow } from '@/lib/api';
import { usePlayers, useTeams } from '@/lib/query';
import { availabilityLabel } from '@/lib/squad';

type Sort = NonNullable<ExplorerFilters['sort']>;

const POSITIONS = [
  { label: 'All', value: undefined },
  { label: 'GK', value: 1 },
  { label: 'DEF', value: 2 },
  { label: 'MID', value: 3 },
  { label: 'FWD', value: 4 },
] as const;

const SORTS: readonly { label: string; value: Sort }[] = [
  { label: 'xPts', value: 'xpts' },
  { label: 'Value', value: 'value' },
  { label: 'Form', value: 'form' },
  { label: 'Price', value: 'price' },
  { label: 'Owned', value: 'ownership' },
  { label: 'Start %', value: 'p_start' },
];

const PRICES = [
  { label: 'Any price', value: undefined },
  { label: '≤ £5.0m', value: 5 },
  { label: '≤ £6.5m', value: 6.5 },
  { label: '≤ £8.0m', value: 8 },
  { label: '≤ £10.0m', value: 10 },
] as const;

const AVAILABILITY = [
  { label: 'Any status', value: undefined },
  { label: 'Fit', value: 'fit' },
  { label: 'Doubtful', value: 'doubtful' },
] as const;

const START = [
  { label: 'Any minutes', value: undefined },
  { label: '60%+ to start', value: 0.6 },
  { label: '80%+ to start', value: 0.8 },
] as const;

const FIXTURES = [
  { label: 'Any fixture', value: undefined },
  { label: 'Easy fixture', value: 2.5 },
] as const;

const OWNERSHIP = [
  { label: 'Any ownership', value: undefined },
  { label: 'Under 10%', value: 10 },
] as const;

const MAX_COMPARE = 2;

export default function Players() {
  const theme = useTheme();
  const teams = useTeams();
  const [search, setSearch] = useState('');
  const q = useDebounced(search.trim(), 300);
  const [position, setPosition] = useState<number | undefined>();
  const [sort, setSort] = useState<Sort>('xpts');
  const [showFilters, setShowFilters] = useState(false);
  const [teamId, setTeamId] = useState<number | undefined>();
  const [maxPrice, setMaxPrice] = useState<number | undefined>();
  const [availability, setAvailability] = useState<ExplorerFilters['availability']>();
  const [minStart, setMinStart] = useState<number | undefined>();
  const [maxFdr, setMaxFdr] = useState<number | undefined>();
  const [maxOwnership, setMaxOwnership] = useState<number | undefined>();
  const [comparing, setComparing] = useState(false);
  const [selected, setSelected] = useState<number[]>([]);

  const filters: ExplorerFilters = {
    q: q || undefined,
    position,
    sort,
    team_id: teamId,
    max_price: maxPrice,
    availability,
    min_p_start: minStart,
    max_fdr: maxFdr,
    max_ownership: maxOwnership,
  };
  const players = usePlayers(filters);
  const items = players.data?.pages.flatMap((p) => p.items) ?? [];
  const total = players.data?.pages[0]?.total;
  const activeFilters = [teamId, maxPrice, availability, minStart, maxFdr, maxOwnership].filter(
    (v) => v !== undefined,
  ).length;

  const clubs = useMemo(
    () => [
      { label: 'All clubs', value: undefined as number | undefined },
      ...(teams.data ?? []).map((t) => ({ label: t.short_name, value: t.id as number | undefined })),
    ],
    [teams.data],
  );

  function onPress(row: ExplorerRow) {
    if (!comparing) {
      router.push({ pathname: '/player/[id]', params: { id: String(row.player_id) } });
      return;
    }
    setSelected((s) =>
      s.includes(row.player_id)
        ? s.filter((id) => id !== row.player_id)
        : s.length < MAX_COMPARE
          ? [...s, row.player_id]
          : s,
    );
  }

  const header = (
    <View style={styles.header}>
      <ThemedText type="subtitle" accessibilityRole="header">
        Players
      </ThemedText>
      <TextInput
        testID="players-search"
        value={search}
        onChangeText={setSearch}
        placeholder="Search players"
        placeholderTextColor={theme.textSecondary}
        autoCorrect={false}
        autoCapitalize="none"
        clearButtonMode="while-editing"
        returnKeyType="search"
        accessibilityLabel="Search players"
        style={[styles.search, { color: theme.text, backgroundColor: theme.backgroundElement }]}
      />
      <ChipGroup options={POSITIONS} value={position as 1 | 2 | 3 | 4 | undefined} onChange={setPosition} />
      <ChipGroup options={SORTS} value={sort} onChange={setSort} />
      <View style={styles.toolbar}>
        <Pressable accessibilityRole="button" onPress={() => setShowFilters((s) => !s)}>
          <ThemedText type="linkPrimary">
            {showFilters ? 'Hide filters' : `Filters${activeFilters ? ` (${activeFilters})` : ''}`}
          </ThemedText>
        </Pressable>
        <Pressable
          accessibilityRole="button"
          onPress={() => {
            setComparing((c) => !c);
            setSelected([]);
          }}>
          <ThemedText type="linkPrimary">{comparing ? 'Cancel compare' : 'Compare'}</ThemedText>
        </Pressable>
      </View>
      {showFilters ? (
        <View style={styles.filters}>
          <ChipGroup options={clubs} value={teamId} onChange={setTeamId} />
          <ChipGroup options={PRICES} value={maxPrice as number | undefined} onChange={setMaxPrice} />
          <ChipGroup options={AVAILABILITY} value={availability} onChange={setAvailability} />
          <ChipGroup options={START} value={minStart as number | undefined} onChange={setMinStart} />
          <ChipGroup options={FIXTURES} value={maxFdr as number | undefined} onChange={setMaxFdr} />
          <ChipGroup options={OWNERSHIP} value={maxOwnership as number | undefined} onChange={setMaxOwnership} />
        </View>
      ) : null}
      {comparing ? (
        <ThemedText type="small" themeColor="textSecondary">
          Pick two players to compare ({selected.length}/{MAX_COMPARE}).
        </ThemedText>
      ) : null}
      {total !== undefined ? (
        <ThemedText type="small" themeColor="textSecondary">
          {total} players · xPts for the next gameweek
        </ThemedText>
      ) : null}
      {players.isError ? <ErrorView error={players.error} onRetry={() => players.refetch()} /> : null}
    </View>
  );

  return (
    <SafeAreaView testID="players-screen" style={[styles.safe, { backgroundColor: theme.background }]} edges={['top', 'left', 'right']}>
      <FlatList
        data={items}
        keyExtractor={(p) => String(p.player_id)}
        ListHeaderComponent={header}
        renderItem={({ item }) => (
          <PlayerRow row={item} selected={selected.includes(item.player_id)} onPress={() => onPress(item)} />
        )}
        onEndReached={() => players.hasNextPage && !players.isFetchingNextPage && players.fetchNextPage()}
        onEndReachedThreshold={0.5}
        ListFooterComponent={players.isFetching ? <ActivityIndicator style={styles.footer} /> : null}
        ListEmptyComponent={
          players.isSuccess ? (
            <ThemedText themeColor="textSecondary" style={styles.footer}>
              No players match these filters.
            </ThemedText>
          ) : null
        }
        refreshing={players.isRefetching && !players.isFetchingNextPage}
        onRefresh={() => players.refetch()}
        keyboardShouldPersistTaps="handled"
        contentContainerStyle={styles.list}
      />
      {comparing && selected.length === MAX_COMPARE ? (
        <View style={styles.compareBar}>
          <Button
            title="Compare"
            onPress={() =>
              router.push({ pathname: '/compare', params: { a: String(selected[0]), b: String(selected[1]) } })
            }
          />
        </View>
      ) : null}
    </SafeAreaView>
  );
}

function PlayerRow({ row, selected, onPress }: { row: ExplorerRow; selected: boolean; onPress: () => void }) {
  const theme = useTheme();
  const availability = availabilityLabel(row.status, row.chance);
  return (
    <Pressable
      testID={`player-row-${row.player_id}`}
      accessibilityRole="button"
      accessibilityState={{ selected }}
      onPress={onPress}
      style={[styles.row, { backgroundColor: selected ? theme.backgroundSelected : 'transparent' }]}>
      <PlayerPhoto uri={row.photo} position={row.position} size={36} />
      <View style={styles.grow}>
        <ThemedText type="smallBold" numberOfLines={1}>
          {row.name}
        </ThemedText>
        <ThemedText type="small" themeColor="textSecondary">
          {row.team} · {row.position} · £{row.price.toFixed(1)}m · {row.selected_by_percent.toFixed(1)}%
        </ThemedText>
        {availability ? (
          <ThemedText type="small" themeColor={row.status === 'd' ? 'warning' : 'danger'}>
            {availability}
          </ThemedText>
        ) : null}
      </View>
      <View style={styles.right}>
        <ThemedText type="smallBold">{row.xpts !== null ? row.xpts.toFixed(1) : '—'}</ThemedText>
        <ThemedText type="small" themeColor="textSecondary">
          {row.p_start !== null ? `${Math.round(row.p_start * 100)}% start` : `form ${row.form}`}
        </ThemedText>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1 },
  list: { width: '100%', maxWidth: MaxContentWidth, alignSelf: 'center', paddingBottom: Spacing.six },
  header: { padding: Spacing.three, gap: Spacing.two },
  search: { borderRadius: 12, paddingHorizontal: Spacing.three, paddingVertical: Spacing.two, fontSize: 16 },
  toolbar: { flexDirection: 'row', justifyContent: 'space-between' },
  filters: { gap: Spacing.two },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.three,
    paddingHorizontal: Spacing.three,
    paddingVertical: Spacing.two,
  },
  grow: { flex: 1 },
  right: { alignItems: 'flex-end' },
  footer: { padding: Spacing.four, textAlign: 'center' },
  compareBar: { padding: Spacing.three },
});
