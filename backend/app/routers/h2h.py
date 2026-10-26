import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import ManagerAccess, Premium
from app.database import get_db
from app.rate_limit import UPSTREAM, limiter
from app.routers.leagues import _fpl_error
from app.services.h2h import h2h_view, manager_h2h
from app.services.leagues import LeagueNotFound

router = APIRouter(prefix="/h2h", tags=["leagues"])


@router.get("/{manager_id}", dependencies=[ManagerAccess, Premium])
@limiter.limit(UPSTREAM)
async def h2h_leagues(request: Request, manager_id: int):
    """Your head-to-head leagues, and your FPL cup matches once the cup starts."""
    try:
        return await manager_h2h(manager_id)
    except httpx.HTTPError as e:
        raise _fpl_error(e)


@router.get("/{manager_id}/{league_id}", dependencies=[ManagerAccess, Premium])
@limiter.limit(UPSTREAM)
async def h2h_league(request: Request, manager_id: int, league_id: int, db: AsyncSession = Depends(get_db)):
    """A head-to-head league: the table, this week's match (live), the next one, and your results."""
    try:
        return await h2h_view(db, manager_id, league_id)
    except LeagueNotFound as e:
        raise HTTPException(404, str(e))
    except httpx.HTTPError as e:
        raise _fpl_error(e)
