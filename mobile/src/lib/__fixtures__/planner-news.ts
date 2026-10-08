import type { AlertItem, NewsEvent, Plan, PlanPlayer, PlanStep } from '@/lib/api';

const player = (player_id: number, name: string, team: string, position: number, price_change_percent = 0): PlanPlayer => ({
  player_id, name, team, position, price: 8, price_change_percent,
});

const node = (n: Partial<PlanStep> & Pick<PlanStep, 'id' | 'parent_id' | 'gameweek' | 'depth'>): PlanStep => ({
  action: 'Roll', transfers: 0, hit: 0, in: [], out: [], bank: 0.5, free_transfers: 2,
  gw_xpts: 56, cumulative_xpts: 56, remaining_value: 110, pruned: false, on_best_path: false, ...n,
});

// GW8: sell Martinelli for Saka (Saka near a rise, but bought now at today's price).
// GW9: sell injured Wissa for Watkins, who is 72% of the way to a rise.
const gw8 = node({
  id: 1, parent_id: 0, gameweek: 8, depth: 1, action: '1 transfer', transfers: 1, on_best_path: true,
  out: [player(20, 'Martinelli', 'ARS', 3)], in: [player(21, 'Saka', 'ARS', 3, 80)],
  gw_xpts: 57.2, cumulative_xpts: 57.2, remaining_value: 112, free_transfers: 1,
});
const gw8Roll = node({ id: 2, parent_id: 0, gameweek: 8, depth: 1, cumulative_xpts: 55.2, remaining_value: 112, pruned: true });
const gw9 = node({
  id: 5, parent_id: 1, gameweek: 9, depth: 2, action: '1 transfer', transfers: 1, on_best_path: true,
  out: [player(10, 'Wissa', 'NEW', 4)], in: [player(11, 'Watkins', 'AVL', 4, 72)],
  gw_xpts: 58.0, cumulative_xpts: 115.2, remaining_value: 56.2, free_transfers: 1,
});
const gw9Roll = node({ id: 6, parent_id: 1, gameweek: 9, depth: 2, cumulative_xpts: 113.2, remaining_value: 56.2 });
const gw10 = node({
  id: 9, parent_id: 5, gameweek: 10, depth: 3, on_best_path: true,
  gw_xpts: 56.2, cumulative_xpts: 171.4, remaining_value: 0, free_transfers: 2,
});

export const plan: Plan = {
  horizon: [8, 9, 10],
  requested_horizon: 3,
  horizon_truncated: false,
  truncation_note: null,
  best_path: { total_xpts: 171.4, total_hits: 0, total_transfers: 2, steps: [gw8, gw9, gw10] },
  tree: [node({ id: 0, parent_id: null, gameweek: 8, depth: 0 }), gw8, gw8Roll, gw9, gw9Roll, gw10],
  starting_bank: 0.5,
  starting_free_transfers: 1,
  squad_source: 'fpl_api',
};

export const alerts: AlertItem[] = [
  {
    id: 1, severity: 'warning', title: 'Timber is a doubt', body: 'Knock - 75% chance of playing',
    player_id: 30, still_owned: true, read: false, created_at: new Date().toISOString(),
  },
  {
    id: 2, severity: 'info', title: 'Saka price changed', body: '', player_id: 21, still_owned: true,
    read: true, created_at: new Date().toISOString(),
  },
];

const event = (e: Partial<NewsEvent> & Pick<NewsEvent, 'id' | 'name' | 'team' | 'category'>): NewsEvent => ({
  detected_at: new Date().toISOString(), event_type: 'status_change', player_id: e.id, position: 'MID', price: 6,
  status_label: null, cause: null, expected_return: null, news: '', materiality: 0.5, direction: 'negative',
  confidence: 'high', source: 'fpl_api', source_label: 'FPL official', ...e,
});

export const events: NewsEvent[] = [
  event({ id: 10, name: 'Wissa', team: 'NEW', category: 'INJURY', news: 'Ankle injury - Expected back 30 Nov' }),
  event({ id: 12, name: 'Rice', team: 'ARS', category: 'SUSPENSION', news: 'Shrdlu etaoin', confidence: 'low' }),
  event({ id: 7, name: 'Semenyo', team: 'BOU', category: 'PRICE_CHANGE', direction: 'neutral' }),
];
