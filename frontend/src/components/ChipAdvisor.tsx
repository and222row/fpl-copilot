"use client";

import { useEffect, useState } from "react";
import { api, ApiError, type ChipAdvice, type ChipItem } from "@/lib/api";

/**
 * Chip timing.
 *
 * Presented in the order the underlying facts can be trusted, because that
 * ordering is the honest thing about this feature. Fixture shape is a count and
 * cannot be wrong the way a projection can; chip availability comes from FPL's
 * own record; the valuations rest on a model with one unflattering accuracy
 * reading; and the verdicts are a heuristic on top of those. Chip advice
 * compounds model error — a wildcard stakes fifteen projections at once — so
 * the interface shows its working rather than issuing an instruction.
 */
const VERDICT_STYLE: Record<string, { label: string; className: string }> = {
  use_now: {
    label: "Play it",
    className: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
  },
  use_soon: {
    label: "Soon",
    className: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
  },
  consider: {
    label: "Consider",
    className: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
  },
  hold: {
    label: "Hold",
    className: "bg-slate-500/15 text-slate-600 dark:text-slate-400",
  },
  used: {
    label: "Played",
    className: "bg-slate-500/15 text-slate-500",
  },
  not_yet: {
    label: "Later window",
    className: "bg-slate-500/10 text-slate-400",
  },
  expired: { label: "Expired", className: "bg-red-500/15 text-red-700" },
  unknown: { label: "No data", className: "bg-slate-500/10 text-slate-400" },
};

export function ChipAdvisor({ managerId }: { managerId: number }) {
  const [data, setData] = useState<ChipAdvice | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    api
      .chipAdvice(managerId, 5)
      .then(setData)
      .catch((e) =>
        setError(e instanceof ApiError ? e.message : "Could not load chip advice"),
      )
      .finally(() => setLoading(false));
  }, [managerId]);

  if (loading) {
    return (
      <section>
        <Heading />
        <p className="py-6 text-center text-sm text-slate-400">
          Valuing your chips…
        </p>
      </section>
    );
  }

  if (error || !data) {
    return (
      <section>
        <Heading />
        <p className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs text-amber-800 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-300">
          {error ?? "No chip advice available."}
        </p>
      </section>
    );
  }

  // Only the half currently in play; the second set is noise until GW20.
  const current = data.chips.filter(
    (c) => c.window.start <= data.target_gameweek && data.target_gameweek <= c.window.end,
  );
  const doubles = Object.entries(data.fixture_shape.doubles);
  const blanks = Object.entries(data.fixture_shape.blanks);

  return (
    <section>
      <Heading />

      {/* ── Fact first: the fixture shape ─────────────────────────────── */}
      <div className="mb-3 rounded-lg border border-slate-200 bg-white p-3 dark:border-slate-700 dark:bg-slate-800">
        <p className="text-[10px] font-bold uppercase tracking-widest text-slate-500">
          Fixture shape
        </p>
        {doubles.length === 0 && blanks.length === 0 ? (
          <p className="mt-1 text-xs text-slate-600 dark:text-slate-400">
            No double or blank gameweeks are scheduled. They appear later in the
            season, when postponed fixtures are rearranged — three of the four
            chips are worth roughly double in one, so this is what to wait for.
          </p>
        ) : (
          <div className="mt-1 space-y-1 text-xs text-slate-700 dark:text-slate-300">
            {doubles.map(([gw, teams]) => (
              <p key={`d${gw}`}>
                <span className="font-semibold text-emerald-700 dark:text-emerald-400">
                  GW{gw} double
                </span>{" "}
                — {teams.length} team{teams.length === 1 ? "" : "s"}: {teams.join(", ")}
              </p>
            ))}
            {blanks.map(([gw, teams]) => (
              <p key={`b${gw}`}>
                <span className="font-semibold text-red-700 dark:text-red-400">
                  GW{gw} blank
                </span>{" "}
                — {teams.length} team{teams.length === 1 ? "" : "s"} idle
              </p>
            ))}
          </div>
        )}
        <p className="mt-2 text-[11px] text-slate-500">
          Your squad in GW{data.target_gameweek}:{" "}
          {data.squad_this_gameweek.playing} playing
          {data.squad_this_gameweek.doubling > 0 &&
            `, ${data.squad_this_gameweek.doubling} twice`}
          {data.squad_this_gameweek.blank > 0 &&
            `, ${data.squad_this_gameweek.blank} blank`}
        </p>
      </div>

      {!data.history_available && (
        <p className="mb-3 rounded-lg border border-amber-300 bg-amber-50 p-2 text-[11px] text-amber-800 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-300">
          Could not read which chips you have already played, so these may
          include one you have spent.
        </p>
      )}

      <ul className="space-y-2">
        {current.map((chip) => (
          <ChipRow key={`${chip.name}-${chip.window.start}`} chip={chip} />
        ))}
      </ul>

      <p className="mt-3 text-[10px] leading-relaxed text-slate-400">
        {data.caveat}
      </p>
    </section>
  );
}

function ChipRow({ chip }: { chip: ChipItem }) {
  const [open, setOpen] = useState(false);
  const style = VERDICT_STYLE[chip.verdict] ?? VERDICT_STYLE.unknown;

  return (
    <li className="rounded-lg border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-800">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-3 px-3 py-3 text-left transition
                   hover:bg-slate-50 dark:hover:bg-slate-800/50"
      >
        <div className="min-w-0 flex-1">
          <p className="flex flex-wrap items-center gap-2 text-sm font-semibold text-slate-900 dark:text-slate-100">
            {chip.label}
            <span
              className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${style.className}`}
            >
              {style.label}
            </span>
          </p>
          <p className="mt-0.5 text-[11px] text-slate-500">
            {chip.used_in_gameweek
              ? `Played in GW${chip.used_in_gameweek}`
              : `${chip.weeks_remaining} gameweek${chip.weeks_remaining === 1 ? "" : "s"} left · expires GW${chip.window.end}`}
          </p>
        </div>

        {chip.value_now !== null && (
          <div className="shrink-0 text-right">
            <p className="text-sm font-bold tabular-nums text-slate-900 dark:text-slate-100">
              {chip.value_now.toFixed(1)}
            </p>
            <p className="text-[10px] text-slate-400">pts if played now</p>
          </div>
        )}
        <span className="shrink-0 text-xs text-slate-400" aria-hidden>
          {open ? "▾" : "▸"}
        </span>
      </button>

      {open && (
        <div className="border-t border-slate-100 bg-slate-50 px-3 py-2 dark:border-slate-700 dark:bg-slate-800/40">
          <ul className="space-y-1">
            {chip.reasons.map((r, i) => (
              <li
                key={i}
                className="flex gap-2 text-[11px] leading-relaxed text-slate-600 dark:text-slate-400"
              >
                <span className="text-slate-400" aria-hidden>
                  •
                </span>
                <span>{r}</span>
              </li>
            ))}
          </ul>
          <p className="mt-2 flex flex-wrap gap-x-3 gap-y-1 border-t border-slate-200 pt-2 text-[10px] text-slate-400 dark:border-slate-700">
            {chip.best_value !== null && chip.best_gameweek !== null && (
              <span>
                best in view: {chip.best_value.toFixed(1)} @ GW{chip.best_gameweek}
              </span>
            )}
            {chip.baseline !== null && (
              <span>typical week: {chip.baseline.toFixed(1)}</span>
            )}
            <span>confidence: {chip.confidence}</span>
          </p>
        </div>
      )}
    </li>
  );
}

function Heading() {
  return (
    <h2 className="mb-3 text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">
      Chips — when to play them
    </h2>
  );
}
