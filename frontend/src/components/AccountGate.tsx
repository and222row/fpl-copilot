"use client";

import type { Session } from "@supabase/supabase-js";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { account, ApiError, type Entitlement, type Me, type PendingConnection } from "@/lib/api";
import { supabase, supabaseConfigured } from "@/lib/supabase";
import { BTN_PRIMARY, BTN_SECONDARY } from "@/lib/ui";

export interface SignedInAccount {
  managerId: number;
  teamName: string;
  email: string | null;
  entitlement: Entitlement;
  signOut: () => void;
}

const CARD =
  "mx-auto mt-6 max-w-md rounded-xl border border-slate-200 bg-white p-6 dark:border-slate-700 dark:bg-slate-800";

function signOut() {
  void supabase().auth.signOut({ scope: "global" });
}

/**
 * Sign-in, team connection and the access check, in that order, before the
 * dashboard renders. The same rules as the app: the server decides access;
 * this only decides which screen to show.
 */
export function AccountGate({ children }: { children: (a: SignedInAccount) => ReactNode }) {
  // undefined = not yet read; null = signed out. The env check is inlined at
  // build time, so server and first client render agree (no hydration
  // mismatch).
  const [session, setSession] = useState<Session | null | undefined>(() =>
    supabaseConfigured() ? undefined : null,
  );
  const [me, setMe] = useState<Me | null>(null);
  const [entitlement, setEntitlement] = useState<Entitlement | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!supabaseConfigured()) return;
    const sb = supabase();
    sb.auth.getSession().then(({ data }) => setSession(data.session));
    const { data } = sb.auth.onAuthStateChange((_event, next) => {
      // Drop the previous account's data the moment the session changes, so
      // it can never show under someone else's sign-in.
      setMe(null);
      setEntitlement(null);
      setError(null);
      setSession(next);
    });
    return () => data.subscription.unsubscribe();
  }, []);

  // Bumped to re-read the account (after a retry or a team connection).
  const [reloads, setReloads] = useState(0);
  const reload = useCallback(() => {
    setError(null);
    setReloads((n) => n + 1);
  }, []);

  useEffect(() => {
    if (!session) return;
    // A response that lands after the session changed belongs to the old one.
    let stale = false;
    Promise.all([account.me(), account.entitlements()]).then(
      ([m, e]) => {
        if (stale) return;
        setMe(m);
        setEntitlement(e);
      },
      (e) => {
        if (!stale) setError(e instanceof ApiError ? e.message : "Could not load your account.");
      },
    );
    return () => {
      stale = true;
    };
  }, [session, reloads]);

  if (session === undefined) return <p className="mt-10 text-center text-sm text-slate-400">Loading…</p>;
  if (!session) return <SignIn />;
  if (error) {
    return (
      <div className={CARD}>
        <p className="text-sm text-red-700 dark:text-red-300">{error}</p>
        <div className="mt-4 flex gap-2">
          <button className={BTN_PRIMARY} onClick={reload}>Try again</button>
          <button className={BTN_SECONDARY} onClick={signOut}>Sign out</button>
        </div>
      </div>
    );
  }
  if (!me || !entitlement) return <p className="mt-10 text-center text-sm text-slate-400">Loading your account…</p>;

  const team = me.fpl_accounts[0];
  if (!team) return <ConnectTeam onConnected={reload} />;
  if (!entitlement.premium) return <NoAccess entitlement={entitlement} email={me.email} />;

  return children({
    managerId: team.fpl_entry_id,
    teamName: team.team_name,
    email: me.email,
    entitlement,
    signOut,
  });
}

function SignIn() {
  const [error, setError] = useState<string | null>(null);

  async function go(provider: "google" | "apple") {
    setError(null);
    if (!supabaseConfigured()) {
      setError("Sign-in is not configured: set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_KEY.");
      return;
    }
    const { error: e } = await supabase().auth.signInWithOAuth({
      provider,
      options: { redirectTo: window.location.origin },
    });
    if (e) setError(e.message);
  }

  return (
    <div className={CARD}>
      <h2 className="text-lg font-bold text-slate-900 dark:text-slate-100">Sign in</h2>
      <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
        Use the same account as the FPL Copilot app.
      </p>
      <div className="mt-5 flex flex-col gap-2">
        <button className={BTN_PRIMARY} onClick={() => void go("apple")}>Continue with Apple</button>
        <button className={BTN_SECONDARY} onClick={() => void go("google")}>Continue with Google</button>
      </div>
      {error && <p className="mt-3 text-sm text-red-700 dark:text-red-300">{error}</p>}
    </div>
  );
}

function ConnectTeam({ onConnected }: { onConnected: () => void }) {
  const [teamId, setTeamId] = useState("");
  const [pending, setPending] = useState<PendingConnection | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function start(e: React.FormEvent) {
    e.preventDefault();
    const id = Number(teamId);
    if (!Number.isInteger(id) || id <= 0) {
      setError("Enter your FPL Team ID (numbers only).");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await account.startConnection(id);
      if (result.status === "connected") onConnected();
      else setPending(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  async function verify() {
    if (!pending) return;
    setBusy(true);
    setError(null);
    try {
      await account.verifyConnection(pending.fpl_entry_id);
      onConnected();
    } catch (err) {
      if (err instanceof ApiError && (err.status === 404 || err.status === 429)) setPending(null);
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={CARD}>
      <h2 className="text-lg font-bold text-slate-900 dark:text-slate-100">Connect your FPL team</h2>
      {!pending ? (
        <form onSubmit={start} className="mt-4 flex flex-col gap-2">
          <input
            value={teamId}
            onChange={(e) => setTeamId(e.target.value.replace(/\D/g, ""))}
            inputMode="numeric"
            placeholder="FPL Team ID, e.g. 1234567"
            className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-900"
          />
          <button type="submit" disabled={busy} className={BTN_PRIMARY}>
            {busy ? "Checking…" : "Continue"}
          </button>
          <p className="text-xs text-slate-400">
            Find it at fantasy.premierleague.com → Points: the number after <code>/entry/</code> in the address.
          </p>
        </form>
      ) : (
        <div className="mt-4 flex flex-col gap-3">
          <p className="text-sm text-slate-600 dark:text-slate-300">
            To prove {pending.team_name} is yours, add this code to your FPL team name, save, then verify.
            You can change the name back afterwards.
          </p>
          <p className="text-center font-mono text-3xl font-bold tracking-widest text-slate-900 dark:text-slate-100">
            {pending.code}
          </p>
          <button disabled={busy} className={BTN_PRIMARY} onClick={() => void verify()}>
            {busy ? "Checking FPL…" : "Verify"}
          </button>
        </div>
      )}
      {error && <p className="mt-3 text-sm text-red-700 dark:text-red-300">{error}</p>}
      <button className={`${BTN_SECONDARY} mt-4`} onClick={signOut}>Sign out</button>
    </div>
  );
}

function NoAccess({ entitlement, email }: { entitlement: Entitlement; email: string | null }) {
  const headline =
    entitlement.status === "NONE"
      ? "This team has already used its free trial."
      : "Your free trial or subscription has ended.";
  return (
    <div className={CARD}>
      <h2 className="text-lg font-bold text-slate-900 dark:text-slate-100">FPL Copilot Pro</h2>
      <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">{headline}</p>
      <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
        Subscriptions are sold in the FPL Copilot app for iOS and Android. Subscribe there, then sign in here
        {email ? ` as ${email}` : ""} with the same account.
      </p>
      <button className={`${BTN_SECONDARY} mt-4`} onClick={signOut}>Sign out</button>
    </div>
  );
}
