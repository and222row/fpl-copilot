import httpx
from fastapi import APIRouter, Depends, HTTPException, Path, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.rate_limit import HEAVY, limiter
from app.services.advice import AdviceError
from app.services.preview import preview

router = APIRouter(prefix="/preview", tags=["preview"])


@router.get("/{team_id}")
@limiter.limit(HEAVY)
async def team_preview(
    request: Request,
    team_id: int = Path(ge=1, le=100_000_000),
    db: AsyncSession = Depends(get_db),
):
    """
    Public, no sign-in: a team's public FPL details and a teaser of the advice
    (the gain, not the players). Rate-limited per IP and cached per team.
    """
    try:
        return await preview(db, team_id)
    except AdviceError as e:
        raise HTTPException(e.status, e.message)
    except httpx.HTTPStatusError as e:
        if e.response is not None and e.response.status_code == 404:
            raise HTTPException(404, "No FPL team has that ID.")
        raise HTTPException(503, "FPL is unreachable right now. Please try again shortly.")
    except httpx.HTTPError:
        raise HTTPException(503, "FPL is unreachable right now. Please try again shortly.")
