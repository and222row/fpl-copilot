"use client";

import { useEffect, useState, type ReactNode } from "react";
import { supabase } from "@/lib/supabase";
import { BTN_PRIMARY } from "@/lib/ui";

const CARD =
  "mx-auto mt-6 max-w-md rounded-xl border border-slate-200 bg-white p-6 dark:border-slate-700 dark:bg-slate-800";
const INPUT =
  "rounded-md border border-slate-300 bg-white px-3 py-2 text-center font-mono text-lg tracking-[0.4em] dark:border-slate-600 dark:bg-slate-900";

type State =
  | { step: "checking" }
  | { step: "verify"; factorId: string }
  | { step: "enroll"; factorId: string; qr: string; secret: string }
  | { step: "done" }
  | { step: "error"; message: string };

/**
 * The second factor the admin API requires: an authenticator app code
 * (TOTP). First visit enrols one from a QR code; later visits ask for a code.
 * Verifying upgrades the session to aal2, which the server reads from the
 * signed token, so this screen is convenience, not the security boundary.
 */
export function MfaGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<State>({ step: "checking" });
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let stale = false;
    (async () => {
      const mfa = supabase().auth.mfa;
      const { data: level, error: e } = await mfa.getAuthenticatorAssuranceLevel();
      if (stale) return;
      if (e) return setState({ step: "error", message: e.message });
      if (level.currentLevel === "aal2") return setState({ step: "done" });
      const { data: factors, error: fe } = await mfa.listFactors();
      if (stale) return;
      if (fe) return setState({ step: "error", message: fe.message });
      const verified = factors.totp[0];
      if (verified) return setState({ step: "verify", factorId: verified.id });
      // Start clean: an unverified factor from an abandoned enrolment blocks a new one.
      for (const f of factors.all.filter((f) => f.factor_type === "totp" && f.status !== "verified")) {
        await mfa.unenroll({ factorId: f.id });
      }
      const { data: enrolled, error: ee } = await mfa.enroll({ factorType: "totp", friendlyName: "FPL Copilot admin" });
      if (stale) return;
      if (ee) return setState({ step: "error", message: ee.message });
      setState({ step: "enroll", factorId: enrolled.id, qr: enrolled.totp.qr_code, secret: enrolled.totp.secret });
    })();
    return () => {
      stale = true;
    };
  }, []);

  async function verify(e: React.FormEvent) {
    e.preventDefault();
    if (state.step !== "verify" && state.step !== "enroll") return;
    setBusy(true);
    setError(null);
    const { error: ve } = await supabase().auth.mfa.challengeAndVerify({ factorId: state.factorId, code });
    setBusy(false);
    if (ve) {
      setError("That code didn't work. Codes change every 30 seconds; try the current one.");
      setCode("");
      return;
    }
    setState({ step: "done" });
  }

  if (state.step === "done") return <>{children}</>;
  if (state.step === "checking") return <p className="mt-10 text-center text-sm text-slate-400">Checking your sign-in…</p>;
  if (state.step === "error") {
    return (
      <div className={CARD}>
        <p className="text-sm text-red-700 dark:text-red-300">
          Two-factor sign-in is unavailable: {state.message}. Check that TOTP is enabled under Supabase → Authentication → MFA.
        </p>
      </div>
    );
  }

  return (
    <form className={CARD} onSubmit={verify}>
      <h2 className="text-lg font-bold text-slate-900 dark:text-slate-100">
        {state.step === "enroll" ? "Set up two-factor sign-in" : "Enter your authenticator code"}
      </h2>
      {state.step === "enroll" ? (
        <>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            The admin dashboard needs a second factor. Scan this with an authenticator app (Google Authenticator,
            1Password, Authy…), then enter the 6-digit code it shows.
          </p>
          {/* An SVG data URL from Supabase; img-src allows data: in the CSP. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={state.qr} alt="QR code for your authenticator app" className="mx-auto my-4 h-48 w-48 rounded bg-white p-2" />
          <p className="text-center text-xs text-slate-400">
            Can&apos;t scan? Enter this key: <code className="select-all break-all">{state.secret}</code>
          </p>
        </>
      ) : (
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">From the authenticator app you set up for FPL Copilot.</p>
      )}
      <div className="mt-4 flex flex-col gap-2">
        <input
          value={code}
          onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
          inputMode="numeric"
          autoComplete="one-time-code"
          autoFocus
          placeholder="123456"
          aria-label="Authenticator code"
          className={INPUT}
        />
        <button type="submit" disabled={busy || code.length !== 6} className={BTN_PRIMARY}>
          {busy ? "Checking…" : "Verify"}
        </button>
      </div>
      {error && <p className="mt-3 text-sm text-red-700 dark:text-red-300">{error}</p>}
    </form>
  );
}
