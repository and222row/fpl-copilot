"use client";

import { useEffect, useMemo, useState } from "react";
import { api, ApiError, type Plan, type PlanNode } from "@/lib/api";
import { BTN_PRIMARY, BTN_SECONDARY, SELECT } from "@/lib/ui";

/**
 * Node box geometry, in SVG units.
 *
 * A horizontal tree of five to eight columns cannot fit a phone at desktop
 * sizing — it came out at 1320px against a 375px viewport. The compact set
 * roughly halves that so the panel scrolls two screens instead of four, while
 * keeping the text above 9px where it stays legible.
 */
const GEOMETRY = {
  wide: {
    NODE_W: 168,
    NODE_H: 62,
    GAP_X: 56,
    GAP_Y: 16,
    PAD: 16,
    PADX: 10,
    FONT_TITLE: 11,
    FONT_BODY: 10,
    FONT_META: 9,
    // Free transfers and bank sit beside the running total on a wide node.
    // There is no room for them at 116px, and both appear in the detail panel
    // and the best-path table anyway.
    SHOW_META: true,
    ROOT_LABEL: "Current squad",
  },
  compact: {
    NODE_W: 116,
    NODE_H: 58,
    GAP_X: 26,
    GAP_Y: 12,
    PAD: 10,
    PADX: 7,
    FONT_TITLE: 10,
    FONT_BODY: 9,
    FONT_META: 8,
    SHOW_META: false,
    ROOT_LABEL: "Current",
  },
} as const;

type Geometry = (typeof GEOMETRY)[keyof typeof GEOMETRY];

interface Positioned extends PlanNode {
  x: number;
  y: number;
}


/**
 * Lay the tree out column-per-gameweek.
 *
 * Children are grouped under their parent so connectors stay readable; with a
 * beam width of four or less the columns are short enough that a full tidy-tree
 * algorithm would be more machinery than the problem needs.
 */
function layout(
  nodes: PlanNode[],
  g: Geometry,
): { placed: Positioned[]; width: number; height: number } {
  const { NODE_W, NODE_H, GAP_X, GAP_Y, PAD } = g;
  const byDepth = new Map<number, PlanNode[]>();
  for (const n of nodes) {
    const list = byDepth.get(n.depth) ?? [];
    list.push(n);
    byDepth.set(n.depth, list);
  }

  const placed: Positioned[] = [];
  let maxRows = 0;

  for (const depth of [...byDepth.keys()].sort((a, b) => a - b)) {
    const column = byDepth.get(depth)!;
    // Group by parent, then put the strongest option at the top of each group
    column.sort(
      (a, b) =>
        (a.parent_id ?? -1) - (b.parent_id ?? -1) ||
        b.cumulative_xpts - a.cumulative_xpts,
    );
    column.forEach((n, i) => {
      placed.push({
        ...n,
        x: PAD + depth * (NODE_W + GAP_X),
        y: PAD + i * (NODE_H + GAP_Y),
      });
    });
    maxRows = Math.max(maxRows, column.length);
  }

  const depths = byDepth.size;
  return {
    placed,
    width: PAD * 2 + depths * NODE_W + (depths - 1) * GAP_X,
    height: PAD * 2 + maxRows * NODE_H + (maxRows - 1) * GAP_Y,
  };
}

export function PlannerTree({ managerId }: { managerId: number | null }) {
  const [plan, setPlan] = useState<Plan | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [horizon, setHorizon] = useState(5);
  const [selected, setSelected] = useState<number | null>(null);
  const [showPruned, setShowPruned] = useState(true);

  async function build(id: number, h: number) {
    setLoading(true);
    setError(null);
    setSelected(null);
    try {
      setPlan(await api.plan(id, { horizon: h }));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not build the plan");
      setPlan(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setPlan(null);
    setError(null);
  }, [managerId]);

  const visible = useMemo(
    () => (plan ? plan.tree.filter((n) => showPruned || !n.pruned) : []),
    [plan, showPruned],
  );
  const selectedNode =
    selected !== null ? visible.find((n) => n.id === selected) : undefined;

  if (managerId === null) return null;

  return (
    <section>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">
          Multi-gameweek planner
        </h2>
        <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto">
          <select
            value={horizon}
            onChange={(e) => setHorizon(Number(e.target.value))}
            className={`${SELECT} flex-1 sm:flex-none`}
          >
            {[3, 4, 5, 6, 8].map((h) => (
              <option key={h} value={h}>
                {h} gameweeks
              </option>
            ))}
          </select>
          {plan && (
            <button
              onClick={() => setShowPruned((v) => !v)}
              className={`${BTN_SECONDARY} flex-1 sm:flex-none`}
            >
              {showPruned ? "Hide rejected" : "Show rejected"}
            </button>
          )}
          <button
            onClick={() => build(managerId, horizon)}
            disabled={loading}
            className={`${BTN_PRIMARY} w-full sm:w-auto`}
          >
            {loading ? "Searching…" : plan ? "Rebuild" : "Build plan"}
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs text-amber-800 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-300">
          {error}
        </div>
      )}

      {!plan && !loading && !error && (
        <div className="rounded-lg border border-dashed border-slate-300 p-6 dark:border-slate-700">
          <p className="text-sm text-slate-600 dark:text-slate-400">
            Plan transfers across several gameweeks.
          </p>
          <p className="mt-1 text-xs text-slate-500">
            At every gameweek the search compares rolling, one transfer, and two
            with a hit — then keeps the strongest paths. Rejected branches stay
            visible so you can see what was considered.
          </p>
        </div>
      )}

      {loading && (
        <p className="py-8 text-center text-sm text-slate-400">
          Running the optimiser at every branch…
        </p>
      )}

      {plan && !loading && (
        <>
          {/* ── Headline ────────────────────────────────────────────── */}
          <div className="mb-4 rounded-lg border-2 border-emerald-400 bg-emerald-50 p-3 sm:p-4 dark:border-emerald-700 dark:bg-emerald-950/40">
            <div className="flex flex-wrap items-baseline justify-between gap-3">
              <div className="min-w-0">
                <p className="text-[10px] font-bold uppercase tracking-widest text-slate-500">
                  Best path · GW{plan.horizon[0]}–{plan.horizon[plan.horizon.length - 1]}
                </p>
                <p className="mt-1 text-xl font-bold text-slate-900 sm:text-2xl dark:text-slate-50">
                  {plan.best_path.total_xpts.toFixed(1)} pts
                </p>
                <p className="text-xs text-slate-600 dark:text-slate-400">
                  {plan.best_path.total_transfers} transfer
                  {plan.best_path.total_transfers === 1 ? "" : "s"}
                  {plan.best_path.total_hits > 0
                    ? ` · −${plan.best_path.total_hits} in hits`
                    : " · no hits"}
                </p>
              </div>
              <p className="text-[11px] text-slate-500">
                {plan.optimiser_solves} optimiser solves · beam width{" "}
                {plan.beam_width}
              </p>
            </div>

            {plan.horizon_truncated && plan.truncation_note && (
              <p className="mt-3 rounded bg-amber-100 px-2 py-1 text-[11px] text-amber-900 dark:bg-amber-950/60 dark:text-amber-200">
                {plan.truncation_note}
              </p>
            )}
          </div>

          {/* ── The tree ────────────────────────────────────────────── */}
          {/* Drawn at both sizes with a media query choosing between them.
              Picking the geometry in JS needs a resize or media-query event to
              stay correct and those do not fire in every environment, so the
              tree could be left at the wrong scale; a media query cannot get it
              wrong. The duplicate costs a few dozen SVG nodes. */}
          <div className="overflow-x-auto overscroll-x-contain rounded-lg border border-slate-200 bg-white p-2 dark:border-slate-700 dark:bg-slate-900">
            <div className="sm:hidden">
              <TreeSvg
                nodes={visible}
                g={GEOMETRY.compact}
                selected={selected}
                onSelect={setSelected}
              />
            </div>
            <div className="hidden sm:block">
              <TreeSvg
                nodes={visible}
                g={GEOMETRY.wide}
                selected={selected}
                onSelect={setSelected}
              />
            </div>
          </div>

          <p className="mt-2 text-[10px] text-slate-400">
            Green is the recommended path. Dashed branches were explored and
            rejected.{" "}
            <span className="sm:hidden">
              Swipe sideways for later gameweeks, and tap
            </span>
            <span className="hidden sm:inline">Click</span> any node for detail.
          </p>

          {/* ── Selected node detail ────────────────────────────────── */}
          {selectedNode && selectedNode.depth > 0 && (
            <div className="mt-3 rounded-lg border border-slate-300 bg-slate-50 p-3 dark:border-slate-600 dark:bg-slate-800">
              <p className="text-xs font-bold text-slate-900 dark:text-slate-100">
                GW{selectedNode.gameweek} · {selectedNode.action}
                {selectedNode.pruned && (
                  <span className="ml-2 font-normal text-slate-400">
                    (rejected branch)
                  </span>
                )}
              </p>
              {selectedNode.out.length > 0 ? (
                <div className="mt-2 space-y-1">
                  {selectedNode.out.map((o, i) => (
                    <p key={o.player_id} className="text-xs">
                      <span className="font-semibold text-red-700 dark:text-red-400">
                        {o.name}
                      </span>
                      <span className="text-slate-400"> £{o.price} → </span>
                      {selectedNode.in[i] && (
                        <>
                          <span className="font-semibold text-emerald-700 dark:text-emerald-400">
                            {selectedNode.in[i].name}
                          </span>
                          <span className="text-slate-400">
                            {" "}
                            £{selectedNode.in[i].price}
                          </span>
                        </>
                      )}
                    </p>
                  ))}
                </div>
              ) : (
                <p className="mt-1 text-xs text-slate-500">
                  No transfer — the free transfer rolls over.
                </p>
              )}
              <p className="mt-2 text-[11px] text-slate-500">
                {selectedNode.gw_xpts.toFixed(1)} pts this gameweek ·{" "}
                {selectedNode.cumulative_xpts.toFixed(1)} cumulative ·{" "}
                {selectedNode.remaining_value.toFixed(1)} squad value remaining
              </p>
            </div>
          )}

          {/* ── Best path as a list ─────────────────────────────────── */}
          <div className="mt-4 overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-700">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 dark:bg-slate-800/60">
                <tr className="text-left text-[10px] uppercase tracking-wide text-slate-500">
                  <th className="px-3 py-2 font-semibold">GW</th>
                  <th className="px-2 py-2 font-semibold">Action</th>
                  <th className="px-2 py-2 font-semibold">Move</th>
                  {/* The running total is the number that decides the plan, so
                      the per-gameweek figure is the one that gives way. */}
                  <th className="hidden px-2 py-2 text-right font-semibold sm:table-cell">
                    This GW
                  </th>
                  <th className="px-2 py-2 text-right font-semibold">Running</th>
                  {/* Secondary state — dropped on phones so the transfer
                      itself keeps enough room to read. */}
                  <th className="hidden px-2 py-2 text-right font-semibold sm:table-cell">
                    FT
                  </th>
                  <th className="hidden px-2 py-2 text-right font-semibold sm:table-cell">
                    Bank
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-700">
                {plan.best_path.steps.map((s) => (
                  <tr key={s.id}>
                    <td className="px-3 py-2 font-semibold text-slate-700 dark:text-slate-300">
                      {s.gameweek}
                    </td>
                    <td className="px-2 py-2 text-xs">
                      <span
                        className={
                          s.hit > 0
                            ? "font-semibold text-amber-700 dark:text-amber-400"
                            : "text-slate-600 dark:text-slate-400"
                        }
                      >
                        {s.action}
                      </span>
                    </td>
                    <td className="px-2 py-2 text-xs text-slate-600 dark:text-slate-400">
                      {s.out.length > 0
                        ? s.out.map((o, i) => (
                            <span
                              key={o.player_id}
                              className="block whitespace-nowrap sm:mr-2 sm:inline"
                            >
                              {o.name} → {s.in[i]?.name ?? "?"}
                            </span>
                          ))
                        : "—"}
                    </td>
                    <td className="hidden px-2 py-2 text-right tabular-nums text-slate-500 sm:table-cell">
                      {s.gw_xpts.toFixed(1)}
                    </td>
                    <td className="px-2 py-2 text-right font-bold tabular-nums text-emerald-600 dark:text-emerald-400">
                      {s.cumulative_xpts.toFixed(1)}
                    </td>
                    <td className="hidden px-2 py-2 text-right tabular-nums text-slate-500 sm:table-cell">
                      {s.free_transfers}
                    </td>
                    <td className="hidden px-2 py-2 text-right tabular-nums text-slate-500 sm:table-cell">
                      £{s.bank}m
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}

/**
 * One rendering of the tree at a fixed geometry.
 *
 * `selected` is owned by the parent so the phone and desktop copies stay in
 * step: whichever one the media query is showing, tapping a node opens the same
 * detail panel.
 */
function TreeSvg({
  nodes,
  g,
  selected,
  onSelect,
}: {
  nodes: PlanNode[];
  g: Geometry;
  selected: number | null;
  onSelect: (id: number | null) => void;
}) {
  const {
    NODE_W,
    NODE_H,
    PADX,
    FONT_TITLE,
    FONT_BODY,
    FONT_META,
    SHOW_META,
    ROOT_LABEL,
  } = g;
  const { placed, width, height } = useMemo(() => layout(nodes, g), [nodes, g]);
  const byId = useMemo(() => new Map(placed.map((n) => [n.id, n])), [placed]);

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className="min-w-full"
    >
      {/* Connectors, drawn first so nodes sit on top */}
      {placed.map((n) => {
        if (n.parent_id === null) return null;
        const p = byId.get(n.parent_id);
        if (!p) return null;
        const x1 = p.x + NODE_W;
        const y1 = p.y + NODE_H / 2;
        const x2 = n.x;
        const y2 = n.y + NODE_H / 2;
        const mid = (x1 + x2) / 2;
        const best = n.on_best_path && p.on_best_path;
        return (
          <path
            key={`edge-${n.id}`}
            d={`M ${x1} ${y1} C ${mid} ${y1}, ${mid} ${y2}, ${x2} ${y2}`}
            fill="none"
            stroke={best ? "#059669" : n.pruned ? "#cbd5e1" : "#94a3b8"}
            strokeWidth={best ? 2.5 : 1.25}
            strokeDasharray={n.pruned ? "3 3" : undefined}
            opacity={n.pruned ? 0.5 : 1}
          />
        );
      })}

      {/* Gameweek column headers */}
      {[...new Set(placed.map((n) => n.depth))]
        .sort((a, b) => a - b)
        .map((depth) => {
          const any = placed.find((n) => n.depth === depth)!;
          return (
            <text
              key={`hdr-${depth}`}
              x={any.x + NODE_W / 2}
              y={10}
              textAnchor="middle"
              className="fill-slate-400"
              style={{
                fontSize: FONT_META,
                fontWeight: 700,
                letterSpacing: 0.5,
              }}
            >
              {depth === 0 ? "NOW" : `GW${any.gameweek}`}
            </text>
          );
        })}

      {/* Nodes */}
      {placed.map((n) => {
        const best = n.on_best_path;
        const isSelected = selected === n.id;
        return (
          <g
            key={n.id}
            transform={`translate(${n.x}, ${n.y})`}
            onClick={() => onSelect(isSelected ? null : n.id)}
            style={{ cursor: "pointer" }}
          >
            <rect
              width={NODE_W}
              height={NODE_H}
              rx={7}
              className={
                best
                  ? "fill-emerald-50 dark:fill-emerald-950"
                  : "fill-white dark:fill-slate-800"
              }
              stroke={
                isSelected
                  ? "#0f172a"
                  : best
                    ? "#059669"
                    : n.pruned
                      ? "#e2e8f0"
                      : "#cbd5e1"
              }
              strokeWidth={isSelected ? 2.5 : best ? 2 : 1}
              opacity={n.pruned ? 0.55 : 1}
            />
            <text
              x={PADX}
              y={19}
              className="fill-slate-900 dark:fill-slate-100"
              style={{ fontSize: FONT_TITLE, fontWeight: 700 }}
              opacity={n.pruned ? 0.6 : 1}
            >
              {n.depth === 0 ? ROOT_LABEL : n.action}
            </text>
            {n.depth > 0 && (
              <>
                <text
                  x={PADX}
                  y={36}
                  className="fill-slate-500"
                  style={{ fontSize: FONT_BODY }}
                  opacity={n.pruned ? 0.6 : 1}
                >
                  {n.gw_xpts.toFixed(1)} this GW
                </text>
                <text
                  x={PADX}
                  y={51}
                  className={
                    best
                      ? "fill-emerald-700 dark:fill-emerald-400"
                      : "fill-slate-600 dark:fill-slate-400"
                  }
                  style={{ fontSize: FONT_TITLE, fontWeight: 700 }}
                  opacity={n.pruned ? 0.6 : 1}
                >
                  {n.cumulative_xpts.toFixed(1)} total
                </text>
                {SHOW_META && (
                  <text
                    x={NODE_W - PADX}
                    y={51}
                    textAnchor="end"
                    className="fill-slate-400"
                    style={{ fontSize: FONT_META }}
                    opacity={n.pruned ? 0.6 : 1}
                  >
                    {n.free_transfers} FT · £{n.bank}m
                  </text>
                )}
              </>
            )}
            {n.pruned && (
              // On a compact node the title fills the top row, so the
              // badge drops into the slot the FT/bank line vacated.
              <text
                x={NODE_W - PADX}
                y={SHOW_META ? 19 : 51}
                textAnchor="end"
                className="fill-slate-400"
                style={{ fontSize: FONT_META - 1, fontWeight: 700 }}
              >
                REJECTED
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}
