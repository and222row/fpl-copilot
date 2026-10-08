import type { PlanPlayer, PlanStep } from '@/lib/api';

// FPL resets price-change progress after each change; past this a move is near.
export const PRICE_RISK_PERCENT = 50;

export interface Alternative {
  step: PlanStep;
  /** Points over the whole plan compared with the chosen step; negative is worse. */
  delta: number;
}

const value = (s: PlanStep) => s.cumulative_xpts + s.remaining_value;

/**
 * The other choices available at the same decision point as `step`: siblings
 * under the same parent, ranked the way the search ranked them.
 */
export function alternativesAt(step: PlanStep, tree: PlanStep[]): Alternative[] {
  return tree
    .filter((n) => n.parent_id === step.parent_id && n.id !== step.id)
    .map((n) => ({ step: n, delta: Math.round((value(n) - value(step)) * 10) / 10 }))
    .sort((a, b) => b.delta - a.delta);
}

/** Like-for-like pairs, since FPL transfers must keep the squad's positions. */
export function pairByPosition(outs: PlanPlayer[], ins: PlanPlayer[]): [PlanPlayer, PlanPlayer][] {
  const remaining = [...ins];
  const pairs: [PlanPlayer, PlanPlayer][] = [];
  for (const o of outs) {
    const i = remaining.findIndex((p) => p.position === o.position);
    const match = remaining.splice(i >= 0 ? i : 0, 1)[0];
    if (match) pairs.push([o, match]);
  }
  return pairs;
}

/**
 * Buys planned for a later gameweek whose price is close to rising. The plan
 * assumes today's prices, so these may cost more by the time they are made.
 */
export function priceRisks(step: PlanStep, stepIndex: number): PlanPlayer[] {
  if (stepIndex === 0) return [];
  return step.in.filter((p) => p.price_change_percent >= PRICE_RISK_PERCENT);
}
