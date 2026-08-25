"use client";

import { useEffect, useState } from "react";
import {
  api,
  ApiError,
  type AlertItem,
  type NewsEvent,
  type PriceWatchItem,
} from "@/lib/api";
import {
  BTN_SECONDARY,
  SEGMENT_BASE,
  SEGMENT_GROUP,
  SEGMENT_OFF,
  SEGMENT_ON,
} from "@/lib/ui";

type Tab = "alerts" | "feed" | "prices";

const SEVERITY_STYLE: Record<string, string> = {
  critical: "border-red-300 bg-red-50 dark:border-red-800 dark:bg-red-950/40",
  warning: "border-amber-300 bg-amber-50 dark:border-amber-800 dark:bg-amber-950/40",
  info: "border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-800",
};

const EVENT_LABEL: Record<string, string> = {
  ruled_out: "Ruled out",
  departed: "Left league",
  returned: "Returned",
  status_change: "Status change",
  chance_change: "Availability",
  news_change: "News update",
  price_change: "Price change",
};

/** Availability as a percentage, or a dash when unknown. */
function pct(v: number | null): string {
  return v === null ? "—" : `${Math.round(v * 100)}%`;
}

export function NewsPanel({ managerId }: { managerId: number | null }) {
  const [tab, setTab] = useState<Tab>(managerId ? "alerts" : "feed");
  const [alerts, setAlerts] = useState<AlertItem[] | null>(null);
  const [events, setEvents] = useState<NewsEvent[] | null>(null);
  const [prices, setPrices] = useState<PriceWatchItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    setError(null);

    const load = async () => {
      if (tab === "alerts") {
        if (managerId === null) {
          setAlerts([]);
          return;
        }
        // Generating first means the list reflects the latest sync
        await api.generateAlerts(managerId).catch(() => {});
        setAlerts(await api.alerts(managerId));
      } else if (tab === "feed") {
        setEvents(await api.newsEvents({ hours: 336, limit: 60 }));
      } else {
        setPrices(await api.priceWatch(50));
      }
    };

    load()
      .catch((e: ApiError) => setError(e.message))
      .finally(() => setLoading(false));
  }, [tab, managerId]);

  const unread = alerts?.filter((a) => !a.read).length ?? 0;

  return (
    <section>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">
          News &amp; alerts
        </h2>
        <div className="flex flex-wrap items-center gap-2">
          <div className={SEGMENT_GROUP}>
            {([
              ["alerts", `Mine${unread ? ` (${unread})` : ""}`, `My alerts${unread ? ` (${unread})` : ""}`],
              ["feed", "Changes", "All changes"],
              ["prices", "Prices", "Price watch"],
            ] as const).map(([id, short, long]) => (
              <button
                key={id}
                onClick={() => setTab(id)}
                className={`${SEGMENT_BASE} ${tab === id ? SEGMENT_ON : SEGMENT_OFF}`}
              >
                {/* Three full labels plus the heading overflow a phone, so the
                    tabs shorten rather than wrapping onto their own line. */}
                <span className="sm:hidden">{short}</span>
                <span className="hidden sm:inline">{long}</span>
              </button>
            ))}
          </div>
          {tab === "alerts" && managerId !== null && unread > 0 && (
            <button
              onClick={async () => {
                await api.markAlertsRead(managerId);
                setAlerts(await api.alerts(managerId));
              }}
              className={BTN_SECONDARY}
            >
              Mark read
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs text-amber-800 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-300">
          {error}
        </div>
      )}

      {loading && !error && (
        <p className="py-8 text-center text-sm text-slate-400">Loading…</p>
      )}

      {/* ── My alerts ──────────────────────────────────────────────────── */}
      {tab === "alerts" && !loading && !error && (
        <>
          {managerId === null ? (
            <p className="rounded-lg border border-dashed border-slate-300 p-6 text-center text-sm text-slate-400 dark:border-slate-700">
              Load a squad to see alerts for your players.
            </p>
          ) : alerts && alerts.length > 0 ? (
            <ul className="space-y-2">
              {alerts.map((a) => (
                <li
                  key={a.id}
                  className={`rounded-lg border p-3 ${SEVERITY_STYLE[a.severity]} ${
                    a.read ? "opacity-60" : ""
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                        {a.title}
                      </p>
                      {a.body && (
                        <p className="mt-0.5 text-xs text-slate-600 dark:text-slate-400">
                          {a.body}
                        </p>
                      )}
                      {a.payload?.expected_return ? (
                        <p className="mt-1 text-[11px] text-slate-500">
                          Expected back{" "}
                          {String(a.payload.expected_return).slice(0, 10)}
                        </p>
                      ) : null}
                      {a.still_owned === false && (
                        <p className="mt-1 text-[11px] italic text-slate-400">
                          No longer in your squad
                        </p>
                      )}
                    </div>
                    <span
                      className={`shrink-0 rounded px-1.5 py-0.5 text-[9px] font-bold uppercase ${
                        a.severity === "critical"
                          ? "bg-red-600 text-white"
                          : a.severity === "warning"
                            ? "bg-amber-500 text-white"
                            : "bg-slate-400 text-white"
                      }`}
                    >
                      {a.severity}
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="rounded-lg border border-dashed border-slate-300 p-6 text-center text-sm text-slate-400 dark:border-slate-700">
              No alerts for your squad. Run Sync FPL data to check for changes.
            </p>
          )}
        </>
      )}

      {/* ── All changes ────────────────────────────────────────────────── */}
      {tab === "feed" && !loading && !error && (
        <>
          {events && events.length > 0 ? (
            <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-700">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 dark:bg-slate-800/60">
                  <tr className="text-left text-[10px] uppercase tracking-wide text-slate-500">
                    <th className="px-3 py-2 font-semibold">Player</th>
                    <th className="px-2 py-2 font-semibold">Change</th>
                    <th className="px-2 py-2 text-center font-semibold">Avail</th>
                    {/* The raw FPL news line is long prose; on phones it moves
                        under the player's name instead of squeezing a column. */}
                    <th className="hidden px-2 py-2 font-semibold md:table-cell">
                      Evidence
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 dark:divide-slate-700">
                  {events.map((e) => (
                    <tr key={e.id}>
                      <td className="px-3 py-2">
                        <span className="font-semibold text-slate-900 dark:text-slate-100">
                          {e.name}
                        </span>
                        <span className="ml-1.5 text-[11px] text-slate-400">
                          {e.team} · {e.position}
                        </span>
                        {e.news && (
                          <span className="mt-0.5 block text-[11px] font-normal text-slate-500 md:hidden">
                            {e.news}
                          </span>
                        )}
                      </td>
                      <td className="px-2 py-2 text-xs text-slate-600 dark:text-slate-400">
                        {EVENT_LABEL[e.event_type] ?? e.event_type}
                        {e.requires_review && (
                          <span
                            className="ml-1.5 rounded bg-violet-500/20 px-1 text-[9px] font-bold text-violet-700 dark:text-violet-300"
                            title="Parser did not recognise this phrasing"
                          >
                            REVIEW
                          </span>
                        )}
                      </td>
                      <td className="px-2 py-2 text-center text-xs tabular-nums">
                        <span className="text-slate-400">
                          {pct(e.availability_before)}
                        </span>
                        <span className="mx-1 text-slate-300">→</span>
                        <span
                          className={
                            (e.availability_after ?? 0) <
                            (e.availability_before ?? 0)
                              ? "font-bold text-red-600 dark:text-red-400"
                              : "font-bold text-emerald-600 dark:text-emerald-400"
                          }
                        >
                          {pct(e.availability_after)}
                        </span>
                      </td>
                      <td className="hidden px-2 py-2 text-[11px] text-slate-500 md:table-cell">
                        {e.news || "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="rounded-lg border border-dashed border-slate-300 p-6 text-center text-sm text-slate-400 dark:border-slate-700">
              No changes recorded yet. The first sync only sets a baseline —
              changes appear from the next one.
            </p>
          )}
        </>
      )}

      {/* ── Price watch ────────────────────────────────────────────────── */}
      {tab === "prices" && !loading && !error && (
        <>
          {prices && prices.length > 0 ? (
            <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-700">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 dark:bg-slate-800/60">
                  <tr className="text-left text-[10px] uppercase tracking-wide text-slate-500">
                    <th className="px-3 py-2 font-semibold">Player</th>
                    <th className="px-2 py-2 text-right font-semibold">£</th>
                    <th className="px-2 py-2 font-semibold">Direction</th>
                    <th className="px-2 py-2 text-right font-semibold">Progress</th>
                    <th className="hidden px-2 py-2 text-right font-semibold sm:table-cell">
                      Net transfers
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 dark:divide-slate-700">
                  {prices.map((p) => (
                    <tr key={p.player_id}>
                      <td className="px-3 py-2 font-semibold text-slate-900 dark:text-slate-100">
                        {p.name}
                        <span className="ml-1.5 text-[11px] font-normal text-slate-400">
                          {p.team}
                        </span>
                      </td>
                      <td className="px-2 py-2 text-right tabular-nums text-slate-600 dark:text-slate-400">
                        {p.price.toFixed(1)}
                      </td>
                      <td className="px-2 py-2">
                        <span
                          className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${
                            p.direction === "rise"
                              ? "bg-emerald-500/20 text-emerald-700 dark:text-emerald-300"
                              : "bg-red-500/20 text-red-700 dark:text-red-300"
                          }`}
                        >
                          {p.direction === "rise" ? "↑ RISE" : "↓ FALL"}
                        </span>
                      </td>
                      <td className="px-2 py-2 text-right tabular-nums text-slate-700 dark:text-slate-300">
                        {Math.abs(p.percent_to_threshold).toFixed(1)}%
                      </td>
                      <td className="hidden px-2 py-2 text-right tabular-nums text-slate-500 sm:table-cell">
                        {p.net_transfers_gw.toLocaleString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="rounded-lg border border-dashed border-slate-300 p-6 text-center text-sm text-slate-400 dark:border-slate-700">
              No players near a price change right now.
            </p>
          )}
          <p className="mt-2 text-[10px] text-slate-400">
            Progress toward FPL&apos;s own price-change threshold — published by
            FPL, not modelled by us.
          </p>
        </>
      )}
    </section>
  );
}
