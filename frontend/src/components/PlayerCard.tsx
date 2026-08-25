"use client";

import { useState } from "react";
import Image from "next/image";
import type { SquadPick } from "@/lib/api";

const STATUS_STYLES: Record<string, string> = {
  a: "",
  d: "ring-2 ring-amber-400/70",
  i: "ring-2 ring-red-500/70",
  s: "ring-2 ring-red-500/70",
  u: "ring-2 ring-red-500/70",
  n: "ring-2 ring-slate-400/70",
};

const POSITION_COLORS: Record<string, string> = {
  GKP: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
  DEF: "bg-sky-500/15 text-sky-700 dark:text-sky-300",
  MID: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
  FWD: "bg-rose-500/15 text-rose-700 dark:text-rose-300",
  UNK: "bg-slate-500/15 text-slate-600 dark:text-slate-400",
};

export function PlayerCard({ pick }: { pick: SquadPick }) {
  const hasIssue = pick.status !== "a";
  // Not every player has a headshot — FPL returns 403 for some codes, so fall
  // back to the position badge rather than showing a broken image.
  const [photoFailed, setPhotoFailed] = useState(false);
  const showPhoto = Boolean(pick.photo) && !photoFailed;

  return (
    <div
      className={`relative rounded-lg border border-slate-200 bg-white p-2.5 shadow-sm transition sm:p-3
                  hover:shadow-md dark:border-slate-700 dark:bg-slate-800
                  ${STATUS_STYLES[pick.status] ?? ""}
                  ${pick.transferred_in ? "ring-2 ring-emerald-400/70" : ""}`}
    >
      {/* Captain / vice armband */}
      {(pick.is_captain || pick.is_vice_captain) && (
        <span
          className="absolute -top-2 -right-2 flex h-6 w-6 items-center justify-center
                     rounded-full bg-slate-900 text-[11px] font-bold text-white
                     dark:bg-white dark:text-slate-900"
          title={pick.is_captain ? "Captain" : "Vice-captain"}
        >
          {pick.is_captain ? "C" : "V"}
        </span>
      )}

      <div className="flex items-start gap-2 sm:gap-2.5">
        {showPhoto ? (
          <Image
            src={pick.photo as string}
            alt=""
            width={34}
            height={43}
            unoptimized
            onError={() => setPhotoFailed(true)}
            className="shrink-0 rounded"
          />
        ) : (
          // No image code — keep the layout stable rather than collapsing it
          <div
            className="flex h-[43px] w-[34px] shrink-0 items-center justify-center
                       rounded bg-slate-100 text-[9px] font-bold text-slate-400
                       dark:bg-slate-700"
            aria-hidden
          >
            {pick.position}
          </div>
        )}

        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-slate-900 dark:text-slate-100">
            {pick.name}
          </p>
          <div className="mt-1 flex items-center gap-1.5">
            <span
              className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${
                POSITION_COLORS[pick.position] ?? POSITION_COLORS.UNK
              }`}
            >
              {pick.position}
            </span>
            <span className="text-[11px] font-medium text-slate-500 dark:text-slate-400">
              {pick.team}
            </span>
          </div>
        </div>

        <span className="shrink-0 text-xs font-bold tabular-nums text-slate-700 dark:text-slate-300">
          £{pick.price.toFixed(1)}
        </span>
      </div>

      {/* Shows which player this one replaced, so a recorded transfer is
          visible on the card itself rather than only in the banner. */}
      {pick.transferred_in && pick.replaced_name && (
        <p className="mt-2 flex items-center gap-1 rounded bg-emerald-50 px-1.5 py-1
                      text-[10px] font-medium text-emerald-800
                      dark:bg-emerald-950/50 dark:text-emerald-200">
          <span className="line-through opacity-70">{pick.replaced_name}</span>
          <span aria-hidden>→</span>
          <span className="font-bold">{pick.name}</span>
        </p>
      )}

      <dl className="mt-2.5 grid grid-cols-3 gap-1 border-t border-slate-100 pt-2 dark:border-slate-700">
        <Stat label="Pts" value={pick.total_points} />
        <Stat label="Form" value={pick.form.toFixed(1)} />
        <Stat label="xPts" value={pick.ep_next.toFixed(1)} highlight />
      </dl>

      {hasIssue && (
        <p
          className="mt-2 line-clamp-2 rounded bg-amber-50 px-1.5 py-1 text-[10px]
                     leading-tight text-amber-800 dark:bg-amber-950/50 dark:text-amber-200"
          title={pick.news || pick.status_label}
        >
          {pick.chance_this !== null && `${pick.chance_this}% · `}
          {pick.news || pick.status_label}
        </p>
      )}
    </div>
  );
}

function Stat({
  label,
  value,
  highlight = false,
}: {
  label: string;
  value: string | number;
  highlight?: boolean;
}) {
  return (
    <div className="text-center">
      <dd
        className={`text-sm font-bold tabular-nums ${
          highlight
            ? "text-emerald-600 dark:text-emerald-400"
            : "text-slate-900 dark:text-slate-100"
        }`}
      >
        {value}
      </dd>
      <dt className="text-[9px] font-medium uppercase tracking-wide text-slate-400">
        {label}
      </dt>
    </div>
  );
}
