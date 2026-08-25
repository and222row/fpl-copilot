from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.rate_limit import limiter, HEAVY
from app.services.dream_team import build_dream_team, DEFAULT_BUDGET

router = APIRouter(prefix="/dream-team", tags=["dream-team"])


def _parse_ids(raw: str | None, label: str) -> list[int]:
    if not raw:
        return []
    try:
        return [int(x.strip()) for x in raw.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(400, f"{label} must be comma-separated player IDs")


@router.get("")
@limiter.limit(HEAVY)
async def dream_team(
    request: Request,
    budget: float = Query(
        100.0, ge=50.0, le=120.0,
        description="Total spend in millions. 100.0 is the standard FPL budget.",
    ),
    horizon: int = Query(
        1, ge=1, le=8,
        description="Gameweeks to optimise over. 1 = best team for the next "
                    "gameweek; higher favours a good run of fixtures.",
    ),
    must_include: str | None = Query(
        None, description="Comma-separated player IDs to force into the squad"
    ),
    exclude: str | None = Query(
        None, description="Comma-separated player IDs to keep out"
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    The best legal 15 from the entire player pool — ignoring what you own.

    Answers "if I wildcarded right now, what would I pick?". Squad membership,
    the XI and the captaincy are solved together, because a player's value
    depends on whether he is expected to start.

    Every player comes with reasons derived from the projection model's own
    numbers: which scoring component drives his points, his rank within his
    position, the custom fixture rating, value per million, set-piece duty, and
    any rotation or price risk. No prose is generated — each claim is a figure
    you can check.
    """
    try:
        return await build_dream_team(
            db,
            budget=int(round(budget * 10)),
            horizon=horizon,
            must_include=_parse_ids(must_include, "must_include"),
            exclude=_parse_ids(exclude, "exclude"),
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
