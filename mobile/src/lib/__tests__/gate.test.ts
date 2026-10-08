import type { Entitlement, Me } from '@/lib/api';
import { decideGate } from '@/lib/gate';

const team = { fpl_entry_id: 1, team_name: 'T', manager_name: 'M', connected_at: '' };
const me = (teams = [team]): Me => ({
  id: 'u',
  email: null,
  phone: null,
  providers: ['google'],
  fpl_accounts: teams,
});
const ent = (premium: boolean, status: Entitlement['status'] = premium ? 'TRIALING' : 'EXPIRED'): Entitlement => ({
  premium,
  status,
  plan: null,
  provider: null,
  trial_started_at: null,
  trial_ends_at: null,
  subscription_ends_at: null,
});

const base = { authLoading: false, signedIn: true, me: me(), entitlement: ent(true), failed: false };

test('waits for the stored session before deciding anything', () => {
  expect(decideGate({ ...base, authLoading: true })).toBe('loading');
});

test('signed out goes to sign-in even if stale account data is cached', () => {
  expect(decideGate({ ...base, signedIn: false })).toBe('signed-out');
});

test('waits for both account and entitlement', () => {
  expect(decideGate({ ...base, me: undefined })).toBe('loading');
  expect(decideGate({ ...base, entitlement: undefined })).toBe('loading');
});

test('a failed account load is an error, not a paywall', () => {
  expect(decideGate({ ...base, me: undefined, failed: true })).toBe('error');
});

test('no connected team means onboarding, whatever the entitlement says', () => {
  expect(decideGate({ ...base, me: me([]), entitlement: ent(true) })).toBe('needs-team');
});

test('team but no premium shows the paywall', () => {
  expect(decideGate({ ...base, entitlement: ent(false) })).toBe('needs-premium');
  expect(decideGate({ ...base, entitlement: ent(false, 'NONE') })).toBe('needs-premium');
});

test('team and premium reach the app', () => {
  expect(decideGate(base)).toBe('ready');
});
