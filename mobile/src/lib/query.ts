import { QueryCache, QueryClient, useInfiniteQuery, useQuery } from '@tanstack/react-query';

import { api, ApiError, type ExplorerFilters } from '@/lib/api';

// Errors that retrying cannot fix.
const PERMANENT = new Set([400, 401, 402, 403, 404, 409, 422]);

export const queryKeys = {
  me: ['me'] as const,
  entitlement: ['entitlement'] as const,
  gameweek: ['gameweek'] as const,
  recommendation: (managerId: number) => ['recommendation', managerId] as const,
  transfers: (managerId: number, horizon: number) => ['transfers', managerId, horizon] as const,
  captain: (managerId: number) => ['captain', managerId] as const,
  alerts: (managerId: number) => ['alerts', managerId] as const,
  planner: (managerId: number, horizon: number) => ['planner', managerId, horizon] as const,
  newsEvents: ['news-events'] as const,
  priceWatch: ['price-watch'] as const,
  teams: ['teams'] as const,
  players: (filters: ExplorerFilters) => ['players', filters] as const,
  player: (playerId: number) => ['player', playerId] as const,
};

// Everything derived from the squad, refreshed together after the squad changes.
const SQUAD_DERIVED = ['recommendation', 'transfers', 'captain', 'alerts', 'planner'];

export const queryClient = new QueryClient({
  queryCache: new QueryCache({
    onError: (error) => {
      // The server is the authority on access. If it says premium is gone
      // (trial just expired), refetch the entitlement so the paywall shows.
      if (error instanceof ApiError && error.status === 402) {
        queryClient.invalidateQueries({ queryKey: queryKeys.entitlement });
      }
    },
  }),
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      retry: (failures, error) =>
        !(error instanceof ApiError && PERMANENT.has(error.status)) && failures < 2,
    },
  },
});

export function useMe(enabled: boolean) {
  return useQuery({ queryKey: queryKeys.me, queryFn: api.me, enabled });
}

export function useEntitlement(enabled: boolean) {
  return useQuery({ queryKey: queryKeys.entitlement, queryFn: api.entitlements, enabled });
}

export function useAccountQueries(signedIn: boolean) {
  const me = useMe(signedIn);
  const entitlement = useEntitlement(signedIn);
  return { me, entitlement };
}

/** The connected FPL team id, or undefined before the account loads. */
export function useTeamId(): number | undefined {
  return useMe(true).data?.fpl_accounts[0]?.fpl_entry_id;
}

// The optimiser is the slowest and most rate-limited call (6/min), so Home,
// My Team and Transfers share this one cached result.
export function useRecommendation(teamId: number | undefined) {
  return useQuery({
    queryKey: queryKeys.recommendation(teamId ?? 0),
    queryFn: () => api.recommendation(teamId!),
    enabled: !!teamId,
    staleTime: 5 * 60_000,
  });
}

export function useTransfers(teamId: number | undefined, horizon: number, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.transfers(teamId ?? 0, horizon),
    queryFn: () => api.transfers(teamId!, horizon),
    enabled: enabled && !!teamId,
    staleTime: 5 * 60_000,
  });
}

export function useCaptain(teamId: number | undefined) {
  return useQuery({
    queryKey: queryKeys.captain(teamId ?? 0),
    queryFn: () => api.captain(teamId!),
    enabled: !!teamId,
    staleTime: 5 * 60_000,
  });
}

export function usePlanner(teamId: number | undefined, horizon: number) {
  return useQuery({
    queryKey: queryKeys.planner(teamId ?? 0, horizon),
    queryFn: () => api.planner(teamId!, horizon),
    enabled: !!teamId,
    staleTime: 10 * 60_000,
  });
}

export function useAlerts(teamId: number | undefined) {
  return useQuery({
    queryKey: queryKeys.alerts(teamId ?? 0),
    queryFn: () => api.alerts(teamId!),
    enabled: !!teamId,
  });
}

export function useNewsEvents() {
  return useQuery({ queryKey: queryKeys.newsEvents, queryFn: api.newsEvents, staleTime: 5 * 60_000 });
}

export function usePriceWatch() {
  return useQuery({ queryKey: queryKeys.priceWatch, queryFn: api.priceWatch, staleTime: 5 * 60_000 });
}

export function useTeams() {
  return useQuery({ queryKey: queryKeys.teams, queryFn: api.teams, staleTime: 24 * 3_600_000 });
}

const PAGE_SIZE = 30;

export function usePlayers(filters: ExplorerFilters) {
  return useInfiniteQuery({
    queryKey: queryKeys.players(filters),
    queryFn: ({ pageParam }) => api.players(filters, pageParam, PAGE_SIZE),
    initialPageParam: 0,
    getNextPageParam: (last) =>
      last.offset + last.items.length < last.total ? last.offset + last.limit : undefined,
    staleTime: 5 * 60_000,
  });
}

export function usePlayer(playerId: number) {
  return useQuery({
    queryKey: queryKeys.player(playerId),
    queryFn: () => api.player(playerId),
    staleTime: 5 * 60_000,
  });
}

export async function refreshSquadDerived(): Promise<void> {
  await queryClient.invalidateQueries({
    predicate: (q) => SQUAD_DERIVED.includes(String(q.queryKey[0])),
  });
}

export async function refreshAccount(): Promise<void> {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: queryKeys.me }),
    queryClient.invalidateQueries({ queryKey: queryKeys.entitlement }),
  ]);
}
