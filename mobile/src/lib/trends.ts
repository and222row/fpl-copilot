import type { PriceMove, TrendPlayer } from '@/lib/api';
import { ordinal } from '@/lib/format';

export function likelihoodWord(likelihood: number | null): string {
  if (likelihood === null) return '';
  if (likelihood >= 5) return 'very likely';
  if (likelihood >= 4) return 'likely';
  if (likelihood >= 3) return 'possible';
  return 'unlikely';
}

/** "Rises tonight (very likely)". */
export function priceLine(m: PriceMove): string {
  const word = likelihoodWord(m.likelihood);
  return `${m.direction === 'rise' ? 'Rises' : 'Falls'} ${m.when}${word ? ` (${word})` : ''}`;
}

/** "2nd of 79 forwards". */
export function rankPhrase(p: TrendPlayer): string | null {
  if (!p.position_rank || !p.position_count) return null;
  const nouns: Record<string, string> = { GKP: 'goalkeepers', DEF: 'defenders', MID: 'midfielders', FWD: 'forwards' };
  const noun = nouns[p.position] ?? 'players';
  return `${ordinal(p.position_rank)} of ${p.position_count} ${noun}`;
}

/** "The model ranks him 2nd of 79 forwards". */
export function rankLine(p: TrendPlayer): string | null {
  const phrase = rankPhrase(p);
  return phrase ? `The model ranks him ${phrase}` : null;
}

/** Top fifth of his position over the horizon. */
export function modelRatesHim(p: TrendPlayer): boolean {
  return !!p.position_rank && !!p.position_count && p.position_rank <= Math.max(3, p.position_count / 5);
}

/** What to do about a price move, for someone who does or doesn't own the player. */
export function priceAdvice(p: TrendPlayer, owned: boolean): string | null {
  const m = p.price_move;
  if (!m || m.offset !== 0) return null;
  if (m.direction === 'fall' && owned) return 'You own him: selling before tonight saves £0.1m.';
  if (m.direction === 'rise' && !owned && modelRatesHim(p)) return 'The model rates him: buying before tonight saves £0.1m.';
  return null;
}
