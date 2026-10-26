"""
Head-to-head leagues and the FPL cup: the table, this week's match (live while
it is played), the next one, and your results.

All public FPL data, read through the cached client and never stored. A
match's points come from FPL once the gameweek is over; while it is played,
both sides are worked out live the same way the live screen does it
(services/live.py), since FPL's own match points lag.
"""
import asyncio

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import live
from app.services.fpl_client import fetch_h2h_matches, fetch_h2h_standings, fetch_manager_info
from app.services.fpl_sync import get_latest_started_gameweek, get_next_open_gameweek
from app.services.leagues import LeagueNotFound


def match_view(m: dict, you: int) -> dict:
    """One fixture from your side: who you play, the score, and how it went."""
    first = m.get("entry_1_entry") == you
    me, them = ("entry_1", "entry_2") if first else ("entry_2", "entry_1")
    played = bool(m.get(f"{me}_win") or m.get(f"{me}_draw") or m.get(f"{me}_loss"))
    result = None
    if played:
        result = "W" if m.get(f"{me}_win") else "D" if m.get(f"{me}_draw") else "L"
    return {
        "gameweek": m.get("event"),
        "opponent": None if m.get("is_bye") else {
            "entry": m.get(f"{them}_entry"),
            "team_name": m.get(f"{them}_name"),
            "manager_name": m.get(f"{them}_player_name"),
        },
        "your_points": m.get(f"{me}_points"),
        "their_points": m.get(f"{them}_points"),
        "result": result,
        "knockout": m.get("knockout_name") or None,
    }


def _summary(league: dict) -> dict:
    return {
        "id": league["id"],
        "name": league["name"],
        "rank": league.get("entry_rank") or None,
        "last_rank": league.get("entry_last_rank") or None,
        "size": league.get("rank_count"),
    }


async def manager_h2h(manager_id: int) -> dict:
    """Your head-to-head leagues, and your cup run if it has started."""
    info = await fetch_manager_info(manager_id)
    leagues = (info.get("leagues") or {})
    cup = leagues.get("cup") or {}
    status = cup.get("status") or {}
    return {
        "leagues": [_summary(l) for l in leagues.get("h2h") or []],
        "cup": {
            "matches": sorted((match_view(m, manager_id) for m in cup.get("matches") or []), key=lambda m: m["gameweek"] or 0),
            "qualified": status.get("qualification_state"),
            "starts": status.get("qualification_event"),
        },
    }


async def _live_points(db: AsyncSession, gameweek: int, entries: list[int]) -> dict[int, int]:
    """Live gameweek points (after hits) for each entry with picks."""
    players, _ = await live._world(db, gameweek)

    async def one(entry: int):
        try:
            return entry, live.team_live(await live._picks(entry, gameweek), players).points
        except httpx.HTTPError:
            return entry, None

    return {e: p for e, p in await asyncio.gather(*(one(e) for e in entries)) if p is not None}


async def h2h_view(db: AsyncSession, manager_id: int, league_id: int) -> dict:
    mine = {l["id"]: l for l in (await manager_h2h(manager_id))["leagues"]}
    if league_id not in mine:
        raise LeagueNotFound("You are not in that head-to-head league.")
    standings, matches = await asyncio.gather(fetch_h2h_standings(league_id), fetch_h2h_matches(league_id, manager_id))

    results = [match_view(m, manager_id) for m in matches.get("results") or []]
    results.sort(key=lambda m: m["gameweek"] or 0)
    started = await get_latest_started_gameweek(db)
    upcoming = await get_next_open_gameweek(db)
    current = next((m for m in results if started and m["gameweek"] == started.id), None)
    following = next((m for m in results if upcoming and m["gameweek"] == upcoming.id), None)

    status = None
    if current and started and current["result"] is None and current["opponent"]:
        # Being played: FPL's match points lag, so both sides are worked out live.
        _, fixtures = await live._world(db, started.id)
        status = live._status(fixtures)
        points = await _live_points(db, started.id, [manager_id, current["opponent"]["entry"]])
        current = {**current, "your_points": points.get(manager_id, current["your_points"]),
                   "their_points": points.get(current["opponent"]["entry"], current["their_points"]), "live": True}

    table = [
        {
            "rank": r["rank"], "last_rank": r.get("last_rank"), "entry": r["entry"],
            "team_name": r["entry_name"], "manager_name": r["player_name"],
            "won": r.get("matches_won", 0), "drawn": r.get("matches_drawn", 0), "lost": r.get("matches_lost", 0),
            "points": r.get("total", 0), "points_for": r.get("points_for", 0),
            "is_you": r["entry"] == manager_id,
        }
        for r in sorted((standings.get("standings") or {}).get("results") or [], key=lambda r: r["rank_sort"])
    ]
    played = [m for m in results if m["result"]]
    return {
        "league": {"id": league_id, "name": (standings.get("league") or {}).get("name") or mine[league_id]["name"]},
        "current": current,
        "current_status": status,
        "next": following,
        "record": {k: sum(1 for m in played if m["result"] == k) for k in ("W", "D", "L")},
        "results": list(reversed(played)),
        "standings": table,
        "partial": bool((standings.get("standings") or {}).get("has_next")),
    }
