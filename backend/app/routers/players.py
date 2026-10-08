"""
Player explorer and player detail for the app.

The FPL-data routes under /fpl stay free; these add the model's projections
and so are premium.
"""
import logging
import unicodedata

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import Premium
from app.database import get_db
from app.models.fpl import Player, Team
from app.models.news import AvailabilityEvent
from app.models.projections import Projection
from app.rate_limit import READ, UPSTREAM, limiter
from app.services.fpl_client import fetch_player_detail_cached
from app.services.fpl_sync import get_next_open_gameweek
from app.services.player_view import POSITION_NAMES, STATUS_NAMES, player_photo, player_summary
from app.services.projection import MODEL_VERSION

logger = logging.getLogger("fpl_copilot.players")

router = APIRouter(prefix="/players", tags=["players"])

AVAILABILITY = {"fit": ("a",), "doubtful": ("d",), "out": ("i", "s", "u", "n")}
DETAIL_HORIZON = 5
RECENT_MATCHES = 5
RECENT_EVENTS = 5

# Letters NFKD does not decompose into a base letter plus an accent.
_FOLD = str.maketrans({"ø": "o", "æ": "ae", "œ": "oe", "ß": "ss", "đ": "d", "ł": "l", "ı": "i"})


def fold(text: str) -> str:
    """Lower-case, accent-free form so "odegaard" finds "Ødegaard"."""
    decomposed = unicodedata.normalize("NFKD", text.casefold().translate(_FOLD))
    return "".join(c for c in decomposed if not unicodedata.combining(c))


async def _open_gameweek_id(db: AsyncSession) -> int:
    gw = await get_next_open_gameweek(db)
    if gw is None:
        raise HTTPException(400, "No gameweek found — sync FPL data first.")
    return gw.id


@router.get("", dependencies=[Premium])
@limiter.limit(READ)
async def explore_players(
    request: Request,
    q: str | None = Query(None, min_length=1, max_length=40, description="Name search"),
    position: int | None = Query(None, ge=1, le=4),
    team_id: int | None = Query(None, ge=1, le=100),
    min_price: float | None = Query(None, ge=0, le=20),
    max_price: float | None = Query(None, ge=0, le=20),
    max_fdr: float | None = Query(None, ge=1, le=5, description="Hardest fixture allowed"),
    min_p_start: float | None = Query(None, ge=0, le=1, description="Minimum start probability"),
    max_ownership: float | None = Query(None, ge=0, le=100, description="Differentials"),
    availability: str | None = Query(None, pattern="^(fit|doubtful|out)$"),
    sort: str = Query(
        "xpts", pattern="^(xpts|value|form|price|ownership|total_points|p_start)$"
    ),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    offset: int = Query(0, ge=0, le=2000),
    limit: int = Query(30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """
    Search, filter and sort every player, with next-gameweek projections.

    Players with no projection (for instance not yet modelled) still appear;
    they sort last on projection-based orders.
    """
    gw_id = await _open_gameweek_id(db)

    stmt = (
        select(Player, Team.short_name, Projection)
        .join(Team, Team.id == Player.team_id)
        .outerjoin(
            Projection,
            (Projection.player_id == Player.id)
            & (Projection.gameweek_id == gw_id)
            & (Projection.model_version == MODEL_VERSION),
        )
    )
    if position:
        stmt = stmt.where(Player.position == position)
    if team_id:
        stmt = stmt.where(Player.team_id == team_id)
    if min_price is not None:
        stmt = stmt.where(Player.now_cost >= int(round(min_price * 10)))
    if max_price is not None:
        stmt = stmt.where(Player.now_cost <= int(round(max_price * 10)))
    if max_fdr is not None:
        stmt = stmt.where(Projection.custom_fdr <= max_fdr)
    if min_p_start is not None:
        stmt = stmt.where(Projection.p_start >= min_p_start)
    if max_ownership is not None:
        stmt = stmt.where(Player.selected_by_percent <= max_ownership)
    if availability:
        stmt = stmt.where(Player.status.in_(AVAILABILITY[availability]))

    sort_col = {
        "xpts": Projection.xpts,
        "value": Projection.xpts / func.nullif(Player.now_cost, 0),
        "form": Player.form,
        "price": Player.now_cost,
        "ownership": Player.selected_by_percent,
        "total_points": Player.total_points,
        "p_start": Projection.p_start,
    }[sort]
    direction = sort_col.desc() if order == "desc" else sort_col.asc()
    # Player.id breaks ties so pages never overlap or skip a player.
    stmt = stmt.order_by(direction.nulls_last(), Player.id)

    needle = fold(q.strip()) if q else ""
    if needle:
        # Name matching runs in Python so accents and letters like Ø fold
        # consistently on every database; the pool is only ~700 players.
        rows = [
            r for r in (await db.execute(stmt)).all()
            if needle in fold(r[0].web_name) or needle in fold(f"{r[0].first_name} {r[0].second_name}")
        ]
        total = len(rows)
        rows = rows[offset:offset + limit]
    else:
        total = await db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
        rows = (await db.execute(stmt.offset(offset).limit(limit))).all()

    return {
        "gameweek": gw_id,
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": [_explorer_row(p, short, proj) for p, short, proj in rows],
    }


def _explorer_row(p: Player, team_short: str, proj: Projection | None) -> dict:
    return {
        "player_id": p.id,
        "name": p.web_name,
        "photo": player_photo(p.code),
        "team": team_short,
        "team_id": p.team_id,
        "position": POSITION_NAMES.get(p.position, "UNK"),
        "price": round(p.now_cost / 10, 1),
        "status": p.status,
        "chance": p.chance_of_playing_this_round,
        "news": p.news,
        "form": p.form,
        "total_points": p.total_points,
        "selected_by_percent": p.selected_by_percent,
        "xpts": round(proj.xpts, 2) if proj else None,
        "expected_minutes": round(proj.expected_minutes, 1) if proj else None,
        "p_start": round(proj.p_start, 3) if proj else None,
        "fdr": proj.custom_fdr if proj else None,
    }


@router.get("/{player_id}", dependencies=[Premium])
@limiter.limit(UPSTREAM)
async def player_detail(
    request: Request,
    player_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Everything the player screen shows, in one round trip: profile, the next
    five gameweeks' projections with fixtures, recent matches and the
    availability news behind his status, each item with its source.
    """
    row = (await db.execute(
        select(Player, Team.name, Team.short_name)
        .join(Team, Team.id == Player.team_id)
        .where(Player.id == player_id)
    )).one_or_none()
    if row is None:
        raise HTTPException(404, f"Player {player_id} not found")
    p, team_name, team_short = row

    gw_id = await _open_gameweek_id(db)
    teams = dict((await db.execute(select(Team.id, Team.short_name))).all())

    projections = (await db.execute(
        select(Projection)
        .where(
            Projection.player_id == player_id,
            Projection.model_version == MODEL_VERSION,
            Projection.gameweek_id >= gw_id,
        )
        .order_by(Projection.gameweek_id)
        .limit(DETAIL_HORIZON)
    )).scalars().all()

    events = (await db.execute(
        select(AvailabilityEvent)
        .where(AvailabilityEvent.player_id == player_id)
        .order_by(AvailabilityEvent.detected_at.desc())
        .limit(RECENT_EVENTS)
    )).scalars().all()

    return {
        **player_summary(p, team_short),
        "team_full": team_name,
        "chance_next": p.chance_of_playing_next_round,
        "starts": p.starts,
        "goals": p.goals_scored,
        "assists": p.assists,
        "clean_sheets": p.clean_sheets,
        "bonus": p.bonus,
        "expected_goals": p.expected_goals,
        "expected_assists": p.expected_assists,
        "price_change": {
            "percent_to_threshold": p.price_change_percent,
            "net_transfers_gw": p.net_transfers,
        },
        "projection": {
            "total_xpts": round(sum(r.xpts for r in projections), 2),
            "gameweeks": [
                {
                    "gameweek": r.gameweek_id,
                    "xpts": round(r.xpts, 2),
                    "expected_minutes": round(r.expected_minutes, 1),
                    "p_start": round(r.p_start, 3),
                    "fdr": r.custom_fdr,
                    "fixtures": [
                        {
                            "opponent": teams.get(o.get("opponent")),
                            "is_home": o.get("is_home"),
                            "fdr": o.get("fdr"),
                        }
                        for o in (r.opponents or [])
                    ],
                }
                for r in projections
            ],
        },
        "recent": await _recent_matches(player_id, teams),
        "news": [
            {
                "detected_at": e.detected_at,
                "event_type": e.event_type,
                "status": STATUS_NAMES.get(e.status_after or "", e.status_after),
                "availability": e.availability_after,
                "cause": e.cause,
                "expected_return": e.expected_return,
                "text": e.news_text,
                "source": e.source,
            }
            for e in events
        ],
    }


async def _recent_matches(player_id: int, teams: dict[int, str]) -> list[dict] | None:
    """Last few matches from FPL, or None if FPL is unreachable right now."""
    try:
        summary = await fetch_player_detail_cached(player_id)
    except httpx.HTTPError:
        logger.warning("element-summary unavailable", extra={"player_id": player_id})
        return None
    history = summary.get("history") or []
    return [
        {
            "gameweek": h.get("round"),
            "opponent": teams.get(h.get("opponent_team")),
            "is_home": h.get("was_home"),
            "minutes": h.get("minutes"),
            "points": h.get("total_points"),
            "goals": h.get("goals_scored"),
            "assists": h.get("assists"),
            "bonus": h.get("bonus"),
        }
        for h in history[-RECENT_MATCHES:][::-1]
    ]
