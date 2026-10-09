import type { Position } from '@/lib/api';

/** A player as far as recording a transfer needs: id, club, position, price (£m). */
export interface Pick {
  player_id: number;
  name: string;
  team: string;
  position: Position;
  price: number;
}

export interface Move {
  out: Pick;
  in: Pick;
}

export const POSITION_NUMBER: Record<Position, number | undefined> = { GKP: 1, DEF: 2, MID: 3, FWD: 4, UNK: undefined };
export const MAX_PER_CLUB = 3;
const HIT_PER_TRANSFER = 4;

/** Bank (£m) after the moves, selling at current prices as the server assumes. */
export function bankAfter(bank: number, moves: Move[]): number {
  return Math.round((bank + moves.reduce((s, m) => s + m.out.price - m.in.price, 0)) * 10) / 10;
}

/** Points FPL deducts for transfers beyond the free ones. */
export function hitCost(moves: number, freeTransfers: number): number {
  return Math.max(0, moves - freeTransfers) * HIT_PER_TRANSFER;
}

/** The squad once the moves are made. */
export function squadAfter(squad: Pick[], moves: Move[]): Pick[] {
  const out = new Set(moves.map((m) => m.out.player_id));
  return [...squad.filter((p) => !out.has(p.player_id)), ...moves.map((m) => m.in)];
}

/**
 * Why a player cannot come in for `out`, or null if he can. Mirrors the
 * server's checks so the list never offers a move it would refuse.
 */
export function blockedReason(candidate: Pick, out: Pick, squad: Pick[], moves: Move[], bank: number): string | null {
  const after = squadAfter(squad, moves).filter((p) => p.player_id !== out.player_id);
  if (after.some((p) => p.player_id === candidate.player_id)) return 'Already in your squad';
  if (candidate.position !== out.position) return `Not a ${out.position}`;
  if (after.filter((p) => p.team === candidate.team).length >= MAX_PER_CLUB) return `Already 3 from ${candidate.team}`;
  if (candidate.price > bankAfter(bank, moves) + out.price + 1e-9) return 'Not enough in the bank';
  return null;
}
