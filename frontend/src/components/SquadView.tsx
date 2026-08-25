import type { Squad } from "@/lib/api";
import { PlayerCard } from "./PlayerCard";

const POSITION_ORDER = ["GKP", "DEF", "MID", "FWD"] as const;

export function SquadView({ squad }: { squad: Squad }) {
  const starters = squad.squad.filter((p) => p.is_starting);
  const bench = squad.squad.filter((p) => !p.is_starting);

  // Group the XI by position so it reads like a pitch
  const rows = POSITION_ORDER.map((pos) => ({
    position: pos,
    players: starters.filter((p) => p.position === pos),
  })).filter((row) => row.players.length > 0);

  const projectedPoints = starters.reduce(
    (sum, p) => sum + p.ep_next * (p.multiplier || 1),
    0,
  );
  const issues = squad.squad.filter((p) => p.status !== "a");

  return (
    <div className="space-y-6">
      {/* ── Summary strip ─────────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <SummaryTile
          label="Projected next GW"
          value={projectedPoints.toFixed(1)}
          accent
        />
        <SummaryTile label="Squad value" value={`£${squad.team_value.toFixed(1)}m`} />
        <SummaryTile label="In the bank" value={`£${squad.bank.toFixed(1)}m`} />
        <SummaryTile
          label="Free transfers"
          value={squad.free_transfers ?? "—"}
        />
      </div>

      {/* ── Squad issues ──────────────────────────────────────────── */}
      {issues.length > 0 && (
        <div className="rounded-lg border border-amber-300 bg-amber-50 p-4 dark:border-amber-800 dark:bg-amber-950/40">
          <h3 className="text-sm font-bold text-amber-900 dark:text-amber-200">
            {issues.length} squad {issues.length === 1 ? "issue" : "issues"}
          </h3>
          <ul className="mt-2 space-y-1">
            {issues.map((p) => (
              <li key={p.id} className="text-xs text-amber-800 dark:text-amber-300">
                <span className="font-semibold">{p.name}</span>
                {" — "}
                {p.status_label}
                {p.chance_this !== null && ` (${p.chance_this}% chance)`}
                {p.news && `: ${p.news}`}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* ── Starting XI ───────────────────────────────────────────── */}
      <section>
        <SectionHeading>Starting XI</SectionHeading>
        <div className="space-y-3">
          {rows.map((row) => (
            <div
              key={row.position}
              className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 sm:gap-3 md:grid-cols-4 lg:grid-cols-5"
            >
              {row.players.map((p) => (
                <PlayerCard key={p.id} pick={p} />
              ))}
            </div>
          ))}
        </div>
      </section>

      {/* ── Bench ─────────────────────────────────────────────────── */}
      <section>
        <SectionHeading>
          Bench{" "}
          <span className="font-normal text-slate-400">
            (in autosub order)
          </span>
        </SectionHeading>
        <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4 sm:gap-3">
          {bench.map((p) => (
            <PlayerCard key={p.id} pick={p} />
          ))}
        </div>
      </section>
    </div>
  );
}

function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="mb-3 text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">
      {children}
    </h2>
  );
}

function SummaryTile({
  label,
  value,
  accent = false,
}: {
  label: string;
  value: string | number;
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
      <p className="mt-0.5 text-[10px] font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">
        {label}
      </p>
    </div>
  );
}
