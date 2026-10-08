import { QueryCache, QueryClient, useQuery } from '@tanstack/react-query';

import { api, ApiError } from '@/lib/api';

// Errors that retrying cannot fix.
const PERMANENT = new Set([400, 401, 402, 403, 404, 409, 422]);

export const queryKeys = {
  me: ['me'] as const,
  entitlement: ['entitlement'] as const,
  gameweek: ['gameweek'] as const,
  recommendation: (managerId: number) => ['recommendation', managerId] as const,
  alerts: (managerId: number) => ['alerts', managerId] as const,
};

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

export async function refreshAccount(): Promise<void> {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: queryKeys.me }),
    queryClient.invalidateQueries({ queryKey: queryKeys.entitlement }),
  ]);
}
