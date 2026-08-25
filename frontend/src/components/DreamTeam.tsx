"use client";

import { useState } from "react";
import Image from "next/image";
import { api, ApiError, type DreamPick, type DreamTeam } from "@/lib/api";
import { BTN_PRIMARY, SELECT } from "@/lib/ui";

const POSITION_ORDER = ["GKP", "DEF", "MID", "FWD"] as const;

const POSITION_COLORS: Record<string, string> = {
  GKP: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
  DEF: "bg-sky-500/15 text-sky-700 dark:text-sky-300",
  MID: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
  FWD: "bg-rose-500/15 text-rose-700 dark:text-rose-300",
};

/** FDR 1 = easiest, 5 = hardest. */
function fdrClass(fdr: number): string {
  if (fdr <= 2) return "bg-emerald-500/20 text-emerald-800 dark:text-emerald-300";
  if (fdr <= 2.75) return "bg-lime-500/20 text-lime-800 dark:text-lime-300";
  if (fdr <= 3.5) return "bg-amber-500/20 text-amber-800 dark:text-amber-300";
  if (fdr <= 4.25) return "bg-orange-500/20 text-orange-800 dark:text-orange-300";
  return "bg-red-500/20 text-red-800 dark:text-red-300";
}

function PickRow({ pick }: { pick: DreamPick }) {
  const [open, setOpen] = useState(false);
  const [photoFailed, setPhotoFailed] = useState(false);
  const showPhoto = Boolean(pick.photo) && !photoFailed;

  return (
    <li className="border-b border-slate-100 last:border-0 dark:border-slate-700">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-3 px-3 py-2.5 text-left transition
                   hover:bg-slate-50 dark:hover:bg-slate-800/50"
      >
        {showPhoto ? (
          <Image
            src={pick.photo as string}
            alt=""
            width={30}
            height={38}
            unoptimized
            onError={() => setPhotoFailed(true)}
            className="shrink-0 rounded"
          />
        ) : (
          <div
            className="flex h-[38px] w-[30px] shrink-0 items-center justify-center rounded
                       bg-slate-100 text-[9px] font-bold text-slate-400 dark:bg-slate-700"
            aria-hidden
          >
            {pick.position}
          </div>
        )}

        <div className="min-w-0 flex-1">
          <p className="flex items-center gap-1.5 text-sm font-semibold text-slate-900 dark:text-slate-100">
            <span className="truncate">{pick.name}</span>
            {pick.is_captain && (
              <span
                className="rounded bg-slate-900 px-1 text-[9px] font-bold text-white
                           dark:bg-white dark:text-slate-900"
                title="Captain"
              >
                C
              </span>
            )}
            {pick.is_vice_captain && (
              <span
                className="rounded bg-slate-400 px-1 text-[9px] font-bold text-white"
                title="Vice-captain"
              >
                V
              </span>
            )}
          </p>
          <div className="mt-0.5 flex items-center gap-1.5">
            <span
              className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${
                POSITION_COLORS[pick.position] ?? ""
              }`}
            >
              {pick.position}
            </span>
            <span className="text-[11px] text-slate-500">{pick.team}</span>
            <span
              className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${fdrClass(pick.custom_fdr)}`}
              title="Custom fixture difficulty (1 easiest, 5 hardest)"
            >
              {pick.custom_fdr.toFixed(1)}
            </span>
          </div>
        </div>

        <div className="shrink-0 text-right">
          <p className="text-sm font-bold tabular-nums text-emerald-600 dark:text-emerald-400">
            {pick.gw_xpts.toFixed(2)}
          </p>
          <p className="text-[10px] text-slate-400">£{pick.price.toFixed(1)}m</p>
        </div>

        <span className="shrink-0 text-xs text-slate-400" aria-hidden>
          {open ? "▾" : "▸"}
        </span>
      </button>

      {open && (
        <div className="bg-slate-50 px-3 pb-3 pt-1 dark:bg-slate-800/40">
          <ul className="space-y-1">
            {pick.reasons.map((r, i) => (
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
          {Object.keys(pick.components).length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5 border-t border-slate-200 pt-2 dark:border-slate-700">
              {Object.entries(pick.components)
                .filter(([, v]) => Math.abs(v) >= 0.05)
                .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
                .map(([k, v]) => (
                  <span
                    key={k}
                    className="rounded bg-white px-1.5 py-0.5 text-[10px] text-slate-600
                               dark:bg-slate-900 dark:text-slate-400"
                  >
                    {k.replace(/_/g, " ")}{" "}
                    <span className="font-bold tabular-nums">
                      {v > 0 ? "+" : ""}
                      {v.toFixed(2)}
                    </span>
                  </span>
                ))}
            </div>
          )}
        </div>
      )}
    </li>
  );
}

/**
 * The best legal 15 from the entire player pool, ignoring what the user owns.
 *
 * Deliberately not framed as "AI": the squad comes from the projection model
 * and an exact solver, and each reason is a number from that model. Calling it
 * AI would oversell it and make the reasoning sound less checkable than it is.
 */
export function DreamTeam() {
  const [team, setTeam] = useState<DreamTeam | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [horizon, setHorizon] = useState(1);
  const [budget, setBudget] = useState(100);

  async function build() {
    setLoading(true);
    setError(null);
    try {
      setTeam(await api.dreamTeam({ budget, horizon }));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not build the squad");
      setTeam(null);
    } finally {
      setLoading(false);
    }
  }

  const rows = team
    ? POSITION_ORDER.flatMap((pos) =>
        team.starting
          .filter((p) => p.position === pos)
          .sort((a, b) => b.gw_xpts - a.gw_xpts),
      )
    : [];

  return (
    <section>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">
          Best possible squad
        </h2>
        {/* Two selects share a row on a phone and the button takes the next
            one; from `sm` up the three sit inline as before. */}
        <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto">
          <select
            value={horizon}
            onChange={(e) => setHorizon(Number(e.target.value))}
            className={`${SELECT} min-w-0 flex-1 sm:flex-none`}
          >
            <option value={1}>Next gameweek</option>
            <option value={3}>Next 3 GWs</option>
            <option value={5}>Next 5 GWs</option>
          </select>
          <select
            value={budget}
            onChange={(e) => setBudget(Number(e.target.value))}
            className={`${SELECT} min-w-0 flex-1 sm:flex-none`}
          >
            {[95, 100, 105, 110].map((b) => (
              <option key={b} value={b}>
                £{b}.0m budget
              </option>
            ))}
          </select>
          <button
            onClick={build}
            disabled={loading}
            className={`${BTN_PRIMARY} w-full sm:w-auto`}
          >
            {loading ? "Solving…" : team ? "Rebuild" : "Build best squad"}
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs text-amber-800 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-300">
          {error}
        </div>
      )}

      {!team && !loading && !error && (
        <div className="rounded-lg border border-dashed border-slate-300 p-6 dark:border-slate-700">
          <p className="text-sm text-slate-600 dark:text-slate-400">
            Build the strongest legal 15 from every available player — ignoring
            what you currently own.
          </p>
          <p className="mt-1 text-xs text-slate-500">
            Answers &ldquo;if I wildcarded right now, what would I pick?&rdquo;.
            Squad, XI and captaincy are solved together, and each player comes
            with the numbers behind his selection.
          </p>
        </div>
      )}

      {loading && (
        <p className="py-8 text-center text-sm text-slate-400">
          Searching every legal combination…
        </p>
      )}

      {team && !loading && (
        <>
          <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Tile
              label={`projected GW${team.gameweeks[0]}`}
              value={team.projected_next_gw.toFixed(1)}
              accent
            />
            <Tile label="formation" value={team.formation} />
            <Tile label="spent" value={`£${team.squad_cost.toFixed(1)}m`} />
            <Tile
              label="money left"
              value={`£${team.money_left.toFixed(1)}m`}
            />
          </div>

          <p className="mb-3 text-[11px] text-slate-500 dark:text-slate-400">
            Optimal across{" "}
            <span className="font-semibold">
              {team.candidates_considered} available players
            </span>{" "}
            · captain {team.captain} · vice {team.vice_captain}
            {team.horizon_truncated && " · horizon shortened to the gameweeks with projections"}
          </p>

          <p className="mb-3 text-xs font-bold uppercase tracking-wide text-slate-400">
            Starting XI — tap a player for the reasoning
          </p>
          <ul className="mb-4 overflow-hidden rounded-lg border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-800">
            {rows.map((p) => (
              <PickRow key={p.player_id} pick={p} />
            ))}
          </ul>

          <p className="mb-3 text-xs font-bold uppercase tracking-wide text-slate-400">
            Bench (autosub order)
          </p>
          <ul className="overflow-hidden rounded-lg border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-800">
            {team.bench.map((p) => (
              <PickRow key={p.player_id} pick={p} />
            ))}
          </ul>

          <p className="mt-3 text-[10px] leading-relaxed text-slate-400">
            {team.explanation_note}
          </p>
        </>
      )}
    </section>
  );
}

function Tile({
  label,
  value,
  accent = false,
}: {
  label: string;
  value: string;
  accent?: boolean;
}) {
  return (
    <div
      className={`rounded-lg border p-3 ${
        accent
          ? "border-emerald-300 bg-emerald-50 dark:border-emerald-800 dark:bg-emerald-950/40"
          : "border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-800"
      }`}
    >
      <p
        className={`text-xl font-bold tabular-nums ${
          accent
            ? "text-emerald-700 dark:text-emerald-300"
            : "text-slate-900 dark:text-slate-100"
        }`}
      >
        {value}
      </p>
      <p className="mt-0.5 text-[10px] font-medium uppercase tracking-wide text-slate-500">
        {label}
      </p>
    </div>
  );
}
