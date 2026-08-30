const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ── Types (mirror the FastAPI response shapes) ───────────────────────────────

export type PlayerStatus = "a" | "d" | "i" | "s" | "u" | "n";

export interface PlayerSummary {
  id: number;
  name: string;
  /** FPL headshot URL, or null when no image code is known. */
  photo: string | null;
  full_name: string;
  team: string;
  position: "GKP" | "DEF" | "MID" | "FWD" | "UNK";
  price: number;
  total_points: number;
  form: number;
  ep_this: number;
  ep_next: number;
  selected_by_percent: number;
  status: PlayerStatus;
  status_label: string;
  news: string;
  chance_this: number | null;
  minutes: number;
}

export interface SquadPick extends PlayerSummary {
  slot: number;
  is_starting: boolean;
  is_captain: boolean;
  is_vice_captain: boolean;
  multiplier: number;
  unmapped?: boolean;
  /** Set when this player replaced someone via a transfer you recorded. */
  transferred_in?: boolean;
  replaced_player_id?: number | null;
  replaced_name?: string | null;
}

export interface Squad {
  manager_id: number;
  gameweek: number;
  points: number | null;
  total_points: number | null;
  overall_rank: number | null;
  bank: number;
  team_value: number;
  event_transfers: number | null;
  event_transfers_cost: number | null;
  free_transfers: number | null;
  active_chip: string | null;
  squad: SquadPick[];
}

export interface Gameweek {
  id: number;
  name: string;
  deadline_time: string;
  /** True only at season end, when every deadline is behind us. */
  deadline_passed: boolean;
  finished: boolean;
  is_current: boolean;
  is_next: boolean;
  average_entry_score: number;
  highest_score: number;
  /** The gameweek actually being played, which may differ from `id`. */
  current_gameweek: number | null;
}

export interface Manager {
  id: number;
  manager_name: string;
  team_name: string;
  overall_points: number | null;
  overall_rank: number | null;
  gameweek_points: number | null;
  gameweek_rank: number | null;
  bank: number;
  team_value: number;
  total_transfers: number | null;
  started_event: number | null;
}

export interface SyncResult {
  ok: boolean;
  synced?: {
    teams: number;
    gameweeks: number;
    players: number;
    scoring_rules?: string;
  };
  fixtures_synced?: number;
}

export interface ProjectionRow {
  player_id: number;
  name: string;
  team: string;
  position: "GKP" | "DEF" | "MID" | "FWD" | "UNK";
  price: number;
  xpts: number;
  variance: number;
  value: number;
  expected_minutes: number;
  p_start: number;
  p_60_plus: number;
  custom_fdr: number;
  fixture_count: number;
  is_penalty_taker: boolean;
  status: PlayerStatus;
}

export interface RebuildResult {
  model_version: string;
  gameweeks: number[];
  players: number;
  written: number;
  matches_played: number;
}

// ── Decisions ────────────────────────────────────────────────────────────────

export interface PlayerBrief {
  player_id: number;
  name: string;
  team: string;
  position: "GKP" | "DEF" | "MID" | "FWD" | "UNK";
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

export interface TransferPlan {
  transfers: number;
  hit: number;
  out: TransferMove[];
  in: TransferMove[];
  squad_xpts_before: number;
  squad_xpts_after: number;
  net_gain: number;
  bank_after: number;
  note: string;
}

export interface TransferRecommendation {
  action: string;
  horizon_gameweeks: number;
  expected_net_gain: number;
  hit_taken: number;
  confidence: number;
  factors: Record<string, number>;
  weights: Record<string, number>;
  notes: string[];
  plan: TransferPlan;
}

export interface CaptainOption extends PlayerBrief {
  expected_captain_points: number;
  score: number;
  variance: number;
  ownership: number;
  mode: string;
  rationale: string;
}

export interface SquadIssue extends PlayerBrief {
  news: string;
  chance_of_playing: number | null;
  reason: string;
}

export interface FullRecommendation {
  manager_id: number;
  picks_gameweek: number;
  target_gameweek: number;
  bank: number;
  team_value: number;
  free_transfers: number;
  active_chip: string | null;
  players_without_projection: string[];
  gameweek: {
    id: number;
    name: string;
    deadline_time: string;
    is_current: boolean;
  };
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
    mode: string;
    ranking: CaptainOption[];
  };
  squad_issues: SquadIssue[];
  transfer: TransferRecommendation;
  transfer_alternatives: TransferPlan[];
}

export interface NewsEvent {
  id: number;
  detected_at: string;
  event_type: string;
  player_id: number;
  name: string;
  team: string;
  position: string;
  price: number;
  status_before: string | null;
  status_after: string | null;
  status_label: string | null;
  availability_before: number | null;
  availability_after: number | null;
  cause: string | null;
  expected_return: string | null;
  news: string;
  materiality: number;
  requires_review: boolean;
  availability_source: string | null;
}

export interface AlertItem {
  id: number;
  severity: "critical" | "warning" | "info";
  title: string;
  body: string;
  payload: Record<string, unknown> | null;
  player_id: number | null;
  /** false = the player has since left your squad. Hidden by default. */
  still_owned: boolean | null;
  read: boolean;
  created_at: string;
}

export interface PriceWatchItem {
  player_id: number;
  name: string;
  team: string;
  price: number;
  direction: "rise" | "fall";
  percent_to_threshold: number;
  net_transfers_gw: number;
  fpl_projections: unknown;
}


// ── Accuracy feedback ────────────────────────────────────────────────────────

export interface CategoryAccuracy {
  decisions: number;
  hit_rate: number | null;
  mean_error: number;
  mean_absolute_error: number;
  mean_regret: number;
  follow_rate: number | null;
  points_lost_by_overriding: number | null;
}

export interface AccuracySummary {
  manager_id: number;
  gameweeks_scored: number;
  gameweeks?: number[];
  categories: Record<string, CategoryAccuracy>;
  total_regret?: number;
  note?: string;
  interpretation?: Record<string, string>;
}

export interface OutcomeRow {
  gameweek: number;
  kind: string;
  predicted: number;
  actual: number;
  error: number;
  regret: number;
  correct: boolean | null;
  followed: boolean | null;
  override_delta: number | null;
  detail: Record<string, unknown> | null;
  model_version: string;
  scored_at: string;
}

export interface PendingSnapshot {
  snapshot_id: number;
  gameweek: number;
  kind: string;
  predicted_value: number;
  confidence: number;
  model_version: string;
  created_at: string;
  gameweek_finished: boolean;
  scoreable: boolean;
}


// ── Planner ──────────────────────────────────────────────────────────────────

export interface PlanMove {
  player_id: number;
  name: string;
  team: string;
  position: number;
  price: number;
}

export interface PlanNode {
  id: number;
  parent_id: number | null;
  gameweek: number;
  depth: number;
  action: string;
  transfers: number;
  hit: number;
  in: PlanMove[];
  out: PlanMove[];
  bank: number;
  free_transfers: number;
  gw_xpts: number;
  cumulative_xpts: number;
  remaining_value: number;
  pruned: boolean;
  on_best_path: boolean;
}

export interface Plan {
  planner_version: string;
  horizon: number[];
  requested_horizon: number;
  horizon_truncated: boolean;
  truncation_note: string | null;
  beam_width: number;
  optimiser_solves: number;
  manager_id: number;
  starting_bank: number;
  starting_free_transfers: number;
  max_free_transfers: number;
  best_path: {
    total_xpts: number;
    total_hits: number;
    total_transfers: number;
    steps: PlanNode[];
  };
  tree: PlanNode[];
}


// ── Squad state ──────────────────────────────────────────────────────────────

export interface SquadState {
  manager_id: number;
  target_gameweek: number;
  /** `fpl_api` = locked at the last deadline. `manager_override` = you told us. */
  squad_source: "fpl_api" | "manager_override";
  picks_gameweek: number;
  transfers_applied: { out: number; in: number }[] | null;
  /** Set when the squad shown may predate transfers you have already made. */
  stale_warning: string | null;
  bank: number;
  free_transfers: number;
  squad: PlayerSummary[];
}


// ── Dream team ───────────────────────────────────────────────────────────────

export interface DreamPick {
  player_id: number;
  name: string;
  full_name: string;
  team: string;
  position: "GKP" | "DEF" | "MID" | "FWD" | "UNK";
  price: number;
  photo: string | null;
  xpts: number;
  gw_xpts: number;
  value: number;
  p_start: number;
  custom_fdr: number;
  is_starting: boolean;
  is_captain: boolean;
  is_vice_captain: boolean;
  bench_order: number | null;
  position_rank: number | null;
  value_rank: number | null;
  components: Record<string, number>;
  /** Derived from the model's own numbers, not generated prose. */
  reasons: string[];
}

export interface DreamTeam {
  version: string;
  model_version: string;
  solver_status: string;
  gameweeks: number[];
  horizon: number;
  horizon_truncated: boolean;
  budget: number;
  squad_cost: number;
  money_left: number;
  formation: string;
  projected_next_gw: number;
  projected_horizon: number;
  candidates_considered: number;
  captain: string | null;
  vice_captain: string | null;
  starting: DreamPick[];
  bench: DreamPick[];
  explanation_note: string;
}

// ── Fetch helper ─────────────────────────────────────────────────────────────

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new ApiError(
      "Cannot reach the API. Is the backend running on port 8000?",
      0,
    );
  }

  if (!res.ok) {
    // FastAPI puts human-readable errors in `detail`
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      /* response wasn't JSON — keep the generic message */
    }
    throw new ApiError(detail, res.status);
  }

  return res.json() as Promise<T>;
}

// ── Endpoints ────────────────────────────────────────────────────────────────

export interface NotificationStatus {
  manager_id: number;
  /** False when the server has no bot token, so the UI offers nothing that cannot work. */
  available: boolean;
  linked: boolean;
  enabled: boolean;
  linked_at: string | null;
  severities: string[];
}

export interface TelegramLink {
  deep_link: string;
  bot_username: string;
  expires_at: string;
  expires_in_minutes: number;
}

export interface ChipItem {
  name: string;
  label: string;
  available: boolean;
  used_in_gameweek: number | null;
  window: { start: number; end: number };
  weeks_remaining: number;
  value_now: number | null;
  best_value: number | null;
  best_gameweek: number | null;
  baseline: number | null;
  /** use_now | use_soon | consider | hold | used | not_yet | expired | unknown */
  verdict: string;
  confidence: string;
  reasons: string[];
}

export interface ChipAdvice {
  manager_id: number;
  target_gameweek: number;
  budget: number;
  horizon: number[];
  fixture_shape: {
    doubles: Record<string, string[]>;
    blanks: Record<string, string[]>;
    gameweeks_scheduled: number;
    note: string | null;
  };
  squad_this_gameweek: { playing: number; doubling: number; blank: number };
  chips: ChipItem[];
  history_available: boolean;
  caveat: string;
}

export const api = {
  health: () =>
    request<{ status: string; database: string; redis: string }>("/health"),

  gameweek: () => request<Gameweek>("/fpl/gameweek"),

  players: (params: {
    position?: number;
    max_price?: number;
    sort_by?: string;
    limit?: number;
  } = {}) => {
    const q = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined) q.set(k, String(v));
    }
    const qs = q.toString();
    return request<PlayerSummary[]>(`/fpl/players${qs ? `?${qs}` : ""}`);
  },

  manager: (id: number) => request<Manager>(`/fpl/manager/${id}`),

  squad: (id: number, gameweek?: number) =>
    request<Squad>(
      `/fpl/manager/${id}/squad${gameweek ? `?gameweek=${gameweek}` : ""}`,
    ),

  syncBootstrap: () =>
    request<SyncResult>("/fpl/sync/bootstrap", { method: "POST" }),

  syncFixtures: () =>
    request<SyncResult>("/fpl/sync/fixtures", { method: "POST" }),

  // ── Projections ───────────────────────────────────────────────────────────

  projections: (params: {
    gameweek?: number;
    position?: number;
    max_price?: number;
    min_minutes?: number;
    limit?: number;
  } = {}) => {
    const q = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined) q.set(k, String(v));
    }
    const qs = q.toString();
    return request<ProjectionRow[]>(`/projections${qs ? `?${qs}` : ""}`);
  },

  rebuildTeamStrength: () =>
    request<{ teams_updated: number; fixtures_used: number }>(
      "/projections/rebuild/team-strength",
      { method: "POST" },
    ),

  rebuildProjections: (horizon = 5) =>
    request<RebuildResult>(`/projections/rebuild?horizon=${horizon}`, {
      method: "POST",
    }),

  // ── Decisions ─────────────────────────────────────────────────────────────

  // ── News & alerts ─────────────────────────────────────────────────────────

  detectChanges: () =>
    request<{
      first_run: boolean;
      events_detected: number;
      by_type: Record<string, number>;
      needs_review: number;
    }>("/news/detect", { method: "POST" }),

  newsEvents: (opts: { hours?: number; min_materiality?: number; limit?: number } = {}) => {
    const q = new URLSearchParams();
    for (const [k, v] of Object.entries(opts)) {
      if (v !== undefined) q.set(k, String(v));
    }
    const qs = q.toString();
    return request<NewsEvent[]>(`/news/events${qs ? `?${qs}` : ""}`);
  },

  generateAlerts: (managerId: number) =>
    request<{ alerts_created: number; events_considered: number }>(
      `/news/alerts/${managerId}/generate`,
      { method: "POST" },
    ),

  alerts: (managerId: number, unreadOnly = false) =>
    request<AlertItem[]>(
      `/news/alerts/${managerId}${unreadOnly ? "?unread_only=true" : ""}`,
    ),

  markAlertsRead: (managerId: number) =>
    request<{ marked_read: number }>(`/news/alerts/${managerId}/read`, {
      method: "POST",
    }),

  priceWatch: (threshold = 50) =>
    request<PriceWatchItem[]>(`/news/price-watch?threshold=${threshold}`),

  // ── Dream team ────────────────────────────────────────────────────────────

  dreamTeam: (opts: { budget?: number; horizon?: number } = {}) => {
    const q = new URLSearchParams();
    if (opts.budget) q.set("budget", String(opts.budget));
    if (opts.horizon) q.set("horizon", String(opts.horizon));
    const qs = q.toString();
    return request<DreamTeam>(`/dream-team${qs ? `?${qs}` : ""}`);
  },

  // ── Squad state ───────────────────────────────────────────────────────────

  squadState: (managerId: number) =>
    request<SquadState>(`/fpl/manager/${managerId}/squad-state`),

  recordTransfers: (
    managerId: number,
    moves: { out: number; in: number }[],
  ) =>
    request<SquadState>(`/fpl/manager/${managerId}/squad-state/transfers`, {
      method: "POST",
      body: JSON.stringify({ moves }),
    }),

  resetSquadState: (managerId: number) =>
    request<{ cleared: boolean }>(`/fpl/manager/${managerId}/squad-state`, {
      method: "DELETE",
    }),

  // ── Planner ───────────────────────────────────────────────────────────────

  plan: (
    managerId: number,
    opts: { horizon?: number; beam_width?: number } = {},
  ) => {
    const q = new URLSearchParams();
    if (opts.horizon) q.set("horizon", String(opts.horizon));
    if (opts.beam_width) q.set("beam_width", String(opts.beam_width));
    const qs = q.toString();
    return request<Plan>(`/planner/${managerId}${qs ? `?${qs}` : ""}`);
  },

  // ── Accuracy feedback ─────────────────────────────────────────────────────

  accuracy: (managerId: number) =>
    request<AccuracySummary>(`/feedback/${managerId}/accuracy`),

  accuracyHistory: (managerId: number, limit = 30) =>
    request<OutcomeRow[]>(`/feedback/${managerId}/history?limit=${limit}`),

  pendingSnapshots: (managerId: number) =>
    request<{ manager_id: number; pending: PendingSnapshot[]; count: number }>(
      `/feedback/${managerId}/pending`,
    ),

  scoreAll: (managerId: number) =>
    request<{ scored_gameweeks: { gameweek: number; count: number }[] }>(
      `/feedback/${managerId}/score-all`,
      { method: "POST" },
    ),

  recommendation: (
    managerId: number,
    opts: { horizon?: number; captain_mode?: string } = {},
  ) => {
    const q = new URLSearchParams();
    if (opts.horizon) q.set("horizon", String(opts.horizon));
    if (opts.captain_mode) q.set("captain_mode", opts.captain_mode);
    const qs = q.toString();
    return request<FullRecommendation>(
      `/decisions/${managerId}${qs ? `?${qs}` : ""}`,
    );
  },
  notificationStatus: (managerId: number) =>
    request<NotificationStatus>(`/notifications/${managerId}`),

  createTelegramLink: (managerId: number) =>
    request<TelegramLink>(`/notifications/${managerId}/telegram/link`, {
      method: "POST",
    }),

  setTelegramEnabled: (managerId: number, enabled: boolean) =>
    request<NotificationStatus>(
      `/notifications/${managerId}/telegram/enabled?enabled=${enabled}`,
      { method: "POST" },
    ),

  unlinkTelegram: (managerId: number) =>
    request<NotificationStatus & { unlinked: boolean }>(
      `/notifications/${managerId}/telegram`,
      { method: "DELETE" },
    ),

  testTelegram: (managerId: number) =>
    request<{ sent: boolean }>(`/notifications/${managerId}/telegram/test`, {
      method: "POST",
    }),
  chipAdvice: (managerId: number, horizon = 5) =>
    request<ChipAdvice>(`/chips/${managerId}?horizon=${horizon}`),
};
