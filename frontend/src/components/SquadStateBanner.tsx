"use client";

import { useEffect, useState } from "react";
import {
  api,
  ApiError,
  type PlayerSummary,
  type SquadState,
} from "@/lib/api";
import { BTN_PRIMARY, BTN_SECONDARY, SELECT } from "@/lib/ui";

interface Move {
  out: number;
  in: number;
}

/**
 * Lets a manager correct the squad we read from FPL.
 *
 * FPL's public API cannot show transfers made for a gameweek that has not
 * started, so the newest squad it reports is the one locked at the last
 * deadline. Without this, the app advises on a squad the manager no longer owns
 * — and will cheerfully re-suggest a transfer they have already made.
 */
export function SquadStateBanner({
  managerId,
  onChanged,
}: {
  managerId: number;
  onChanged?: () => void;
}) {
  const [state, setState] = useState<SquadState | null>(null);
  const [pool, setPool] = useState<PlayerSummary[]>([]);
  const [editing, setEditing] = useState(false);
  const [rows, setRows] = useState<{ out: string; in: string }[]>([
    { out: "", in: "" },
  ]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      setState(await api.squadState(managerId));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not read squad state");
    }
  }

  useEffect(() => {
    load();
  }, [managerId]);

  // Only fetch the (large) player list when the editor is actually opened.
  useEffect(() => {
    if (editing && pool.length === 0) {
      api
        .players({ limit: 300, sort_by: "total_points" })
        .then(setPool)
        .catch(() => setPool([]));
    }
  }, [editing, pool.length]);

  async function submit() {
    const moves: Move[] = rows
      .filter((r) => r.out && r.in)
      .map((r) => ({ out: Number(r.out), in: Number(r.in) }));

    if (moves.length === 0) {
      setError("Pick at least one player out and one in.");
      return;
    }

    setBusy(true);
    setError(null);
    try {
      setState(await api.recordTransfers(managerId, moves));
      setEditing(false);
      setRows([{ out: "", in: "" }]);
      onChanged?.();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not record transfers");
    } finally {
      setBusy(false);
    }
  }

  async function reset() {
    setBusy(true);
    try {
      await api.resetSquadState(managerId);
      await load();
      onChanged?.();
    } finally {
      setBusy(false);
    }
  }

  if (!state) return null;

  const corrected = state.squad_source === "manager_override";

  return (
    <div
      className={`mb-6 rounded-lg border p-4 ${
        corrected
          ? "border-sky-300 bg-sky-50 dark:border-sky-800 dark:bg-sky-950/40"
          : "border-amber-300 bg-amber-50 dark:border-amber-800 dark:bg-amber-950/40"
      }`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          {corrected ? (
            <>
              <p className="text-sm font-bold text-sky-900 dark:text-sky-200">
                Using your corrected squad
              </p>
              <p className="mt-0.5 text-xs text-sky-800 dark:text-sky-300">
                {state.transfers_applied?.length ?? 0} transfer
                {(state.transfers_applied?.length ?? 0) === 1 ? "" : "s"} recorded
                for GW{state.target_gameweek} · £{state.bank.toFixed(1)}m bank ·{" "}
                {state.free_transfers} free transfer
                {state.free_transfers === 1 ? "" : "s"} left
              </p>
              <p className="mt-1 text-[11px] text-sky-700 dark:text-sky-400">
                Discarded automatically once GW{state.target_gameweek} starts —
                FPL becomes the source of truth then.
              </p>
            </>
          ) : (
            <>
              <p className="text-sm font-bold text-amber-900 dark:text-amber-200">
                This may not be your current squad
              </p>
              <p className="mt-0.5 text-xs text-amber-800 dark:text-amber-300">
                {state.stale_warning ??
                  `Showing your GW${state.picks_gameweek} squad — the newest one FPL exposes publicly.`}
              </p>
            </>
          )}
        </div>

        <div className="flex w-full shrink-0 flex-wrap gap-2 sm:w-auto">
          {corrected && (
            <button
              onClick={reset}
              disabled={busy}
              className={`${BTN_SECONDARY} flex-1 sm:flex-none`}
            >
              Reset to FPL
            </button>
          )}
          <button
            onClick={() => setEditing((v) => !v)}
            className={`${BTN_PRIMARY} flex-1 sm:flex-none`}
          >
            {editing ? "Cancel" : corrected ? "Add more" : "Record my transfers"}
          </button>
        </div>
      </div>

      {editing && (
        <div className="mt-4 space-y-2 border-t border-slate-200 pt-3 dark:border-slate-700">
          <p className="text-[11px] text-slate-600 dark:text-slate-400">
            Pick who left and who arrived. Bank and free transfers update with them.
          </p>

          {/* Two player pickers side by side leave ~145px each on a phone,
              which truncates almost every name. They stack instead, and the
              arrow turns to point down to match. */}
          {rows.map((row, i) => (
            <div
              key={i}
              className="flex flex-col gap-2 sm:flex-row sm:items-center"
            >
              <select
                value={row.out}
                onChange={(e) => {
                  const next = [...rows];
                  next[i] = { ...next[i], out: e.target.value };
                  setRows(next);
                }}
                className={`${SELECT} min-w-0 flex-1 font-normal`}
              >
                <option value="">Player out…</option>
                {state.squad.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} ({p.position} · £{p.price.toFixed(1)})
                  </option>
                ))}
              </select>

              <span className="self-center text-slate-400" aria-hidden>
                <span className="sm:hidden">↓</span>
                <span className="hidden sm:inline">→</span>
              </span>

              <select
                value={row.in}
                onChange={(e) => {
                  const next = [...rows];
                  next[i] = { ...next[i], in: e.target.value };
                  setRows(next);
                }}
                className={`${SELECT} min-w-0 flex-1 font-normal`}
              >
                <option value="">Player in…</option>
                {pool
                  .filter((p) => !state.squad.some((s) => s.id === p.id))
                  .map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} ({p.position} · {p.team} · £{p.price.toFixed(1)})
                    </option>
                  ))}
              </select>

              {rows.length > 1 && (
                <button
                  onClick={() => setRows(rows.filter((_, j) => j !== i))}
                  className="inline-flex min-h-9 items-center justify-center rounded-md
                             text-xs text-slate-400 hover:text-red-500 sm:px-1 sm:pointer-fine:min-h-7"
                  aria-label="Remove this transfer"
                >
                  <span className="sm:hidden">Remove this transfer</span>
                  <span className="hidden sm:inline" aria-hidden>
                    ✕
                  </span>
                </button>
              )}
            </div>
          ))}

          <div className="flex flex-wrap gap-2 pt-1">
            <button
              onClick={() => setRows([...rows, { out: "", in: "" }])}
              className={`${BTN_SECONDARY} flex-1 sm:flex-none`}
            >
              + Another transfer
            </button>
            <button
              onClick={submit}
              disabled={busy}
              className={`${BTN_PRIMARY} flex-1 bg-emerald-600 hover:bg-emerald-700
                          sm:flex-none dark:bg-emerald-600 dark:text-white
                          dark:hover:bg-emerald-700`}
            >
              {busy ? "Saving…" : "Save"}
            </button>
          </div>

          {error && (
            <p className="text-xs text-red-600 dark:text-red-400">{error}</p>
          )}
        </div>
      )}
    </div>
  );
}
