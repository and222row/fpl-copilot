import { request } from "@/lib/api";

// Mirrors backend/app/routers/admin.py. Every call needs an admin account
// with a verified second factor; the server checks both on every request.

export type AccessStatus = "TRIALING" | "ACTIVE" | "PAST_DUE" | "CANCELED" | "EXPIRED" | "NONE" | "GRANTED";

export interface Overview {
  users: number;
  teams_connected: number;
  statuses: Partial<Record<AccessStatus, number>>;
  subscribers: { MONTHLY: number; ANNUAL: number };
  signups: { "7d": number; "30d": number };
  trial_conversion_30d: { ended: number; converted: number };
  push_devices: number;
  telegram_linked: number;
  live_alerts_off: number;
  advice_cached: number;
  last_refresh: { at: string | null; ok: boolean; seconds: number } | null;
}

export interface UserRow {
  id: string;
  /** Masked in the list: "an***@gmail.com". */
  email: string | null;
  providers: string[];
  team: { fpl_entry_id: number; team_name: string; verified: boolean } | null;
  status: AccessStatus;
  premium: boolean;
  plan: string | null;
  provider: string | null;
  trial_ends_at: string | null;
  subscription_ends_at: string | null;
  created_at: string | null;
  last_sign_in_at: string | null;
  last_seen_at: string | null;
  devices: number;
  telegram: boolean;
}

export interface UserPage {
  total: number;
  page: number;
  page_size: number;
  users: UserRow[];
}

export interface AuditEntry {
  id: number;
  admin_user_id: string;
  action: string;
  target_user_id: string | null;
  reason: string;
  detail: Record<string, unknown> | null;
  created_at: string | null;
}

export interface UserDetail extends Omit<UserRow, "team" | "devices" | "telegram"> {
  /** In full on this page. */
  email: string | null;
  is_admin: boolean;
  banned_until: string | null;
  in_auth: boolean;
  teams: {
    fpl_entry_id: number;
    team_name: string;
    manager_name: string;
    connected_at: string | null;
    verified_at: string | null;
    telegram: boolean;
  }[];
  subscription: {
    provider: string;
    status: string;
    plan: string | null;
    product_id: string;
    expires_at: string | null;
    is_sandbox: boolean;
    synced_at: string | null;
    granted: boolean;
  } | null;
  trial: { fpl_entry_id: number; started_at: string | null; ends_at: string | null } | null;
  devices: { platform: string; last_seen_at: string | null }[];
  notifications: Record<"availability" | "price" | "deadline" | "live", boolean>;
  billing_events: { type: string; at: string | null }[];
  pushes: { kind: string; key: string; sent_at: string | null }[];
  audit: AuditEntry[];
}

const post = <T>(path: string, body: object) => request<T>(path, { method: "POST", body: JSON.stringify(body) });

export const adminApi = {
  overview: () => request<Overview>("/admin/overview"),
  users: (q: string, status: AccessStatus | "", page: number) => {
    const params = new URLSearchParams({ q, page: String(page) });
    if (status) params.set("status", status);
    return request<UserPage>(`/admin/users?${params}`);
  },
  user: (id: string) => request<UserDetail>(`/admin/users/${id}`),
  audit: () => request<{ entries: AuditEntry[] }>("/admin/audit"),
  grant: (id: string, days: number, reason: string) => post<{ until: string }>(`/admin/users/${id}/grant`, { days, reason }),
  endGrant: (id: string, reason: string) => post<{ ok: true }>(`/admin/users/${id}/end-grant`, { reason }),
  releaseTeam: (id: string, reason: string) => post<{ released: number[] }>(`/admin/users/${id}/release-team`, { reason }),
  syncBilling: (id: string, reason: string) =>
    post<{ status: string | null; provider: string | null }>(`/admin/users/${id}/sync-billing`, { reason }),
  testPush: (id: string, reason: string) => post<{ devices: number; sent: number }>(`/admin/users/${id}/test-push`, { reason }),
  deleteUser: (id: string, reason: string) =>
    request<null>(`/admin/users/${id}`, { method: "DELETE", body: JSON.stringify({ reason }) }),
};

export function when(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString(undefined, { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}
