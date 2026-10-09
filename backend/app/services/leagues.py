"""
Mini-leagues: standings, what your rivals own that you don't, and head to head.

Everything here is public FPL data (anyone can open a league page on the FPL
site); nothing about other managers is stored. Rival squads are as of the
last deadline, the same limit that applies to every squad FPL publishes.
"""
import asyncio
import logging
from collections import Counter
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fpl import Fixture, Player, Team
from app.models.projections import Projection
from app.services.fpl_client import fetch_league_standings, fetch_manager_info, fetch_manager_picks
from app.services.fpl_sync import get_latest_started_gameweek, get_next_open_gameweek
from app.services.projection import MODEL_VERSION
from app.services.squad_state import resolve_squad

logger = logging.getLogger("fpl_copilot.leagues")

PAGE_SIZE = 50
# Rivals whose squads are read for league ownership. Each is one FPL request
# (cached), so the top of the table rather than all of it.
RIVALS_SAMPLED = 10
# A player at least this share of the sampled rivals own, and you don't, is a threat.
THREAT_SHARE = 0.5
# A player you own that at most this share of rivals own is a differential.
DIFFERENTIAL_SHARE = 0.2
POSITIONS = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
KIT_URL = "https://fantasy.premierleague.com/dist/img/shirts/standard/shirt_{code}{keeper}-110.png"


def kit_url(team_code: int, position: int) -> str | None:
    """FPL's own shirt image; goalkeepers wear the _1 variant."""
    if not team_code:
        return None
    return KIT_URL.format(code=team_code, keeper="_1" if position == 1 else "")


async def _fixtures(db: AsyncSession, team_ids: set[int], gameweek: int) -> dict[int, list[str]]:
    """Each club's opponents in the gameweek, as "LIV (A)"; doubles list two."""
    if not team_ids:
        return {}
    rows = (await db.execute(
        select(Fixture.team_h, Fixture.team_a).where(
            Fixture.gameweek_id == gameweek,
            or_(Fixture.team_h.in_(team_ids), Fixture.team_a.in_(team_ids)),
        ).order_by(Fixture.kickoff_time)
    )).all()
    short = dict((await db.execute(select(Team.id, Team.short_name))).all())
    out: dict[int, list[str]] = {}
    for home, away in rows:
        out.setdefault(home, []).append(f"{short.get(away, '?')} (H)")
        out.setdefault(away, []).append(f"{short.get(home, '?')} (A)")
    return out


class LeagueNotFound(Exception):
    """The manager is not in this league (or it does not exist)."""


@dataclass(frozen=True)
class Gameweeks:
    picks: int
    target: int


async def _gameweeks(db: AsyncSession) -> Gameweeks:
    started = await get_latest_started_gameweek(db)
    target = await get_next_open_gameweek(db)
    if started is None:
        raise LeagueNotFound("No gameweek has started yet, so there are no squads to compare.")
    return Gameweeks(picks=started.id, target=target.id if target else started.id)


def _league_summary(raw: dict) -> dict:
    return {
        "id": raw["id"],
        "name": raw["name"],
        # x = created by players; s = FPL's own (overall, country, club).
        "private": raw.get("league_type") == "x",
        "rank": raw.get("entry_rank") or None,
        "last_rank": raw.get("entry_last_rank") or None,
        "size": raw.get("rank_count"),
    }


async def manager_leagues(manager_id: int) -> list[dict]:
    """The manager's classic leagues: their own leagues first, then FPL's."""
    info = await fetch_manager_info(manager_id)
    leagues = [_league_summary(l) for l in (info.get("leagues") or {}).get("classic", [])]
    return sorted(leagues, key=lambda l: (not l["private"], l["size"] or 10**9))


async def _membership(manager_id: int, league_id: int) -> dict:
    for league in await manager_leagues(manager_id):
        if league["id"] == league_id:
            return league
    raise LeagueNotFound("You are not in that league.")


async def _player_rows(db: AsyncSession, ids: set[int], target_gw: int) -> dict[int, dict]:
    """Name, club, position and next-gameweek projection for the given players."""
    if not ids:
        return {}
    rows = (await db.execute(
        select(Player.id, Player.web_name, Player.position, Player.now_cost, Team.short_name, Team.code, Team.id)
        .join(Team, Team.id == Player.team_id)
        .where(Player.id.in_(ids))
    )).all()
    fixtures = await _fixtures(db, {r[6] for r in rows}, target_gw)
    xpts = dict((await db.execute(
        select(Projection.player_id, Projection.xpts).where(
            Projection.player_id.in_(ids),
            Projection.gameweek_id == target_gw,
            Projection.model_version == MODEL_VERSION,
        )
    )).all())
    return {
        pid: {
            "player_id": pid,
            "name": name,
            "team": team,
            "position": POSITIONS.get(position, "UNK"),
            "price": round(cost / 10, 1),
            "xpts": round(float(xpts.get(pid, 0.0)), 2),
            "kit": kit_url(code, position),
            "fixtures": fixtures.get(team_id, []),
        }
        for pid, name, position, cost, team, code, team_id in rows
    }


async def _standings(league_id: int, your_rank: int | None) -> tuple[dict, list[dict]]:
    """Page one, plus the page you are on when you are further down."""
    first = await fetch_league_standings(league_id, 1)
    rows = list(first["standings"]["results"])
    if your_rank and your_rank > PAGE_SIZE:
        page = (your_rank - 1) // PAGE_SIZE + 1
        mine = await fetch_league_standings(league_id, page)
        seen = {r["entry"] for r in rows}
        rows += [r for r in mine["standings"]["results"] if r["entry"] not in seen]
    return first["league"], rows


async def _picks(manager_id: int, gameweek: int) -> dict | None:
    try:
        return await fetch_manager_picks(manager_id, gameweek)
    except Exception:
        # A manager who joined after that deadline has no picks for it.
        logger.info("rival picks unavailable", extra={"gameweek": gameweek})
        return None


async def league_view(db: AsyncSession, manager_id: int, league_id: int) -> dict:
    membership = await _membership(manager_id, league_id)
    gws = await _gameweeks(db)
    league, rows = await _standings(league_id, membership["rank"])

    you = next((r for r in rows if r["entry"] == manager_id), None)
    standings = [
        {
            "rank": r["rank"],
            "last_rank": r["last_rank"],
            "entry": r["entry"],
            "team_name": r["entry_name"],
            "manager_name": r["player_name"],
            "total": r["total"],
            "gameweek_points": r["event_total"],
            "is_you": r["entry"] == manager_id,
        }
        for r in sorted(rows, key=lambda r: r["rank_sort"])
    ]

    gaps = None
    if you:
        above = [r for r in rows if r["rank_sort"] < you["rank_sort"]]
        gaps = {
            "to_leader": (rows[0]["total"] - you["total"]) if rows and rows[0]["entry"] != manager_id else 0,
            "to_next": (above[-1]["total"] - you["total"]) if above else 0,
        }

    rivals = [r["entry"] for r in sorted(rows, key=lambda r: r["rank_sort"]) if r["entry"] != manager_id][:RIVALS_SAMPLED]
    semaphore = asyncio.Semaphore(4)

    async def picks_for(entry: int):
        async with semaphore:
            return await _picks(entry, gws.picks)

    rival_picks = [p for p in await asyncio.gather(*(picks_for(e) for e in rivals)) if p]
    owned = Counter(pick["element"] for p in rival_picks for pick in p.get("picks", []))
    captained = Counter(
        pick["element"] for p in rival_picks for pick in p.get("picks", []) if pick.get("is_captain")
    )

    mine = set((await resolve_squad(db, manager_id, gws.target, gws.picks)).player_ids)
    sample = len(rival_picks)
    players = await _player_rows(db, set(owned) | mine, gws.target)

    def entry(pid: int) -> dict:
        return {
            **players.get(pid, {"player_id": pid, "name": f"#{pid}", "team": "", "position": "UNK", "price": 0, "xpts": 0}),
            "owned_by": owned.get(pid, 0),
            "captained_by": captained.get(pid, 0),
        }

    threats = sorted(
        (entry(pid) for pid, n in owned.items() if pid not in mine and sample and n / sample >= THREAT_SHARE),
        key=lambda p: (-p["owned_by"], -p["xpts"]),
    )
    differentials = sorted(
        (entry(pid) for pid in mine if not sample or owned.get(pid, 0) / sample <= DIFFERENTIAL_SHARE),
        key=lambda p: -p["xpts"],
    )
    return {
        "league": {"id": league["id"], "name": league["name"], "private": membership["private"], "size": membership["size"]},
        "your_rank": you["rank"] if you else membership["rank"],
        "gaps": gaps,
        "standings": standings,
        "rivals_sampled": sample,
        "squads_as_of_gameweek": gws.picks,
        "projections_for_gameweek": gws.target,
        "threats": threats,
        "differentials": differentials,
        "most_captained": [entry(pid) for pid, _ in captained.most_common(3)],
    }


async def rival_view(db: AsyncSession, manager_id: int, league_id: int, rival_id: int) -> dict:
    membership = await _membership(manager_id, league_id)
    if rival_id == manager_id:
        raise LeagueNotFound("Pick someone other than yourself.")
    gws = await _gameweeks(db)
    _, rows = await _standings(league_id, membership["rank"])
    row = next((r for r in rows if r["entry"] == rival_id), None)
    if row is None:
        raise LeagueNotFound("That manager is not in the part of the league table we can see.")
    you_row = next((r for r in rows if r["entry"] == manager_id), None)

    theirs = await _picks(rival_id, gws.picks)
    if theirs is None:
        raise LeagueNotFound("FPL has no squad for that manager yet.")
    their_ids = {p["element"] for p in theirs.get("picks", [])}
    their_captain = next((p["element"] for p in theirs.get("picks", []) if p.get("is_captain")), None)

    mine_squad = await resolve_squad(db, manager_id, gws.target, gws.picks)
    mine = set(mine_squad.player_ids)
    my_picks = await _picks(manager_id, gws.picks)
    my_captain = next((p["element"] for p in (my_picks or {}).get("picks", []) if p.get("is_captain")), None)

    players = await _player_rows(db, their_ids | mine, gws.target)

    def side(ids: set[int]) -> list[dict]:
        return sorted((players[i] for i in ids if i in players), key=lambda p: -p["xpts"])

    only_mine, only_theirs = side(mine - their_ids), side(their_ids - mine)

    # Their whole squad as FPL lays it out: slots 1-11 start, 12-15 are the
    # bench in order. Drawn on a pitch like the FPL app's.
    squad = [
        {
            **players[p["element"]],
            "slot": p.get("position"),
            "starting": (p.get("position") or 99) <= 11,
            "is_captain": bool(p.get("is_captain")),
            "is_vice_captain": bool(p.get("is_vice_captain")),
            "you_own": p["element"] in mine,
        }
        for p in sorted(theirs.get("picks", []), key=lambda p: p.get("position") or 99)
        if p["element"] in players
    ]
    return {
        "league_id": league_id,
        "rival": {
            "entry": rival_id,
            "team_name": row["entry_name"],
            "manager_name": row["player_name"],
            "rank": row["rank"],
            "total": row["total"],
            "gameweek_points": row["event_total"],
            "captain": players.get(their_captain, {}).get("name") if their_captain else None,
        },
        "you": {
            "rank": you_row["rank"] if you_row else membership["rank"],
            "total": you_row["total"] if you_row else None,
            "gameweek_points": you_row["event_total"] if you_row else None,
            "captain": players.get(my_captain, {}).get("name") if my_captain else None,
        },
        "points_gap": (row["total"] - you_row["total"]) if you_row else None,
        "squad": squad,
        "shared": side(mine & their_ids),
        "only_yours": only_mine,
        "only_theirs": only_theirs,
        # Who the differences favour next gameweek, by the projection.
        "edge_next_gameweek": round(sum(p["xpts"] for p in only_mine) - sum(p["xpts"] for p in only_theirs), 1),
        "squads_as_of_gameweek": gws.picks,
        "projections_for_gameweek": gws.target,
    }
