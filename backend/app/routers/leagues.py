import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import ManagerAccess, Premium
from app.database import get_db
from app.rate_limit import UPSTREAM, limiter
from app.services.leagues import LeagueNotFound, league_view, manager_leagues, rival_view

router = APIRouter(prefix="/leagues", tags=["leagues"])


def _fpl_error(e: httpx.HTTPError) -> HTTPException:
    if isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 404:
        return HTTPException(404, "FPL could not find that league or manager.")
    return HTTPException(503, "FPL is unreachable right now. Please try again shortly.")


@router.get("/{manager_id}", dependencies=[ManagerAccess, Premium])
@limiter.limit(UPSTREAM)
async def leagues(request: Request, manager_id: int):
    """Your classic mini-leagues, your own first, with your rank in each."""
    try:
        return {"leagues": await manager_leagues(manager_id)}
    except httpx.HTTPError as e:
        raise _fpl_error(e)


@router.get("/{manager_id}/{league_id}", dependencies=[ManagerAccess, Premium])
@limiter.limit(UPSTREAM)
async def league(request: Request, manager_id: int, league_id: int, db: AsyncSession = Depends(get_db)):
    """
    A league's table with your gaps, the players the leaders own that you
    don't, and your differentials.
    """
    try:
        return await league_view(db, manager_id, league_id)
    except LeagueNotFound as e:
        raise HTTPException(404, str(e))
    except httpx.HTTPError as e:
        raise _fpl_error(e)


@router.get("/{manager_id}/{league_id}/rivals/{rival_id}", dependencies=[ManagerAccess, Premium])
@limiter.limit(UPSTREAM)
async def rival(
    request: Request, manager_id: int, league_id: int, rival_id: int, db: AsyncSession = Depends(get_db)
):
    """Head to head with one rival: shared players, the differences, and who they favour."""
    try:
        return await rival_view(db, manager_id, league_id, rival_id)
    except LeagueNotFound as e:
        raise HTTPException(404, str(e))
    except httpx.HTTPError as e:
        raise _fpl_error(e)
