import { config } from '@/lib/config';
import { supabase } from '@/lib/supabase';

// ── Types (mirror backend/app responses) ─────────────────────────────────────

export type SubscriptionStatus =
  | 'NONE'
  | 'TRIALING'
  | 'ACTIVE'
  | 'PAST_DUE'
  | 'CANCELED'
  | 'EXPIRED';

export interface Entitlement {
  premium: boolean;
  status: SubscriptionStatus;
  plan: 'MONTHLY' | 'ANNUAL' | null;
  provider: string | null;
  trial_started_at: string | null;
  trial_ends_at: string | null;
  subscription_ends_at: string | null;
}

export interface FplAccount {
  fpl_entry_id: number;
  team_name: string;
  manager_name: string;
  connected_at: string;
}

export interface Me {
  id: string;
  email: string | null;
  phone: string | null;
  providers: string[];
  fpl_accounts: FplAccount[];
}

export interface PendingConnection {
  status: 'verification_required';
  fpl_entry_id: number;
  team_name: string;
  code: string;
  expires_at: string;
  attempts_remaining: number;
  instructions: string;
}

export type StartConnectionResult = PendingConnection | ({ status: 'connected' } & FplAccount);

export interface VerifiedConnection extends FplAccount {
  status: 'connected';
  trial_started: boolean;
  entitlement: Entitlement;
}

export interface Gameweek {
  id: number;
  name: string;
  deadline_time: string;
  deadline_passed: boolean;
  current_gameweek: number | null;
}

export type PlayerStatus = 'a' | 'd' | 'i' | 's' | 'u' | 'n';
export type Position = 'GKP' | 'DEF' | 'MID' | 'FWD' | 'UNK';

export interface PlayerBrief {
  player_id: number;
  name: string;
  team: string;
  position: Position;
  /** £m */
  price: number;
  xpts: number;
  p_start: number;
  status: PlayerStatus;
}

export interface TransferMove {
  player_id: number;
  name: string;
  team: string;
  position: string;
  price: number;
  horizon_xpts: number;
  status: PlayerStatus;
}

export interface TransferRecommendation {
  action: string;
  horizon_gameweeks: number;
  expected_net_gain: number;
  hit_taken: number;
  confidence: number;
  notes: string[];
  plan: {
    transfers: number;
    hit: number;
    out: TransferMove[];
    in: TransferMove[];
    net_gain: number;
    /** tenths of £m */
    bank_after: number;
    note: string;
  };
}

export interface SquadIssue extends PlayerBrief {
  news: string;
  chance_of_playing: number | null;
  reason: string;
}

export interface Recommendation {
  manager_id: number;
  /** tenths of £m */
  bank: number;
  free_transfers: number;
  stale_warning?: string | null;
  gameweek: { id: number; name: string; deadline_time: string; deadline_passed: boolean };
  lineup: { formation: string; starting_xpts: number; projected_total: number };
  captain: { pick: PlayerBrief | null; vice: PlayerBrief | null };
  squad_issues: SquadIssue[];
  transfer: TransferRecommendation;
}

export interface AlertItem {
  id: number;
  severity: 'critical' | 'warning' | 'info';
  title: string;
  body: string;
  player_id: number | null;
  still_owned: boolean | null;
  read: boolean;
  created_at: string;
}

// ── Transport ────────────────────────────────────────────────────────────────

export type ApiErrorCode =
  | 'NETWORK'
  | 'TIMEOUT'
  | 'UNAUTHORIZED'
  | 'PREMIUM_REQUIRED'
  | 'RATE_LIMITED'
  | 'SERVER'
  | string;

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: ApiErrorCode,
    message: string,
    readonly detail?: unknown,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

const DEFAULT_TIMEOUT_MS = 20_000;

interface RequestOptions {
  method?: 'GET' | 'POST' | 'DELETE';
  body?: unknown;
  timeoutMs?: number;
}

function parseError(status: number, payload: unknown): ApiError {
  const detail = (payload as { detail?: unknown } | null)?.detail;
  if (detail && typeof detail === 'object' && 'code' in detail) {
    const d = detail as { code: string; message?: string };
    return new ApiError(status, d.code, d.message ?? 'Request failed', detail);
  }
  const message = typeof detail === 'string' ? detail : 'Something went wrong. Please try again.';
  const code =
    status === 401
      ? 'UNAUTHORIZED'
      : status === 402
        ? 'PREMIUM_REQUIRED'
        : status === 429
          ? 'RATE_LIMITED'
          : status >= 500
            ? 'SERVER'
            : `HTTP_${status}`;
  return new ApiError(status, code, message, detail);
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, timeoutMs = DEFAULT_TIMEOUT_MS } = options;
  // getSession refreshes an expired access token before handing it over.
  const token = (await supabase.auth.getSession()).data.session?.access_token;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let response: Response;
  try {
    response = await fetch(`${config.apiUrl}/api/v1${path}`, {
      method,
      signal: controller.signal,
      headers: {
        Accept: 'application/json',
        ...(body !== undefined && { 'Content-Type': 'application/json' }),
        ...(token && { Authorization: `Bearer ${token}` }),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    if (controller.signal.aborted) {
      throw new ApiError(0, 'TIMEOUT', 'The server took too long to respond.');
    }
    throw new ApiError(0, 'NETWORK', 'No connection. Check your internet and try again.');
  } finally {
    clearTimeout(timer);
  }

  const payload = response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) {
    if (response.status === 401 && token) {
      // The server rejected a token we believed valid (revoked or expired past
      // refresh). Drop it locally so the app returns to sign-in.
      await supabase.auth.signOut({ scope: 'local' });
    }
    throw parseError(response.status, payload);
  }
  return payload as T;
}

export const api = {
  me: () => request<Me>('/me'),
  entitlements: () => request<Entitlement>('/me/entitlements'),
  startConnection: (fplEntryId: number) =>
    request<StartConnectionResult>('/me/fpl-accounts', {
      method: 'POST',
      body: { fpl_entry_id: fplEntryId },
    }),
  verifyConnection: (fplEntryId: number) =>
    request<VerifiedConnection>(`/me/fpl-accounts/${fplEntryId}/verify`, { method: 'POST' }),
  disconnect: (fplEntryId: number) =>
    request<null>(`/me/fpl-accounts/${fplEntryId}`, { method: 'DELETE' }),

  gameweek: () => request<Gameweek>('/fpl/gameweek'),
  // The optimiser can take several seconds on a cold server.
  recommendation: (managerId: number) =>
    request<Recommendation>(`/decisions/${managerId}`, { timeoutMs: 60_000 }),
  alerts: (managerId: number) => request<AlertItem[]>(`/news/alerts/${managerId}`),
};
