"use client";

import type { Session } from "@supabase/supabase-js";
import { useCallback, useEffect, useState } from "react";
import { MfaGate } from "@/components/admin/MfaGate";
import { SignIn } from "@/components/AccountGate";
import { adminApi, when, type AccessStatus, type AuditEntry, type Overview, type UserDetail, type UserPage } from "@/lib/admin";
import { ApiError } from "@/lib/api";
import { supabase, supabaseConfigured } from "@/lib/supabase";
import { BTN_PRIMARY, BTN_SECONDARY, SELECT } from "@/lib/ui";

const PANEL = "rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800";
const MUTED = "text-xs text-slate-500 dark:text-slate-400";
const STATUSES: (AccessStatus | "")[] = ["", "TRIALING", "ACTIVE", "GRANTED", "EXPIRED", "NONE", "PAST_DUE", "CANCELED"];

function message(e: unknown): string {
  return e instanceof ApiError ? e.message : "Something went wrong.";
}

/** Signed in, then a second factor, then the dashboard. The server checks the same on every call. */
export function AdminApp() {
  const [session, setSession] = useState<Session | null | undefined>(() => (supabaseConfigured() ? undefined : null));

  useEffect(() => {
    if (!supabaseConfigured()) return;
    const sb = supabase();
    sb.auth.getSession().then(({ data }) => setSession(data.session));
    const { data } = sb.auth.onAuthStateChange((_event, next) => setSession(next));
    return () => data.subscription.unsubscribe();
  }, []);

  if (session === undefined) return <p className="mt-10 text-center text-sm text-slate-400">Loading…</p>;
  if (!session) return <SignIn />;
  return (
    <MfaGate>
      <Dashboard onSignOut={() => void supabase().auth.signOut({ scope: "global" })} />
    </MfaGate>
  );
}

type Tab = "overview" | "users" | "audit";

function Dashboard({ onSignOut }: { onSignOut: () => void }) {
  const [tab, setTab] = useState<Tab>("overview");
  const [selected, setSelected] = useState<string | null>(null);
  const [denied, setDenied] = useState<string | null>(null);

  if (denied) {
    return (
      <div className={`${PANEL} mx-auto mt-6 max-w-md`}>
        <p className="text-sm text-red-700 dark:text-red-300">{denied}</p>
        <button className={`${BTN_SECONDARY} mt-4`} onClick={onSignOut}>Sign out</button>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-6xl p-4">
      <header className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-bold text-slate-900 dark:text-slate-100">FPL Copilot admin</h1>
        <nav className="flex gap-2">
          {(["overview", "users", "audit"] as Tab[]).map((t) => (
            <button
              key={t}
              className={tab === t ? BTN_PRIMARY : BTN_SECONDARY}
              onClick={() => {
                setTab(t);
                setSelected(null);
              }}>
              {t[0].toUpperCase() + t.slice(1)}
            </button>
          ))}
          <button className={BTN_SECONDARY} onClick={onSignOut}>Sign out</button>
        </nav>
      </header>
      {selected ? (
        <UserView id={selected} onBack={() => setSelected(null)} onDenied={setDenied} />
      ) : tab === "overview" ? (
        <OverviewView onDenied={setDenied} />
      ) : tab === "users" ? (
        <UsersView onOpen={setSelected} onDenied={setDenied} />
      ) : (
        <AuditView onOpen={setSelected} onDenied={setDenied} />
      )}
    </div>
  );
}

/** Loads with the denied-access case routed up: a non-admin sees one clear message. */
function useAdmin<T>(load: () => Promise<T>, onDenied: (m: string) => void, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [n, setN] = useState(0);
  const reload = useCallback(() => setN((x) => x + 1), []);
  useEffect(() => {
    let stale = false;
    load().then(
      (d) => {
        if (stale) return;
        setData(d);
        setError(null);
      },
      (e) => {
        if (stale) return;
        if (e instanceof ApiError && e.status === 403 && e.code !== "MFA_REQUIRED") onDenied("This account is not an admin.");
        else setError(message(e));
      },
    );
    return () => {
      stale = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, n]);
  return { data, error, reload };
}

function Stat({ label, value, note }: { label: string; value: string | number; note?: string }) {
  return (
    <div className={PANEL}>
      <p className={MUTED}>{label}</p>
      <p className="mt-1 text-2xl font-bold tabular-nums text-slate-900 dark:text-slate-100">{value}</p>
      {note && <p className={`${MUTED} mt-1`}>{note}</p>}
    </div>
  );
}

function OverviewView({ onDenied }: { onDenied: (m: string) => void }) {
  const { data, error } = useAdmin<Overview>(adminApi.overview, onDenied, []);
  if (error) return <p className="text-sm text-red-700 dark:text-red-300">{error}</p>;
  if (!data) return <p className={MUTED}>Loading…</p>;
  const s = data.statuses;
  const conv = data.trial_conversion_30d;
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
      <Stat label="Users" value={data.users} note={`${data.teams_connected} teams connected`} />
      <Stat label="Paying" value={(s.ACTIVE ?? 0) + (s.PAST_DUE ?? 0)} note={`${data.subscribers.MONTHLY} monthly · ${data.subscribers.ANNUAL} annual`} />
      <Stat label="On a free trial" value={s.TRIALING ?? 0} />
      <Stat label="Free access granted" value={s.GRANTED ?? 0} />
      <Stat label="Expired" value={s.EXPIRED ?? 0} note={`${s.NONE ?? 0} never started`} />
      <Stat label="Sign-ups" value={data.signups["7d"]} note={`last 7 days · ${data.signups["30d"]} in 30`} />
      <Stat
        label="Trial → paid (30 days)"
        value={conv.ended ? `${Math.round((conv.converted / conv.ended) * 100)}%` : "—"}
        note={`${conv.converted} of ${conv.ended} trials that ended`}
      />
      <Stat label="Notifications" value={data.push_devices} note={`phones · ${data.telegram_linked} Telegram · ${data.live_alerts_off} live alerts off`} />
      <Stat
        label="Last data refresh"
        value={data.last_refresh ? (data.last_refresh.ok ? "OK" : "Failed") : "—"}
        note={data.last_refresh ? `${when(data.last_refresh.at)} · ${data.last_refresh.seconds}s` : undefined}
      />
      <Stat label="Advice stored" value={data.advice_cached} note="teams with advice worked out ahead" />
    </div>
  );
}

function UsersView({ onOpen, onDenied }: { onOpen: (id: string) => void; onDenied: (m: string) => void }) {
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<AccessStatus | "">("");
  const [page, setPage] = useState(1);
  const { data, error } = useAdmin<UserPage>(() => adminApi.users(query, status, page), onDenied, [query, status, page]);

  return (
    <div className="flex flex-col gap-3">
      <form
        className="flex flex-wrap gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          setPage(1);
          setQuery(q);
        }}>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Email, team name, Team ID or user id"
          aria-label="Search users"
          className="min-w-64 flex-1 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-900"
        />
        <select aria-label="Status" className={SELECT} value={status} onChange={(e) => { setPage(1); setStatus(e.target.value as AccessStatus | ""); }}>
          {STATUSES.map((s) => (
            <option key={s} value={s}>{s || "Any status"}</option>
          ))}
        </select>
        <button className={BTN_PRIMARY} type="submit">Search</button>
      </form>
      {error && <p className="text-sm text-red-700 dark:text-red-300">{error}</p>}
      {data && (
        <>
          <p className={MUTED}>{data.total} users</p>
          <div className={`${PANEL} overflow-x-auto p-0`}>
            <table className="w-full text-left text-sm">
              <thead className={MUTED}>
                <tr>
                  {["Email", "Team", "Status", "Ends", "Signed up", "Last seen", "Alerts"].map((h) => (
                    <th key={h} className="px-3 py-2 font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.users.map((u) => (
                  <tr
                    key={u.id}
                    onClick={() => onOpen(u.id)}
                    className="cursor-pointer border-t border-slate-100 hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-700/40">
                    <td className="px-3 py-2">{u.email ?? "—"} <span className={MUTED}>{u.providers.join(", ")}</span></td>
                    <td className="px-3 py-2">{u.team ? `${u.team.team_name} (${u.team.fpl_entry_id})` : "—"}</td>
                    <td className="px-3 py-2"><StatusBadge status={u.status} /> {u.plan ? <span className={MUTED}>{u.plan.toLowerCase()}</span> : null}</td>
                    <td className="px-3 py-2">{when(u.subscription_ends_at ?? u.trial_ends_at)}</td>
                    <td className="px-3 py-2">{when(u.created_at)}</td>
                    <td className="px-3 py-2">{when(u.last_seen_at ?? u.last_sign_in_at)}</td>
                    <td className="px-3 py-2">{u.devices ? `${u.devices} phone${u.devices > 1 ? "s" : ""}` : "—"}{u.telegram ? " · Telegram" : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex gap-2">
            <button className={BTN_SECONDARY} disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
            <button className={BTN_SECONDARY} disabled={page * data.page_size >= data.total} onClick={() => setPage(page + 1)}>Next</button>
          </div>
        </>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: AccessStatus }) {
  const tone: Record<string, string> = {
    ACTIVE: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
    TRIALING: "bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-300",
    GRANTED: "bg-violet-100 text-violet-800 dark:bg-violet-900/40 dark:text-violet-300",
    PAST_DUE: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  };
  return (
    <span className={`rounded px-1.5 py-0.5 text-xs font-semibold ${tone[status] ?? "bg-slate-100 text-slate-700 dark:bg-slate-700 dark:text-slate-300"}`}>
      {status.replace("_", " ").toLowerCase()}
    </span>
  );
}

type Action = "grant" | "endGrant" | "releaseTeam" | "syncBilling" | "testPush" | "delete";
const ACTIONS: Record<Action, { label: string; danger?: boolean; help: string }> = {
  grant: { label: "Give free access", help: "Days of free access, added to any already running. Not for store subscribers." },
  endGrant: { label: "End free access", help: "Ends free access given from this dashboard." },
  syncBilling: { label: "Re-check with RevenueCat", help: "Re-reads their subscription from the store, when the app and the store disagree." },
  testPush: { label: "Send a test notification", help: "Sends a test push to their phones." },
  releaseTeam: { label: "Release their team", danger: true, help: "Disconnects their FPL team so its rightful owner can connect it. Their trial record stays with the team." },
  delete: { label: "Delete account", danger: true, help: "Deletes the account and its data, exactly as deleting it in the app does. Cannot be undone." },
};

function UserView({ id, onBack, onDenied }: { id: string; onBack: () => void; onDenied: (m: string) => void }) {
  const { data: u, error, reload } = useAdmin<UserDetail>(() => adminApi.user(id), onDenied, [id]);
  const [action, setAction] = useState<Action | null>(null);
  const [done, setDone] = useState<string | null>(null);

  return (
    <div className="flex flex-col gap-3">
      <button className={`${BTN_SECONDARY} self-start`} onClick={onBack}>← Back</button>
      {error && <p className="text-sm text-red-700 dark:text-red-300">{error}</p>}
      {done && <p className="rounded-md bg-emerald-50 p-2 text-sm text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300">{done}</p>}
      {u && (
        <>
          <div className={PANEL}>
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-lg font-bold text-slate-900 dark:text-slate-100">{u.email ?? "No email"}</h2>
              <StatusBadge status={u.status} />
              {u.is_admin && <span className={MUTED}>admin</span>}
            </div>
            <p className={MUTED}>
              {u.providers.join(", ") || "—"} · signed up {when(u.created_at)} · last signed in {when(u.last_sign_in_at)} · last seen {when(u.last_seen_at)}
            </p>
            <p className={`${MUTED} select-all`}>{u.id}</p>
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            <Section title="Team">
              {u.teams.length ? u.teams.map((t) => (
                <p key={t.fpl_entry_id}>
                  <b>{t.team_name}</b> ({t.fpl_entry_id}) · {t.manager_name}
                  <br />
                  <span className={MUTED}>
                    connected {when(t.connected_at)} · {t.verified_at ? `proven ${when(t.verified_at)}` : "not proven"}{t.telegram ? " · Telegram linked" : ""}
                  </span>
                </p>
              )) : <p className={MUTED}>No team connected.</p>}
            </Section>
            <Section title="Access">
              <p>
                {u.status.toLowerCase()} {u.plan ? `· ${u.plan.toLowerCase()}` : ""} {u.provider ? `· ${u.provider.toLowerCase()}` : ""}
              </p>
              {u.trial && <p className={MUTED}>Trial {when(u.trial.started_at)} → {when(u.trial.ends_at)} (team {u.trial.fpl_entry_id})</p>}
              {u.subscription && (
                <p className={MUTED}>
                  {u.subscription.granted ? "Free access" : u.subscription.provider} · {u.subscription.status.toLowerCase()} · ends {when(u.subscription.expires_at)}
                  {u.subscription.is_sandbox ? " · sandbox" : ""} · synced {when(u.subscription.synced_at)}
                </p>
              )}
            </Section>
            <Section title="Notifications">
              <p>{u.devices.length ? u.devices.map((d) => `${d.platform} (${when(d.last_seen_at)})`).join(", ") : "No phone registered"}</p>
              <p className={MUTED}>
                {Object.entries(u.notifications).map(([k, on]) => `${k} ${on ? "on" : "off"}`).join(" · ")}
              </p>
              {u.pushes.slice(0, 5).map((p) => (
                <p key={`${p.kind}${p.key}`} className={MUTED}>{when(p.sent_at)} · {p.kind} · {p.key}</p>
              ))}
            </Section>
            <Section title="Billing events">
              {u.billing_events.length ? u.billing_events.map((e, i) => (
                <p key={i} className={MUTED}>{when(e.at)} · {e.type}</p>
              )) : <p className={MUTED}>None.</p>}
            </Section>
          </div>

          <Section title="Actions">
            <div className="flex flex-wrap gap-2">
              {(Object.keys(ACTIONS) as Action[]).map((a) => (
                <button
                  key={a}
                  className={ACTIONS[a].danger ? `${BTN_SECONDARY} border-red-300 text-red-700 dark:border-red-800 dark:text-red-300` : BTN_SECONDARY}
                  onClick={() => setAction(a)}>
                  {ACTIONS[a].label}
                </button>
              ))}
            </div>
          </Section>

          <Section title="Admin history">
            {u.audit.length ? u.audit.map((a) => <AuditLine key={a.id} entry={a} />) : <p className={MUTED}>Nothing yet.</p>}
          </Section>

          {action && (
            <ActionDialog
              user={u}
              action={action}
              onClose={() => setAction(null)}
              onDone={(text) => {
                setAction(null);
                setDone(text);
                if (action === "delete") onBack();
                else reload();
              }}
            />
          )}
        </>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className={`${PANEL} flex flex-col gap-1 text-sm text-slate-800 dark:text-slate-200`}>
      <h3 className="mb-1 text-xs font-semibold tracking-wide text-slate-500 uppercase dark:text-slate-400">{title}</h3>
      {children}
    </section>
  );
}

/** Every action: a reason (kept in the audit log), and for deletion, typing DELETE. */
function ActionDialog({ user, action, onClose, onDone }: { user: UserDetail; action: Action; onClose: () => void; onDone: (text: string) => void }) {
  const [reason, setReason] = useState("");
  const [days, setDays] = useState(30);
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const spec = ACTIONS[action];
  const ready = reason.trim().length >= 3 && (action !== "delete" || confirm === "DELETE");

  async function run() {
    setBusy(true);
    setError(null);
    try {
      let text = `${spec.label}: done.`;
      if (action === "grant") text = `Free access until ${when((await adminApi.grant(user.id, days, reason)).until)}.`;
      if (action === "endGrant") await adminApi.endGrant(user.id, reason);
      if (action === "releaseTeam") text = `Released team ${(await adminApi.releaseTeam(user.id, reason)).released.join(", ")}.`;
      if (action === "syncBilling") {
        const r = await adminApi.syncBilling(user.id, reason);
        text = `RevenueCat says: ${r.status ?? "no subscription"}${r.provider ? ` (${r.provider})` : ""}.`;
      }
      if (action === "testPush") {
        const r = await adminApi.testPush(user.id, reason);
        text = `Sent to ${r.sent} of ${r.devices} phone${r.devices > 1 ? "s" : ""}.`;
      }
      if (action === "delete") {
        await adminApi.deleteUser(user.id, reason);
        text = `Deleted ${user.email ?? user.id}.`;
      }
      onDone(text);
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div role="dialog" aria-modal="true" aria-label={spec.label} className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className={`${PANEL} w-full max-w-md`}>
        <h3 className="text-base font-bold text-slate-900 dark:text-slate-100">{spec.label}</h3>
        <p className={`${MUTED} mt-1`}>{spec.help}</p>
        <p className={`${MUTED} mt-1`}>For {user.email ?? user.id}</p>
        {action === "grant" && (
          <label className="mt-3 flex items-center gap-2 text-sm">
            Days
            <input type="number" min={1} max={365} value={days} onChange={(e) => setDays(Number(e.target.value))}
              className="w-24 rounded-md border border-slate-300 bg-white px-2 py-1 dark:border-slate-600 dark:bg-slate-900" />
          </label>
        )}
        <textarea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          maxLength={500}
          rows={3}
          placeholder="Why? This is kept in the audit log."
          aria-label="Reason"
          className="mt-3 w-full rounded-md border border-slate-300 bg-white p-2 text-sm dark:border-slate-600 dark:bg-slate-900"
        />
        {action === "delete" && (
          <input value={confirm} onChange={(e) => setConfirm(e.target.value)} placeholder="Type DELETE to confirm" aria-label="Confirm deletion"
            className="mt-2 w-full rounded-md border border-red-300 bg-white px-2 py-1 text-sm dark:border-red-800 dark:bg-slate-900" />
        )}
        {error && <p className="mt-2 text-sm text-red-700 dark:text-red-300">{error}</p>}
        <div className="mt-4 flex justify-end gap-2">
          <button className={BTN_SECONDARY} onClick={onClose}>Cancel</button>
          <button className={BTN_PRIMARY} disabled={!ready || busy} onClick={() => void run()}>{busy ? "Working…" : spec.label}</button>
        </div>
      </div>
    </div>
  );
}

function AuditLine({ entry, onOpen }: { entry: AuditEntry; onOpen?: (id: string) => void }) {
  const detail = entry.detail ? ` · ${Object.entries(entry.detail).map(([k, v]) => `${k} ${v}`).join(", ")}` : "";
  return (
    <p className="text-sm">
      <span className={MUTED}>{when(entry.created_at)}</span> <b>{entry.action.replace(/_/g, " ")}</b>
      {entry.target_user_id && onOpen ? (
        <button className="ml-1 text-xs text-sky-700 underline dark:text-sky-300" onClick={() => onOpen(entry.target_user_id!)}>
          user
        </button>
      ) : null}
      <span className={MUTED}> · {entry.reason}{detail}</span>
    </p>
  );
}

function AuditView({ onOpen, onDenied }: { onOpen: (id: string) => void; onDenied: (m: string) => void }) {
  const { data, error } = useAdmin(adminApi.audit, onDenied, []);
  if (error) return <p className="text-sm text-red-700 dark:text-red-300">{error}</p>;
  if (!data) return <p className={MUTED}>Loading…</p>;
  return (
    <div className={`${PANEL} flex flex-col gap-1`}>
      {data.entries.length ? data.entries.map((e) => <AuditLine key={e.id} entry={e} onOpen={onOpen} />) : <p className={MUTED}>No admin actions yet.</p>}
    </div>
  );
}
