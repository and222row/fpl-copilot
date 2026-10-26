import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import ManagerAccess, Premium
from app.database import get_db
from app.rate_limit import UPSTREAM, limiter
from app.routers.leagues import _fpl_error
from app.services.review import ReviewUnavailable, review

router = APIRouter(prefix="/review", tags=["review"])


@router.get("/{manager_id}", dependencies=[ManagerAccess, Premium])
@limiter.limit(UPSTREAM)
async def gameweek_review(
    request: Request,
    manager_id: int,
    gameweek: int | None = Query(None, ge=1, le=38, description="Defaults to the latest finished gameweek"),
    db: AsyncSession = Depends(get_db),
):
    """
    How a finished gameweek went: points, ranks, best and worst picks, the
    captain, the bench, how the advice did, your leagues and the season so far.
    """
    try:
        return await review(db, manager_id, gameweek)
    except ReviewUnavailable as e:
        raise HTTPException(404, str(e))
    except httpx.HTTPError as e:
        raise _fpl_error(e)
