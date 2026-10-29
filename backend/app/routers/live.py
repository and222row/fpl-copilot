import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import ManagerAccess, Premium
from app.database import get_db
from app.rate_limit import UPSTREAM, limiter
from app.routers.leagues import _fpl_error
from app.services.leagues import LeagueNotFound
from app.services.live import LiveUnavailable, league_live, live_view

router = APIRouter(prefix="/live", tags=["live"])


@router.get("/{manager_id}", dependencies=[ManagerAccess, Premium])
@limiter.limit(UPSTREAM)
async def my_live(request: Request, manager_id: int, db: AsyncSession = Depends(get_db)):
    """
    Your points in the gameweek being played: provisional bonus, projected
    automatic substitutions and captaincy, and who is still to play.
    """
    try:
        return await live_view(db, manager_id)
    except LiveUnavailable as e:
        raise HTTPException(404, str(e))
    except httpx.HTTPError as e:
        raise _fpl_error(e)


@router.get("/{manager_id}/managers/{entry_id}", dependencies=[ManagerAccess, Premium])
@limiter.limit(UPSTREAM)
async def manager_live(request: Request, manager_id: int, entry_id: int, db: AsyncSession = Depends(get_db)):
    """
    Another manager's team in the gameweek being played, scored live: for an
    opponent in a head-to-head league or a rival in a table. FPL publishes
    every squad once the deadline has passed, so nothing private is shown.
    """
    if not 1 <= entry_id <= 100_000_000:
        raise HTTPException(422, "Not an FPL team ID")
    try:
        return await live_view(db, entry_id)
    except LiveUnavailable as e:
        raise HTTPException(404, str(e).replace("for you", "for this manager"))
    except httpx.HTTPError as e:
        raise _fpl_error(e)


@router.get("/{manager_id}/leagues/{league_id}", dependencies=[ManagerAccess, Premium])
@limiter.limit(UPSTREAM)
async def league(request: Request, manager_id: int, league_id: int, db: AsyncSession = Depends(get_db)):
    """A mini-league re-ranked by live points, with each manager's captain and players left."""
    try:
        return await league_live(db, manager_id, league_id)
    except (LeagueNotFound, LiveUnavailable) as e:
        raise HTTPException(404, str(e))
    except httpx.HTTPError as e:
        raise _fpl_error(e)
