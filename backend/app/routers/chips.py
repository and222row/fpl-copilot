from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import ManagerAccess
from app.database import get_db
from app.rate_limit import limiter, HEAVY, READ
from app.services import chips

router = APIRouter(tags=["chips"])


@router.get("/chips/{manager_id}", dependencies=[ManagerAccess])
@limiter.limit(HEAVY)
async def chip_advice(
    request: Request,
    manager_id: int,
    horizon: int = Query(5, ge=1, le=10, description="Gameweeks to look ahead"),
    db: AsyncSession = Depends(get_db),
):
    """
    When to play each chip, for this squad.

    Answers the timing question rather than the scoring one. FPL issues chips
    with an expiry, so the useful question is never "is this a good week" but
    "is this good enough, given how many chances remain before it is lost".

    The response is layered by how much each part can be trusted. Fixture shape
    and chip availability are facts and hold regardless of how good the
    projection model turns out to be. The valuations rest on that model, and the
    verdicts are a stated heuristic on top of them.
    """
    return await chips.advise(db, manager_id, horizon=horizon)


@router.get("/chips/fixtures/shape")
@limiter.limit(READ)
async def fixture_shape(
    request: Request,
    from_gameweek: int = Query(1, ge=1, le=38),
    db: AsyncSession = Depends(get_db),
):
    """
    Which gameweeks contain doubles or blanks.

    Squad-independent and model-free — just a count of fixtures per team per
    gameweek. This is the scarce information in chip timing: doubles appear
    only when postponed fixtures are rearranged, months after anyone was
    watching for them.
    """
    return await chips.fixture_shape(db, from_gameweek=from_gameweek)
