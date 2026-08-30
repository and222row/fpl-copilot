"use client";

import { useCallback, useEffect, useState } from "react";
import {
  api,
  ApiError,
  type NotificationStatus,
  type TelegramLink,
} from "@/lib/api";
import { BTN_PRIMARY, BTN_SECONDARY } from "@/lib/ui";

/**
 * Opt-in Telegram delivery, and the switch to turn it off again.
 *
 * Alerts were computed every fifteen minutes and then sat in a table until
 * someone opened this page — which required already suspecting that something
 * had happened. This connects them to a phone.
 *
 * Consent is explicit in both directions and offered in two degrees, because
 * "quiet for a bit" and "forget me" are different requests: pausing keeps the
 * link so it can be resumed from here alone, disconnecting discards the chat
 * id and needs Telegram again to undo.
 */
export function NotificationSettings({ managerId }: { managerId: number }) {
  const [status, setStatus] = useState<NotificationStatus | null>(null);
  const [link, setLink] = useState<TelegramLink | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setStatus(await api.notificationStatus(managerId));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not read settings");
    }
  }, [managerId]);

  useEffect(() => {
    load();
  }, [load]);

  // While a link is outstanding the connection happens in Telegram, not here,
  // so poll until it lands rather than making the user reload.
  useEffect(() => {
    if (!link || status?.linked) return;
    const id = setInterval(async () => {
      const next = await api.notificationStatus(managerId).catch(() => null);
      if (next?.linked) {
        setStatus(next);
        setLink(null);
        setNote("Connected. A test message is on its way.");
        api.testTelegram(managerId).catch(() => {});
      }
    }, 3000);
    return () => clearInterval(id);
  }, [link, status?.linked, managerId]);

  async function run(fn: () => Promise<unknown>, after?: string) {
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      await fn();
      await load();
      if (after) setNote(after);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  if (!status) return null;

  if (!status.available) {
    return (
      <section>
        <Heading />
        <p className="rounded-lg border border-dashed border-slate-300 p-4 text-xs text-slate-500 dark:border-slate-700">
          Telegram alerts are not configured on the server. Set{" "}
          <code>TELEGRAM_BOT_TOKEN</code> to enable them.
        </p>
      </section>
    );
  }

  return (
    <section>
      <Heading />

      <div className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800">
        {/* ── Connected ─────────────────────────────────────────────────── */}
        {status.linked ? (
          <>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-slate-100">
                  <span
                    className={`inline-block h-2 w-2 shrink-0 rounded-full ${
                      status.enabled ? "bg-emerald-500" : "bg-slate-400"
                    }`}
                    aria-hidden
                  />
                  {status.enabled ? "Sending to Telegram" : "Paused"}
                </p>
                <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  {status.enabled
                    ? `You'll get ${status.severities.join(" and ")} alerts for your squad — injuries, availability and price moves.`
                    : "Still connected, just not sending. Resume any time."}
                </p>
              </div>

              <div className="flex w-full flex-wrap gap-2 sm:w-auto">
                <button
                  onClick={() =>
                    run(
                      () => api.setTelegramEnabled(managerId, !status.enabled),
                      status.enabled ? "Paused." : "Resumed.",
                    )
                  }
                  disabled={busy}
                  className={`${BTN_PRIMARY} flex-1 sm:flex-none`}
                >
                  {status.enabled ? "Pause" : "Resume"}
                </button>
                <button
                  onClick={() => run(() => api.testTelegram(managerId), "Test message sent.")}
                  disabled={busy || !status.enabled}
                  className={`${BTN_SECONDARY} flex-1 sm:flex-none`}
                >
                  Send test
                </button>
              </div>
            </div>

            <button
              onClick={() => {
                if (
                  confirm(
                    "Disconnect Telegram? You'll need to link again from Telegram to turn it back on.",
                  )
                ) {
                  run(() => api.unlinkTelegram(managerId), "Disconnected.");
                }
              }}
              disabled={busy}
              className="mt-3 inline-flex min-h-9 items-center text-xs font-semibold
                         text-slate-500 underline decoration-dotted hover:text-red-600
                         sm:pointer-fine:min-h-0 dark:hover:text-red-400"
            >
              Disconnect
            </button>
          </>
        ) : link ? (
          /* ── Waiting for the manager to press Start ────────────────────── */
          <>
            <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">
              One tap to finish
            </p>
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
              Open the link and press <strong>Start</strong>. That is how the bot
              learns which squad is yours — this page updates by itself.
            </p>
            <a
              href={link.deep_link}
              target="_blank"
              rel="noopener noreferrer"
              className={`${BTN_PRIMARY} mt-3 w-full sm:w-auto`}
            >
              Open Telegram →
            </a>
            <p className="mt-2 text-[11px] text-slate-400">
              Link expires in {link.expires_in_minutes} minutes and works once.
            </p>
          </>
        ) : (
          /* ── Not connected ────────────────────────────────────────────── */
          <>
            <p className="text-sm text-slate-600 dark:text-slate-400">
              Get injuries, availability changes and price warnings for{" "}
              <strong>your</strong> players sent to Telegram.
            </p>
            <p className="mt-1 text-xs text-slate-500">
              Alerts are checked every 15 minutes. Right now they only appear on
              this page, which means you have to think to look.
            </p>
            <button
              onClick={() =>
                run(async () => setLink(await api.createTelegramLink(managerId)))
              }
              disabled={busy}
              className={`${BTN_PRIMARY} mt-3 w-full sm:w-auto`}
            >
              {busy ? "Preparing…" : "Connect Telegram"}
            </button>
          </>
        )}

        {note && (
          <p className="mt-3 text-xs text-emerald-700 dark:text-emerald-400">{note}</p>
        )}
        {error && (
          <p className="mt-3 text-xs text-red-600 dark:text-red-400">{error}</p>
        )}
      </div>
    </section>
  );
}

function Heading() {
  return (
    <h2 className="mb-3 text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">
      Alerts to your phone
    </h2>
  );
}
