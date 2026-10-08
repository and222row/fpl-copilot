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

export interface ExplainedMove {
  out: TransferMove;
  in: TransferMove;
  xpts_gain: number;
  reasons: string[];
}

export interface TransferPlan {
  transfers: number;
  hit: number;
  out: TransferMove[];
  in: TransferMove[];
  squad_xpts_before: number;
  squad_xpts_after: number;
  net_gain: number;
  /** tenths of £m */
  bank_after: number;
  note: string;
  moves: ExplainedMove[];
}

export interface TransferRecommendation {
  action: string;
  horizon_gameweeks: number;
  expected_net_gain: number;
  hit_taken: number;
  confidence: number;
  notes: string[];
  plan: TransferPlan;
}

export interface SquadIssue extends PlayerBrief {
  news: string;
  chance_of_playing: number | null;
  reason: string;
}

export interface CaptainOption extends PlayerBrief {
  expected_captain_points: number;
  ownership: number;
  rationale: string;
}

export type CaptainMode = 'safe' | 'balanced' | 'differential';

/** Which squad the advice is about; FPL cannot show pending transfers. */
export interface SquadMeta {
  /** tenths of £m */
  bank: number;
  free_transfers: number;
  squad_source: 'fpl_api' | 'manager_override';
  transfers_applied: { out: number; in: number }[] | null;
  stale_warning: string | null;
}

export interface Recommendation extends SquadMeta {
  manager_id: number;
  gameweek: { id: number; name: string; deadline_time: string; deadline_passed: boolean };
  lineup: {
    formation: string;
    starting_xpts: number;
    bench_xpts: number;
    projected_total: number;
    starting: PlayerBrief[];
    bench: (PlayerBrief & { bench_order: number })[];
  };
  captain: {
    pick: PlayerBrief | null;
    vice: PlayerBrief | null;
    ranking: CaptainOption[];
  };
  squad_issues: SquadIssue[];
  transfer: TransferRecommendation;
  transfer_alternatives: TransferPlan[];
}

export interface TransfersResponse extends SquadMeta {
  horizon: number[];
  recommendation: TransferRecommendation;
  alternatives: TransferPlan[];
}

export interface CaptainResponse {
  modes: Record<CaptainMode, { ranking: CaptainOption[]; confidence: { confidence: number } | null }>;
}

export interface Team {
  id: number;
  name: string;
  short_name: string;
}

export interface ExplorerFilters {
  q?: string;
  position?: number;
  team_id?: number;
  max_price?: number;
  max_fdr?: number;
  min_p_start?: number;
  max_ownership?: number;
  availability?: 'fit' | 'doubtful' | 'out';
  sort?: 'xpts' | 'value' | 'form' | 'price' | 'ownership' | 'total_points' | 'p_start';
}

export interface ExplorerRow {
  player_id: number;
  name: string;
  photo: string | null;
  team: string;
  team_id: number;
  position: Position;
  price: number;
  status: PlayerStatus;
  chance: number | null;
  news: string;
  form: number;
  total_points: number;
  selected_by_percent: number;
  xpts: number | null;
  expected_minutes: number | null;
  p_start: number | null;
  fdr: number | null;
}

export interface ExplorerPage {
  gameweek: number;
  total: number;
  offset: number;
  limit: number;
  items: ExplorerRow[];
}

export interface PlayerDetail {
  id: number;
  name: string;
  full_name: string;
  photo: string | null;
  team: string;
  team_full: string;
  position: Position;
  price: number;
  status: PlayerStatus;
  status_label: string;
  news: string;
  chance_this: number | null;
  form: number;
  total_points: number;
  selected_by_percent: number;
  minutes: number;
  starts: number;
  goals: number;
  assists: number;
  clean_sheets: number;
  bonus: number;
  expected_goals: number;
  expected_assists: number;
  price_change: { percent_to_threshold: number; net_transfers_gw: number };
  projection: {
    total_xpts: number;
    gameweeks: {
      gameweek: number;
      xpts: number;
      expected_minutes: number;
      p_start: number;
      fdr: number;
      fixtures: { opponent: string | null; is_home: boolean; fdr: number }[];
    }[];
  };
  recent:
    | {
        gameweek: number;
        opponent: string | null;
        is_home: boolean;
        minutes: number;
        points: number;
        goals: number;
        assists: number;
        bonus: number;
      }[]
    | null;
  availability_news: PlayerNews[];
}

export interface PlayerNews {
  detected_at: string;
  event_type: string;
  status: string | null;
  availability: number | null;
  cause: string | null;
  expected_return: string | null;
  text: string;
  source: string;
}

export interface PlanPlayer {
  player_id: number;
  name: string;
  team: string;
  /** 1 GKP, 2 DEF, 3 MID, 4 FWD */
  position: number;
  price: number;
  price_change_percent: number;
}

export interface PlanStep {
  id: number;
  parent_id: number | null;
  gameweek: number;
  depth: number;
  action: string;
  transfers: number;
  hit: number;
  in: PlanPlayer[];
  out: PlanPlayer[];
  /** £m, after this gameweek's moves */
  bank: number;
  /** available for the following gameweek */
  free_transfers: number;
  gw_xpts: number;
  cumulative_xpts: number;
  remaining_value: number;
  pruned: boolean;
  on_best_path: boolean;
}

export interface Plan {
  horizon: number[];
  requested_horizon: number;
  horizon_truncated: boolean;
  truncation_note: string | null;
  best_path: { total_xpts: number; total_hits: number; total_transfers: number; steps: PlanStep[] };
  tree: PlanStep[];
  starting_bank: number;
  starting_free_transfers: number;
  squad_source: 'fpl_api' | 'manager_override';
}

export type NewsCategory =
  | 'INJURY'
  | 'RETURN_FROM_INJURY'
  | 'SUSPENSION'
  | 'TRANSFER'
  | 'PRICE_CHANGE'
  | 'OTHER';

export interface NewsEvent {
  id: number;
  detected_at: string;
  event_type: string;
  player_id: number;
  name: string;
  team: string;
  position: Position;
  price: number;
  status_label: string | null;
  cause: string | null;
  expected_return: string | null;
  news: string;
  materiality: number;
  category: NewsCategory;
  direction: 'positive' | 'negative' | 'neutral';
  confidence: 'high' | 'low';
  source: string;
  source_label: string;
}

export interface PriceWatchItem {
  player_id: number;
  name: string;
  team: string;
  price: number;
  direction: 'rise' | 'fall';
  percent_to_threshold: number;
  net_transfers_gw: number;
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
  // Asks the server to confirm with RevenueCat after a purchase or restore.
  // Sends nothing: the server reads the signed-in user's own state.
  syncBilling: () => request<Entitlement>('/billing/sync', { method: 'POST' }),
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
  transfers: (managerId: number, horizon: number) =>
    request<TransfersResponse>(`/decisions/${managerId}/transfers?horizon=${horizon}`, {
      timeoutMs: 60_000,
    }),
  captain: (managerId: number) => request<CaptainResponse>(`/decisions/${managerId}/captain`),
  alerts: (managerId: number) => request<AlertItem[]>(`/news/alerts/${managerId}`),
  markAlertsRead: (managerId: number) =>
    request<{ marked_read: number }>(`/news/alerts/${managerId}/read`, { method: 'POST' }),
  newsEvents: () => request<NewsEvent[]>('/news/events?hours=168&limit=100'),
  priceWatch: () => request<PriceWatchItem[]>('/news/price-watch'),
  // Beam search runs the optimiser at every node: seconds, not milliseconds.
  planner: (managerId: number, horizon: number) =>
    request<Plan>(`/planner/${managerId}?horizon=${horizon}`, { timeoutMs: 90_000 }),

  recordTransfers: (managerId: number, moves: { out: number; in: number }[]) =>
    request<{ free_transfers: number }>(`/fpl/manager/${managerId}/squad-state/transfers`, {
      method: 'POST',
      body: { moves },
    }),
  resetRecordedTransfers: (managerId: number) =>
    request<{ cleared: boolean }>(`/fpl/manager/${managerId}/squad-state`, { method: 'DELETE' }),

  teams: () => request<Team[]>('/fpl/teams'),
  players: (filters: ExplorerFilters, offset: number, limit = 30) => {
    const qs = new URLSearchParams({ offset: String(offset), limit: String(limit) });
    for (const [k, v] of Object.entries(filters)) {
      if (v !== undefined && v !== '') qs.set(k, String(v));
    }
    return request<ExplorerPage>(`/players?${qs.toString()}`);
  },
  player: (playerId: number) => request<PlayerDetail>(`/players/${playerId}`),
};
