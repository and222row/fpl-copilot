import type { PlayerBrief, PlayerDetail, Position, Recommendation, TransferMove } from '@/lib/api';

let nextId = 1;
const brief = (name: string, position: Position, extra: Partial<PlayerBrief> = {}): PlayerBrief => ({
  player_id: nextId++,
  name,
  team: 'ARS',
  position,
  price: 6,
  xpts: 4,
  p_start: 0.9,
  status: 'a',
  ...extra,
});

const xi = [
  brief('Raya', 'GKP'),
  brief('Saliba', 'DEF'),
  brief('Gabriel', 'DEF'),
  brief('Timber', 'DEF', { status: 'd', p_start: 0.6 }),
  brief('Saka', 'MID', { xpts: 7.1 }),
  brief('Palmer', 'MID', { team: 'CHE', xpts: 6.4 }),
  brief('Rice', 'MID'),
  brief('Mbeumo', 'MID'),
  brief('Haaland', 'FWD', { team: 'MCI', xpts: 8.2, price: 14.5 }),
  brief('Isak', 'FWD', { team: 'LIV' }),
  brief('Wissa', 'FWD', { team: 'NEW', status: 'i', p_start: 0.05, xpts: 0.3 }),
];
const bench = [brief('Kelleher', 'GKP'), brief('Gvardiol', 'DEF'), brief('Semenyo', 'MID'), brief('Wood', 'FWD')].map(
  (p, i) => ({ ...p, bench_order: i }),
);

const asMove = (p: PlayerBrief, horizon_xpts: number): TransferMove => ({
  player_id: p.player_id,
  name: p.name,
  team: p.team,
  position: p.position,
  price: p.price,
  horizon_xpts,
  status: p.status,
});

export const wissa = xi[10];
export const timber = xi[3];
export const haaland = xi[8];
export const watkins = brief('Watkins', 'FWD', { team: 'AVL', price: 8.9 });

const move = {
  out: asMove(wissa, 2.1),
  in: asMove(watkins, 28.4),
  xpts_gain: 26.3,
  reasons: ['Wissa is injured: Ankle injury - Expected back 30 Nov', 'Easier fixtures: average difficulty 2.4 vs 3.6 (1 is easiest)'],
};

export const recommendation: Recommendation = {
  manager_id: 1234,
  bank: 15,
  free_transfers: 1,
  squad_source: 'fpl_api',
  transfers_applied: null,
  stale_warning: null,
  gameweek: { id: 8, name: 'Gameweek 8', deadline_time: '2026-10-17T17:30:00Z', deadline_passed: false },
  lineup: {
    formation: '3-4-3',
    starting_xpts: 52.3,
    bench_xpts: 9.1,
    projected_total: 60.5,
    starting: xi,
    bench,
  },
  captain: { pick: haaland, vice: xi[4], ranking: [] },
  squad_issues: [
    { ...timber, news: 'Knock - 75% chance of playing', chance_of_playing: 75, reason: 'Doubtful' },
    { ...wissa, news: 'Ankle injury - Expected back 30 Nov', chance_of_playing: 0, reason: 'Unavailable' },
  ],
  transfer: {
    action: 'TRANSFER',
    horizon_gameweeks: 5,
    expected_net_gain: 26.3,
    hit_taken: 0,
    confidence: 84,
    notes: [],
    plan: {
      transfers: 1,
      hit: 0,
      out: [move.out],
      in: [move.in],
      squad_xpts_before: 240,
      squad_xpts_after: 266.3,
      net_gain: 26.3,
      bank_after: 0,
      note: '',
      moves: [move],
    },
  },
  transfer_alternatives: [
    {
      transfers: 0, hit: 0, out: [], in: [], squad_xpts_before: 240, squad_xpts_after: 240,
      net_gain: 0, bank_after: 15, note: 'Roll the transfer', moves: [],
    },
  ],
};

export const watkinsDetail: PlayerDetail = {
  id: watkins.player_id,
  name: 'Watkins',
  full_name: 'Ollie Watkins',
  photo: null,
  team: 'AVL',
  team_full: 'Aston Villa',
  position: 'FWD',
  price: 8.9,
  status: 'a',
  status_label: 'Available',
  news: '',
  chance_this: null,
  form: 6.2,
  total_points: 48,
  selected_by_percent: 21.4,
  minutes: 630,
  starts: 7,
  goals: 5,
  assists: 2,
  clean_sheets: 0,
  bonus: 6,
  expected_goals: 4.8,
  expected_assists: 1.3,
  price_change: { percent_to_threshold: 64, net_transfers_gw: 120000 },
  projection: {
    total_xpts: 28.4,
    gameweeks: [
      { gameweek: 8, xpts: 6.1, expected_minutes: 84, p_start: 0.93, fdr: 2.2, fixtures: [{ opponent: 'BUR', is_home: true, fdr: 2.2 }] },
      { gameweek: 9, xpts: 5.2, expected_minutes: 84, p_start: 0.93, fdr: 3.9, fixtures: [{ opponent: 'LIV', is_home: false, fdr: 3.9 }] },
    ],
  },
  recent: null,
  availability_news: [],
};
