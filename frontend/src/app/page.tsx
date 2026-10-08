"use client";

import { useCallback, useEffect, useState } from "react";
import {
  api,
  ApiError,
  type FullRecommendation,
  type Gameweek,
  type Manager,
  type Squad,
} from "@/lib/api";
import { AccountGate, type SignedInAccount } from "@/components/AccountGate";
import { SquadView } from "@/components/SquadView";
import { ProjectionTable } from "@/components/ProjectionTable";
import { RecommendationCard } from "@/components/RecommendationCard";
import { NewsPanel } from "@/components/NewsPanel";
import { AccuracyPanel } from "@/components/AccuracyPanel";
import { PlannerTree } from "@/components/PlannerTree";
import { SquadStateBanner } from "@/components/SquadStateBanner";
import { DreamTeam } from "@/components/DreamTeam";
import { NotificationSettings } from "@/components/NotificationSettings";
import { ChipAdvisor } from "@/components/ChipAdvisor";
import { BTN_SECONDARY } from "@/lib/ui";

export default function Page() {
  return <AccountGate>{(account) => <Dashboard account={account} />}</AccountGate>;
}

function Dashboard({ account }: { account: SignedInAccount }) {
  const [gameweek, setGameweek] = useState<Gameweek | null>(null);
  const [manager, setManager] = useState<Manager | null>(null);
  const [squad, setSquad] = useState<Squad | null>(null);
  const [rec, setRec] = useState<FullRecommendation | null>(null);
  const [recLoading, setRecLoading] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [needsSync, setNeedsSync] = useState(false);
  const [mounted, setMounted] = useState(false);

  // ── Load the active gameweek on mount ──────────────────────────────────
  useEffect(() => {
    api
      .gameweek()
      .then(setGameweek)
      .catch((e: ApiError) => {
        // 404 means the DB is empty — explain that rather than showing an error
        if (e.status === 404) setNeedsSync(true);
        else setError(e.message);
      });
  }, []);

  // Locale-formatted dates differ between the server (UTC) and the browser
  // (local timezone). Rendering one during SSR causes a hydration mismatch,
  // which silently strips every event handler off the page. Only format the
  // deadline once we are definitely on the client.
  useEffect(() => setMounted(true), []);

  const loadTeam = useCallback(async (id: number) => {
    setLoading(true);
    setError(null);
    setRec(null);
    try {
      // Manager profile and squad are independent — fetch together
      const [m, s] = await Promise.all([api.manager(id), api.squad(id)]);
      setManager(m);
      setSquad(s);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong");
      setManager(null);
      setSquad(null);
      setLoading(false);
      return;
    }
    setLoading(false);

    // The recommendation runs an optimiser, so it is slower than the squad
    // fetch. Load it separately rather than making the squad wait for it.
    setRecLoading(true);
    try {
      setRec(await api.recommendation(id, { horizon: 5 }));
    } catch {
      // Projections may not be built yet — the squad view still works.
      setRec(null);
    } finally {
      setRecLoading(false);
    }
  }, []);

  // The team is the one connected to the account; there is nothing to type.
  useEffect(() => {
    void loadTeam(account.managerId);
  }, [account.managerId, loadTeam]);

  return (
    <div className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-6 sm:py-8">
      {/* ── Header ──────────────────────────────────────────────────── */}
      <header className="mb-6 flex flex-col gap-3 sm:mb-8 sm:flex-row sm:items-end sm:justify-between sm:gap-4">
        <div className="min-w-0">
          <h1 className="text-xl font-bold tracking-tight text-slate-900 sm:text-2xl dark:text-slate-50">
            FPL Copilot
          </h1>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            {gameweek ? (
              <>
                <span className="font-semibold text-slate-700 dark:text-slate-300">
                  Planning {gameweek.name}
                </span>
                {mounted && (
                  <>
                    {" · deadline "}
                    {formatDeadline(gameweek.deadline_time)}
                  </>
                )}
                {gameweek.current_gameweek !== null &&
                  gameweek.current_gameweek !== gameweek.id && (
                    <span className="text-slate-400">
                      {" · GW"}
                      {gameweek.current_gameweek} in progress
                    </span>
                  )}
              </>
            ) : (
              "Loading gameweek…"
            )}
          </p>
        </div>
        <div className="flex items-center gap-3 text-xs text-slate-500 dark:text-slate-400">
          <span className="truncate">{account.email ?? account.teamName}</span>
          <button className={BTN_SECONDARY} onClick={account.signOut}>
            Sign out
          </button>
        </div>
      </header>

      {/* ── Empty database prompt ───────────────────────────────────── */}
      {needsSync && (
        <div className="mb-6 rounded-lg border border-sky-300 bg-sky-50 p-4 dark:border-sky-800 dark:bg-sky-950/40">
          <h2 className="text-sm font-bold text-sky-900 dark:text-sky-200">
            No FPL data yet
          </h2>
          <p className="mt-1 text-xs text-sky-800 dark:text-sky-300">
            The database is empty. The scheduled refresh pulls players, teams,
            gameweeks and fixtures from the FPL API every 30 minutes; check back
            shortly.
          </p>
        </div>
      )}

      {/* ── Error ───────────────────────────────────────────────────── */}
      {error && (
        <div className="mb-6 rounded-lg border border-red-300 bg-red-50 p-4 dark:border-red-800 dark:bg-red-950/40">
          <p className="text-sm text-red-800 dark:text-red-300">{error}</p>
        </div>
      )}

      {/* ── Manager header ──────────────────────────────────────────── */}
      {manager && (
        <div className="mb-6 rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800">
          <div className="flex flex-wrap items-baseline justify-between gap-3">
            <div className="min-w-0">
              <h2 className="text-base font-bold text-slate-900 sm:text-lg dark:text-slate-100">
                {manager.team_name}
              </h2>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {manager.manager_name}
              </p>
            </div>
            <div className="flex gap-5 sm:gap-6 sm:text-right">
              <div>
                <p className="text-lg font-bold tabular-nums text-slate-900 dark:text-slate-100">
                  {manager.overall_points ?? "—"}
                </p>
                <p className="text-[10px] uppercase tracking-wide text-slate-400">
                  Total pts
                </p>
              </div>
              <div>
                <p className="text-lg font-bold tabular-nums text-slate-900 dark:text-slate-100">
                  {manager.overall_rank?.toLocaleString() ?? "—"}
                </p>
                <p className="text-[10px] uppercase tracking-wide text-slate-400">
                  Overall rank
                </p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── Which squad is this advice about? ───────────────────────── */}
      {manager && (
        <SquadStateBanner
          key={`sq-${manager.id}`}
          managerId={manager.id}
          onChanged={() => loadTeam(manager.id)}
        />
      )}

      {/* ── The recommendation, above the raw squad ─────────────────── */}
      {recLoading && (
        <div className="mb-6 rounded-xl border-2 border-dashed border-slate-300 p-8 text-center dark:border-slate-700">
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Optimising your squad…
          </p>
        </div>
      )}
      {rec && !recLoading && (
        <div className="mb-8">
          <RecommendationCard rec={rec} />
        </div>
      )}

      {/* ── Squad ───────────────────────────────────────────────────── */}
      {squad && <SquadView squad={squad} />}

      {!squad && !loading && !error && !needsSync && (
        <div className="rounded-lg border border-dashed border-slate-300 p-12 text-center dark:border-slate-700">
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Loading your squad…
          </p>
        </div>
      )}

      {/* ── Chips ───────────────────────────────────────────────────── */}
      {manager && (
        <div className="mt-8 border-t border-slate-200 pt-6 sm:mt-10 sm:pt-8 dark:border-slate-700">
          <ChipAdvisor key={`chips-${manager.id}`} managerId={manager.id} />
        </div>
      )}

      {/* ── Multi-gameweek planner ──────────────────────────────────── */}
      {manager && (
        <div className="mt-8 border-t border-slate-200 pt-6 sm:mt-10 sm:pt-8 dark:border-slate-700">
          <PlannerTree key={`plan-${manager.id}`} managerId={manager.id} />
        </div>
      )}

      {/* ── Accuracy track record ───────────────────────────────────── */}
      {manager && (
        <div className="mt-8 border-t border-slate-200 pt-6 sm:mt-10 sm:pt-8 dark:border-slate-700">
          <AccuracyPanel key={`acc-${manager.id}`} managerId={manager.id} />
        </div>
      )}

      {/* ── Alert delivery settings ─────────────────────────────────── */}
      {manager && (
        <div className="mt-8 border-t border-slate-200 pt-6 sm:mt-10 sm:pt-8 dark:border-slate-700">
          <NotificationSettings key={`notify-${manager.id}`} managerId={manager.id} />
        </div>
      )}

      {/* ── News & alerts ───────────────────────────────────────────── */}
      {!needsSync && (
        <div className="mt-8 border-t border-slate-200 pt-6 sm:mt-10 sm:pt-8 dark:border-slate-700">
          <NewsPanel
            key={`news-${manager?.id ?? "none"}`}
            managerId={manager?.id ?? null}
          />
        </div>
      )}

      {/* ── Best possible squad (independent of what you own) ───────── */}
      {!needsSync && (
        <div className="mt-8 border-t border-slate-200 pt-6 sm:mt-10 sm:pt-8 dark:border-slate-700">
          <DreamTeam />
        </div>
      )}

      {/* ── Projections ─────────────────────────────────────────────── */}
      {!needsSync && (
        <div className="mt-8 border-t border-slate-200 pt-6 sm:mt-10 sm:pt-8 dark:border-slate-700">
          <ProjectionTable />
        </div>
      )}
    </div>
  );
}

function formatDeadline(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}
