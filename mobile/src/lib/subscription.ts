import type { Entitlement } from '@/lib/api';

const date = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString() : '');
const planName = (e: Entitlement) => (e.plan === 'ANNUAL' ? 'Annual' : e.plan === 'MONTHLY' ? 'Monthly' : 'Pro');

/** One line describing where the user stands, from the server's entitlement. */
export function describeEntitlement(e: Entitlement): string {
  switch (e.status) {
    case 'TRIALING':
      return `Free trial until ${date(e.trial_ends_at)}`;
    case 'ACTIVE':
      return e.subscription_ends_at ? `${planName(e)} plan · renews ${date(e.subscription_ends_at)}` : `${planName(e)} plan`;
    case 'CANCELED':
      return `${planName(e)} plan · cancelled, access until ${date(e.subscription_ends_at)}`;
    case 'PAST_DUE':
      return `${planName(e)} plan · payment problem`;
    case 'EXPIRED':
      return e.provider && e.provider !== 'TRIAL' ? 'Subscription ended' : 'Free trial ended';
    case 'NONE':
      return 'No subscription';
  }
}

/** Store subscriptions are managed in the store, not here. */
export function managedInStore(e: Entitlement): boolean {
  return (e.provider === 'APPLE' || e.provider === 'GOOGLE') && e.status !== 'EXPIRED';
}
