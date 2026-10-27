"""
The guest preview: what the app would say about a team, before signing up.

Anyone can type a Team ID, so this shows only what FPL itself makes public
(the team, its rank, its squad and FPL's own injury news) plus a teaser of
the advice: how much the recommended transfers gain and what the best XI
projects, with the players named only after signing up. It reads FPL's
public squad, never transfers an owner recorded, records nothing for the
track record, and is cached per team for half an hour, so typing the same ID
again costs nothing. The route is rate-limited per IP like the optimiser.
"""
import time
from collections import deque

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import advice, cache
from app.services.cache import cached_json
from app.services.fpl_client import fetch_manager_info

PREVIEW_TTL_SECONDS = 1800

# The route is open to anyone, and every team not already cached costs an FPL
# request plus an optimiser solve. The per-IP limit does not stop many IPs or
# many IDs, so uncached builds also share one budget across all callers, and a
# team FPL says does not exist is remembered so probing IDs costs one lookup.
MAX_BUILDS_PER_MINUTE = 20
MISSING_TTL_SECONDS = 600
MAX_MISSING_REMEMBERED = 5000

_builds: deque[float] = deque()
_missing: dict[int, float] = {}


def _reset_guards() -> None:
    _builds.clear()
    _missing.clear()


def _spend_build() -> None:
    now = time.monotonic()
    while _builds and now - _builds[0] > 60:
        _builds.popleft()
    if len(_builds) >= MAX_BUILDS_PER_MINUTE:
        raise advice.AdviceError(503, "Lots of people are checking teams right now. Please try again in a minute.")
    _builds.append(now)


def _known_missing(team_id: int) -> bool:
    until = _missing.get(team_id)
    if until is None:
        return False
    if until < time.monotonic():
        del _missing[team_id]
        return False
    return True


async def preview(db: AsyncSession, team_id: int) -> dict:
    gw = await advice.target_gameweek(db, None)

    async def build() -> dict:
        if _known_missing(team_id):
            raise advice.AdviceError(404, "No FPL team has that ID.")
        _spend_build()
        try:
            info = await fetch_manager_info(team_id)  # a 404 here means no such team
        except httpx.HTTPStatusError as e:
            if e.response is not None and e.response.status_code == 404:
                if len(_missing) >= MAX_MISSING_REMEMBERED:
                    _missing.clear()
                _missing[team_id] = time.monotonic() + MISSING_TTL_SECONDS
            raise
        body = await advice.full_advice(db, team_id, gw, record=False, use_override=False)
        t = body["transfer"]
        plan = t.get("plan") or {}
        squad = [*body["lineup"]["starting"], *body["lineup"]["bench"]]
        return {
            "team": {
                "id": team_id,
                "name": info.get("name") or "",
                "manager": " ".join(s for s in (info.get("player_first_name"), info.get("player_last_name")) if s),
                "overall_rank": info.get("summary_overall_rank"),
                "total_points": info.get("summary_overall_points"),
                "last_gameweek_points": info.get("summary_event_points"),
            },
            "gameweek": {"id": gw.id, "name": gw.name, "deadline_time": gw.deadline_time.isoformat() if gw.deadline_time else None},
            # FPL's own public data: who is in the squad and who is flagged.
            "squad": [{"name": p["name"], "team": p["team"], "position": p["position"]} for p in squad],
            "flagged": [{"name": p["name"], "reason": p["reason"], "news": p.get("news")} for p in body["squad_issues"]],
            # The advice, without the names: what signing up unlocks.
            "teaser": {
                "transfers": plan.get("transfers", 0),
                "gain": t.get("expected_net_gain", 0.0),
                "horizon": t.get("horizon_gameweeks"),
                "hit": t.get("hit_taken", 0),
                "projected": body["lineup"]["projected_total"],
                "formation": body["lineup"]["formation"],
            },
        }

    return await cached_json(cache.key_preview(team_id, gw.id), build, ttl_seconds=PREVIEW_TTL_SECONDS)
