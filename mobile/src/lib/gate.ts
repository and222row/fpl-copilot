import type { Entitlement, Me } from '@/lib/api';

// Which part of the app the user may see. This only decides navigation: every
// premium endpoint re-checks entitlement on the server, so a tampered client
// that skips the paywall still gets 402s.
export type Gate = 'loading' | 'error' | 'signed-out' | 'needs-team' | 'needs-premium' | 'ready';

interface GateInput {
  authLoading: boolean;
  signedIn: boolean;
  me: Me | undefined;
  entitlement: Entitlement | undefined;
  failed: boolean;
}

export function decideGate({ authLoading, signedIn, me, entitlement, failed }: GateInput): Gate {
  if (authLoading) return 'loading';
  if (!signedIn) return 'signed-out';
  if (failed) return 'error';
  if (!me || !entitlement) return 'loading';
  if (me.fpl_accounts.length === 0) return 'needs-team';
  if (!entitlement.premium) return 'needs-premium';
  return 'ready';
}
