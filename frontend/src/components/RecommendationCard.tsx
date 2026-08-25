"use client";

import { useState } from "react";
import type { FullRecommendation } from "@/lib/api";

/**
 * The blueprint's core UX promise: answer "what should I do?" first, and show
 * the reasoning underneath rather than a wall of metrics.
 */
export function RecommendationCard({ rec }: { rec: FullRecommendation }) {
  const [showWhy, setShowWhy] = useState(false);
  const t = rec.transfer;
  const isHold = t.plan.transfers === 0;
  const best = rec.captain.ranking[0];
  const runnerUp = rec.captain.ranking[1];

  return (
    <div className="space-y-4">
      {/* ── The action ────────────────────────────────────────────────── */}
      <div
        className={`rounded-xl border-2 p-4 sm:p-5 ${
          isHold
            ? "border-sky-400 bg-sky-50 dark:border-sky-700 dark:bg-sky-950/40"
            : "border-emerald-400 bg-emerald-50 dark:border-emerald-700 dark:bg-emerald-950/40"
        }`}
      >
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="text-[10px] font-bold uppercase tracking-widest text-slate-500 dark:text-slate-400">
              Recommended move
            </p>
            <h2 className="mt-1 text-xl font-bold text-slate-900 sm:text-2xl dark:text-slate-50">
              {isHold ? "Hold — roll your transfer" : t.action}
            </h2>

            {!isHold && (
              <div className="mt-3 space-y-1.5">
                {t.plan.out.map((out, i) => {
                  const inc = t.plan.in[i];
                  return (
                    <div key={out.player_id} className="flex flex-wrap items-center gap-2 text-sm">
                      <span className="font-semibold text-red-700 dark:text-red-400">
                        {out.name}
                      </span>
                      <span className="text-xs text-slate-400">
                        £{out.price.toFixed(1)} · {out.horizon_xpts.toFixed(1)} xPts
                      </span>
                      <span className="text-slate-400">→</span>
                      {inc && (
                        <>
                          <span className="font-semibold text-emerald-700 dark:text-emerald-400">
                            {inc.name}
                          </span>
                          <span className="text-xs text-slate-400">
                            £{inc.price.toFixed(1)} · {inc.horizon_xpts.toFixed(1)} xPts
                          </span>
                        </>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          <div className="flex gap-5 sm:text-right">
            <div>
              <p
                className={`text-xl font-bold tabular-nums sm:text-2xl ${
                  t.expected_net_gain > 0
                    ? "text-emerald-700 dark:text-emerald-400"
                    : "text-slate-600 dark:text-slate-400"
                }`}
              >
                {t.expected_net_gain > 0 ? "+" : ""}
                {t.expected_net_gain.toFixed(1)}
              </p>
              <p className="text-[10px] uppercase tracking-wide text-slate-500">
                pts / {t.horizon_gameweeks} GW
              </p>
            </div>
            <div>
              <p className="text-xl font-bold tabular-nums text-slate-900 sm:text-2xl dark:text-slate-100">
                {t.confidence}%
              </p>
              <p className="text-[10px] uppercase tracking-wide text-slate-500">
                confidence
              </p>
            </div>
          </div>
        </div>

        {t.hit_taken > 0 && (
          <p className="mt-3 rounded bg-amber-100 px-2 py-1 text-xs font-medium text-amber-900 dark:bg-amber-950/60 dark:text-amber-200">
            Takes a −{t.hit_taken} hit. The gain above is already net of it.
          </p>
        )}

        <button
          onClick={() => setShowWhy((v) => !v)}
          className="mt-2 inline-flex min-h-9 items-center text-xs font-semibold
                     text-slate-600 underline decoration-dotted hover:text-slate-900
                     sm:mt-3 sm:pointer-fine:min-h-0 dark:text-slate-400 dark:hover:text-slate-200"
        >
          {showWhy ? "Hide reasoning" : "Why this move?"}
        </button>

        {showWhy && (
          <div className="mt-3 space-y-3 border-t border-slate-200 pt-3 dark:border-slate-700">
            <div>
              <p className="mb-1.5 text-[10px] font-bold uppercase tracking-wide text-slate-500">
                Confidence is computed, not asserted
              </p>
              <div className="space-y-1">
                {Object.entries(t.factors).map(([name, value]) => (
                  <div key={name} className="flex items-center gap-2">
                    <span className="w-24 shrink-0 text-[11px] text-slate-600 sm:w-36 dark:text-slate-400">
                      {name.replace(/_/g, " ")}
                    </span>
                    <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
                      <div
                        className="h-full rounded-full bg-slate-700 dark:bg-slate-300"
                        style={{ width: `${Math.round(value * 100)}%` }}
                      />
                    </div>
                    <span className="w-9 shrink-0 text-right text-[11px] tabular-nums text-slate-500">
                      {Math.round(value * 100)}%
                    </span>
                    <span className="w-9 shrink-0 text-right text-[10px] tabular-nums text-slate-400">
                      ×{t.weights[name]?.toFixed(2)}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            {t.notes.length > 0 && (
              <ul className="space-y-1">
                {t.notes.map((n, i) => (
                  <li key={i} className="text-[11px] text-amber-700 dark:text-amber-400">
                    ⚠ {n}
                  </li>
                ))}
              </ul>
            )}

            {rec.transfer_alternatives.length > 0 && (
              <div>
                <p className="mb-1 text-[10px] font-bold uppercase tracking-wide text-slate-500">
                  Alternatives considered
                </p>
                <ul className="space-y-0.5">
                  {rec.transfer_alternatives.map((alt, i) => (
                    <li key={i} className="text-[11px] text-slate-600 dark:text-slate-400">
                      {alt.note} — net {alt.net_gain > 0 ? "+" : ""}
                      {alt.net_gain.toFixed(1)} pts
                      {alt.hit > 0 && ` (−${alt.hit} hit)`}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── Captain + lineup summary ──────────────────────────────────── */}
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800">
          <p className="text-[10px] font-bold uppercase tracking-widest text-slate-500">
            Captain
          </p>
          {best ? (
            <>
              <p className="mt-1 text-xl font-bold text-slate-900 dark:text-slate-50">
                {best.name}
              </p>
              <p className="text-xs text-slate-500">
                {best.team} · {best.position} · {best.expected_captain_points.toFixed(1)} xPts
                doubled
              </p>
              {rec.captain.vice && (
                <p className="mt-2 text-xs text-slate-600 dark:text-slate-400">
                  Vice: <span className="font-semibold">{rec.captain.vice.name}</span>
                </p>
              )}
              {runnerUp && (
                <p className="mt-2 text-[11px] text-slate-400">
                  Next best: {runnerUp.name} (
                  {(best.expected_captain_points - runnerUp.expected_captain_points).toFixed(1)}{" "}
                  pts behind)
                </p>
              )}
            </>
          ) : (
            <p className="mt-2 text-sm text-slate-400">No captain available</p>
          )}
        </div>

        <div className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800">
          <p className="text-[10px] font-bold uppercase tracking-widest text-slate-500">
            Best lineup
          </p>
          <p className="mt-1 text-xl font-bold text-slate-900 dark:text-slate-50">
            {rec.lineup.formation}
          </p>
          <p className="text-xs text-slate-500">
            {rec.lineup.projected_total.toFixed(1)} projected pts (XI + captain)
          </p>
          <p className="mt-2 text-[11px] text-slate-400">
            Bench worth {rec.lineup.bench_xpts.toFixed(1)} xPts
          </p>
        </div>
      </div>

      {/* ── Squad issues ──────────────────────────────────────────────── */}
      {rec.squad_issues.length > 0 && (
        <div className="rounded-lg border border-amber-300 bg-amber-50 p-4 dark:border-amber-800 dark:bg-amber-950/40">
          <p className="text-[10px] font-bold uppercase tracking-widest text-amber-800 dark:text-amber-300">
            {rec.squad_issues.length} squad{" "}
            {rec.squad_issues.length === 1 ? "issue" : "issues"}
          </p>
          <ul className="mt-2 space-y-1">
            {rec.squad_issues.map((issue) => (
              <li
                key={issue.player_id}
                className="text-xs text-amber-900 dark:text-amber-200"
              >
                <span className="font-semibold">{issue.name}</span> — {issue.reason}
                {issue.chance_of_playing !== null &&
                  ` (${issue.chance_of_playing}% chance)`}
                {issue.news && `: ${issue.news}`}
              </li>
            ))}
          </ul>
        </div>
      )}

      {rec.players_without_projection.length > 0 && (
        <p className="text-[11px] text-slate-400">
          No projection for: {rec.players_without_projection.join(", ")}. Re-run
          Sync FPL data.
        </p>
      )}
    </div>
  );
}
