"use client";

import { useEffect, useState } from "react";
import { api, ApiError, type ProjectionRow } from "@/lib/api";
import {
  BTN_SECONDARY,
  SEGMENT_BASE,
  SEGMENT_GROUP,
  SEGMENT_OFF,
  SEGMENT_ON,
} from "@/lib/ui";

const POSITIONS = [
  { id: undefined, label: "All" },
  { id: 1, label: "GKP" },
  { id: 2, label: "DEF" },
  { id: 3, label: "MID" },
  { id: 4, label: "FWD" },
];

/** FDR 1 = easiest fixture, 5 = hardest. */
function fdrClass(fdr: number): string {
  if (fdr <= 2) return "bg-emerald-500/20 text-emerald-800 dark:text-emerald-300";
  if (fdr <= 2.75) return "bg-lime-500/20 text-lime-800 dark:text-lime-300";
  if (fdr <= 3.5) return "bg-amber-500/20 text-amber-800 dark:text-amber-300";
  if (fdr <= 4.25) return "bg-orange-500/20 text-orange-800 dark:text-orange-300";
  return "bg-red-500/20 text-red-800 dark:text-red-300";
}

export function ProjectionTable() {
  const [rows, setRows] = useState<ProjectionRow[] | null>(null);
  const [position, setPosition] = useState<number | undefined>(undefined);
  const [sortByValue, setSortByValue] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    setError(null);
    api
      .projections({ position, min_minutes: 45, limit: 25 })
      .then(setRows)
      .catch((e: ApiError) => {
        setError(e.message);
        setRows(null);
      })
      .finally(() => setLoading(false));
  }, [position]);

  const sorted = rows
    ? [...rows].sort((a, b) => (sortByValue ? b.value - a.value : b.xpts - a.xpts))
    : null;

  return (
    <section>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">
          Top projected — next gameweek
        </h2>
        <div className="flex flex-wrap items-center gap-2">
          <div className={SEGMENT_GROUP}>
            {POSITIONS.map((p) => (
              <button
                key={p.label}
                onClick={() => setPosition(p.id)}
                className={`${SEGMENT_BASE} ${
                  position === p.id ? SEGMENT_ON : SEGMENT_OFF
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>
          <button
            onClick={() => setSortByValue((v) => !v)}
            className={BTN_SECONDARY}
          >
            {sortByValue ? "Sort: value" : "Sort: xPts"}
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs text-amber-800 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-300">
          {error}
        </div>
      )}

      {loading && !error && (
        <p className="py-8 text-center text-sm text-slate-400">Loading projections…</p>
      )}

      {sorted && !loading && (
        <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-700">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 dark:bg-slate-800/60">
              <tr className="text-left text-[10px] uppercase tracking-wide text-slate-500">
                {/* Nine columns cannot fit a phone. Position and team fold
                    under the player's name below `sm`, and the derived
                    figures drop out entirely until there is room. */}
                <th className="px-3 py-2 font-semibold">Player</th>
                <th className="hidden px-2 py-2 font-semibold sm:table-cell">Pos</th>
                <th className="hidden px-2 py-2 font-semibold sm:table-cell">Team</th>
                <th className="px-2 py-2 text-right font-semibold">£</th>
                <th className="px-2 py-2 text-right font-semibold">xPts</th>
                <th className="hidden px-2 py-2 text-right font-semibold md:table-cell">
                  Value
                </th>
                <th className="hidden px-2 py-2 text-right font-semibold md:table-cell">
                  Mins
                </th>
                <th className="px-2 py-2 text-center font-semibold">FDR</th>
                <th className="hidden px-2 py-2 text-center font-semibold sm:table-cell">
                  Pen
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-700">
              {sorted.map((r) => (
                <tr
                  key={r.player_id}
                  className="transition hover:bg-slate-50 dark:hover:bg-slate-800/50"
                >
                  <td className="px-3 py-2 font-semibold text-slate-900 dark:text-slate-100">
                    {r.name}
                    {r.fixture_count > 1 && (
                      <span
                        className="ml-1.5 rounded bg-violet-500/20 px-1 text-[9px] font-bold text-violet-700 dark:text-violet-300"
                        title={`Double gameweek — ${r.fixture_count} fixtures`}
                      >
                        DGW
                      </span>
                    )}
                    {/* Stands in for the Pos and Team columns on phones */}
                    <span className="block text-[11px] font-normal text-slate-400 sm:hidden">
                      {r.position} · {r.team}
                      {r.is_penalty_taker && (
                        <span title="First-choice penalty taker"> · ⚽</span>
                      )}
                    </span>
                  </td>
                  <td className="hidden px-2 py-2 text-xs text-slate-500 sm:table-cell">
                    {r.position}
                  </td>
                  <td className="hidden px-2 py-2 text-xs text-slate-500 sm:table-cell">
                    {r.team}
                  </td>
                  <td className="px-2 py-2 text-right tabular-nums text-slate-700 dark:text-slate-300">
                    {r.price.toFixed(1)}
                  </td>
                  <td className="px-2 py-2 text-right font-bold tabular-nums text-emerald-600 dark:text-emerald-400">
                    {r.xpts.toFixed(2)}
                  </td>
                  <td className="hidden px-2 py-2 text-right tabular-nums text-slate-600 md:table-cell dark:text-slate-400">
                    {r.value.toFixed(2)}
                  </td>
                  <td className="hidden px-2 py-2 text-right tabular-nums text-slate-500 md:table-cell">
                    {Math.round(r.expected_minutes)}
                  </td>
                  <td className="px-2 py-2 text-center">
                    <span
                      className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${fdrClass(r.custom_fdr)}`}
                      title="Custom FDR from expected goals conceded (1 easiest, 5 hardest)"
                    >
                      {r.custom_fdr.toFixed(1)}
                    </span>
                  </td>
                  <td className="hidden px-2 py-2 text-center text-xs sm:table-cell">
                    {r.is_penalty_taker ? (
                      <span title="First-choice penalty taker">⚽</span>
                    ) : (
                      ""
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="mt-2 text-[10px] text-slate-400">
        xPts from our own projection model (not FPL&apos;s). Value = xPts per £1m.
        FDR is derived from expected goals conceded, not FPL&apos;s static rating.
      </p>
    </section>
  );
}
