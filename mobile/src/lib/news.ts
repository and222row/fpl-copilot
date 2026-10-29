import type { SquadIssue } from '@/lib/api';

/** A squad warning's headline, the way a news site would put it. */
export function warningHeadline(p: SquadIssue): string {
  switch (p.status) {
    case 'i':
      return `${p.name} is injured`;
    case 'd':
      return `${p.name} is a doubt`;
    case 's':
      return `${p.name} is suspended`;
    case 'u':
    case 'n':
      return `${p.name} is unavailable`;
    default:
      return `${p.name} may not start`;
  }
}

/** FPL's news line, or for a rotation risk the chance he starts. */
export function warningSummary(p: SquadIssue): string {
  if (p.news) return p.news;
  return `Projected to start ${Math.round(p.p_start * 100)}% of the time.`;
}

/** "GF" for a fallback when there is no photo. */
export function initials(name: string): string {
  const words = name.replace(/[^\p{L}\s.-]/gu, '').split(/[\s.-]+/).filter(Boolean);
  return (words.length > 1 ? words[0][0] + words[words.length - 1][0] : (words[0] ?? '?').slice(0, 2)).toUpperCase();
}
