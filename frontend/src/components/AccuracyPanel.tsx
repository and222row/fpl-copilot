"use client";

import { useEffect, useState } from "react";
import {
  api,
  ApiError,
  type AccuracySummary,
  type OutcomeRow,
  type PendingSnapshot,
} from "@/lib/api";
import { BTN_SECONDARY } from "@/lib/ui";

const KIND_LABEL: Record<string, string> = {
  captain: "Captain",
  lineup: "Lineup",
  transfer: "Transfer",
};

function pct(v: number | null): string {
  return v === null ? "—" : `${Math.round(v * 100)}%`;
}

/**
 * The retention feature: show the model's track record rather than asking the
 * user to take it on trust.
 */
export function AccuracyPanel({ managerId }: { managerId: number | null }) {
  const [summary, setSummary] = useState<AccuracySummary | null>(null);
  const [history, setHistory] = useState<OutcomeRow[]>([]);
  const [pending, setPending] = useState<PendingSnapshot[]>([]);
  const [loading, setLoading] = useState(false);
  const [scoring, setScoring] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load(id: number) {
    setLoading(true);
    setError(null);
    try {
      const [s, h, p] = await Promise.all([
        api.accuracy(id),
        api.accuracyHistory(id),
        api.pendingSnapshots(id),
      ]);
      setSummary(s);
      setHistory(h);
      setPending(p.pending);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load accuracy");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (managerId !== null) load(managerId);
  }, [managerId]);

  if (managerId === null) return null;

  const scoreable = pending.filter((p) => p.scoreable);

  return (
    <section>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">
          How accurate have we been?
        </h2>
        {scoreable.length > 0 && (
          <button
            onClick={async () => {
              setScoring(true);
              try {
                await api.scoreAll(managerId);
                await load(managerId);
              } finally {
                setScoring(false);
              }
            }}
            disabled={scoring}
            className={BTN_SECONDARY}
          >
            {scoring ? "Scoring…" : `Score ${scoreable.length} finished`}
          </button>
        )}
      </div>

      {error && (
        <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs text-amber-800 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-300">
          {error}
        </div>
      )}

      {loading && !error && (
        <p className="py-6 text-center text-sm text-slate-400">Loading…</p>
      )}

      {/* ── Nothing scored yet ─────────────────────────────────────────── */}
      {!loading && !error && summary?.gameweeks_scored === 0 && (
        <div className="rounded-lg border border-dashed border-slate-300 p-6 dark:border-slate-700">
          <p className="text-sm text-slate-600 dark:text-slate-400">
            No accuracy history yet.
          </p>
          <p className="mt-1 text-xs text-slate-500">
            Recommendations are recorded when you view them before a deadline,
            then graded once that gameweek finishes.
            {pending.length > 0 && (
              <>
                {" "}
                <span className="font-semibold">
                  {pending.length} recommendation
                  {pending.length === 1 ? "" : "s"} waiting
                </span>{" "}
                for GW{[...new Set(pending.map((p) => p.gameweek))].join(", GW")}.
              </>
            )}
          </p>
        </div>
      )}

      {/* ── Category scorecards ────────────────────────────────────────── */}
      {!loading && summary && summary.gameweeks_scored > 0 && (
        <>
          <div className="grid gap-3 sm:grid-cols-3">
            {Object.entries(summary.categories).map(([kind, c]) => (
              <div
                key={kind}
                className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800"
              >
                <p className="text-[10px] font-bold uppercase tracking-widest text-slate-500">
                  {KIND_LABEL[kind] ?? kind}
                </p>
                <p
                  className={`mt-1 text-2xl font-bold tabular-nums ${
                    c.hit_rate === null
                      ? "text-slate-400"
                      : c.hit_rate >= 0.5
                        ? "text-emerald-600 dark:text-emerald-400"
                        : "text-amber-600 dark:text-amber-400"
                  }`}
                >
                  {pct(c.hit_rate)}
                </p>
                <p className="text-[10px] uppercase tracking-wide text-slate-400">
                  best choice rate · {c.decisions} decision
                  {c.decisions === 1 ? "" : "s"}
                </p>

                <dl className="mt-3 space-y-1 border-t border-slate-100 pt-2 text-[11px] dark:border-slate-700">
                  <div className="flex justify-between">
                    <dt className="text-slate-500">Avg regret</dt>
                    <dd className="font-semibold tabular-nums text-slate-700 dark:text-slate-300">
                      {c.mean_regret.toFixed(1)} pts
                    </dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-slate-500">Avg error</dt>
                    <dd
                      className="font-semibold tabular-nums text-slate-700 dark:text-slate-300"
                      title={
                        c.mean_error < 0
                          ? "Negative means we over-projected"
                          : "Positive means we under-projected"
                      }
                    >
                      {c.mean_error > 0 ? "+" : ""}
                      {c.mean_error.toFixed(1)}
                    </dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-slate-500">You followed</dt>
                    <dd className="font-semibold tabular-nums text-slate-700 dark:text-slate-300">
                      {pct(c.follow_rate)}
                    </dd>
                  </div>
                  {c.points_lost_by_overriding !== null && (
                    <div className="flex justify-between">
                      <dt className="text-slate-500">Overriding cost you</dt>
                      <dd
                        className={`font-semibold tabular-nums ${
                          c.points_lost_by_overriding > 0
                            ? "text-red-600 dark:text-red-400"
                            : "text-emerald-600 dark:text-emerald-400"
                        }`}
                      >
                        {c.points_lost_by_overriding > 0 ? "+" : ""}
                        {c.points_lost_by_overriding.toFixed(1)} pts
                      </dd>
                    </div>
                  )}
                </dl>
              </div>
            ))}
          </div>

          {summary.total_regret !== undefined && (
            <p className="mt-3 text-[11px] text-slate-500 dark:text-slate-400">
              Across {summary.gameweeks_scored} gameweek
              {summary.gameweeks_scored === 1 ? "" : "s"}, our recommendations
              left{" "}
              <span className="font-semibold">
                {summary.total_regret.toFixed(1)} points
              </span>{" "}
              on the table versus the best choices available.{" "}
              <span className="text-slate-400">
                Regret is the honest measure — a projection can be numerically
                wrong and still be the right decision.
              </span>
            </p>
          )}

          {/* ── Per-gameweek detail ───────────────────────────────────── */}
          {history.length > 0 && (
            <div className="mt-4 overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-700">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 dark:bg-slate-800/60">
                  <tr className="text-left text-[10px] uppercase tracking-wide text-slate-500">
                    <th className="px-3 py-2 font-semibold">GW</th>
                    <th className="px-2 py-2 font-semibold">Decision</th>
                    {/* Predicted and Followed are context rather than the
                        headline, so they wait for a wider screen. */}
                    <th className="hidden px-2 py-2 text-right font-semibold sm:table-cell">
                      Predicted
                    </th>
                    <th className="px-2 py-2 text-right font-semibold">Actual</th>
                    <th className="px-2 py-2 text-right font-semibold">Regret</th>
                    <th className="px-2 py-2 text-center font-semibold">Best?</th>
                    <th className="hidden px-2 py-2 text-center font-semibold sm:table-cell">
                      Followed
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 dark:divide-slate-700">
                  {history.map((h, i) => (
                    <tr key={`${h.gameweek}-${h.kind}-${i}`}>
                      <td className="px-3 py-2 font-semibold text-slate-700 dark:text-slate-300">
                        {h.gameweek}
                      </td>
                      <td className="px-2 py-2 text-xs text-slate-600 dark:text-slate-400">
                        {KIND_LABEL[h.kind] ?? h.kind}
                      </td>
                      <td className="hidden px-2 py-2 text-right tabular-nums text-slate-500 sm:table-cell">
                        {h.predicted.toFixed(1)}
                      </td>
                      <td className="px-2 py-2 text-right font-semibold tabular-nums text-slate-900 dark:text-slate-100">
                        {h.actual.toFixed(1)}
                      </td>
                      <td
                        className={`px-2 py-2 text-right tabular-nums ${
                          h.regret > 0
                            ? "text-amber-600 dark:text-amber-400"
                            : "text-slate-400"
                        }`}
                      >
                        {h.regret.toFixed(1)}
                      </td>
                      <td className="px-2 py-2 text-center">
                        {h.correct === null ? (
                          <span className="text-slate-300">—</span>
                        ) : h.correct ? (
                          <span className="text-emerald-600 dark:text-emerald-400">✓</span>
                        ) : (
                          <span className="text-red-500">✗</span>
                        )}
                      </td>
                      <td className="hidden px-2 py-2 text-center text-xs sm:table-cell">
                        {h.followed === null ? (
                          <span className="text-slate-300">—</span>
                        ) : h.followed ? (
                          <span className="text-slate-500">yes</span>
                        ) : (
                          <span className="text-slate-400">no</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </section>
  );
}
