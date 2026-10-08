from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.auth import ManagerAccess
from app.database import get_db
from app.rate_limit import limiter, HEAVY, UPSTREAM
from app.models.fpl import Gameweek
from app.models.feedback import RecommendationSnapshot
from app.services.feedback import (
    score_gameweek, accuracy_summary, outcome_history,
)

router = APIRouter(prefix="/feedback", tags=["feedback"])


@router.get("/{manager_id}/accuracy", dependencies=[ManagerAccess])
async def get_accuracy(manager_id: int, db: AsyncSession = Depends(get_db)):
    """
    Running accuracy across every scored gameweek, per decision category.

    The retention feature from the blueprint: it makes the model's track
    record visible instead of asking the user to take it on trust.
    """
    return await accuracy_summary(db, manager_id)


@router.get("/{manager_id}/history", dependencies=[ManagerAccess])
async def get_history(
    manager_id: int,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Per-gameweek outcomes, newest first."""
    return await outcome_history(db, manager_id, limit=limit)


@router.get("/{manager_id}/pending", dependencies=[ManagerAccess])
async def get_pending(manager_id: int, db: AsyncSession = Depends(get_db)):
    """
    Recommendations saved but not yet scored.

    Useful for knowing what will be gradeable once a gameweek finishes, and
    for confirming advice is actually being recorded.
    """
    from app.models.feedback import RecommendationOutcome

    scored_ids = set((await db.execute(
        select(RecommendationOutcome.snapshot_id).where(
            RecommendationOutcome.fpl_entry_id == manager_id
        )
    )).scalars().all())

    snaps = (await db.execute(
        select(RecommendationSnapshot)
        .where(RecommendationSnapshot.fpl_entry_id == manager_id)
        .order_by(RecommendationSnapshot.gameweek_id.desc())
    )).scalars().all()

    gameweeks = {
        g.id: g for g in (await db.execute(select(Gameweek))).scalars().all()
    }

    pending = []
    for s in snaps:
        if s.id in scored_ids:
            continue
        gw = gameweeks.get(s.gameweek_id)
        pending.append({
            "snapshot_id": s.id,
            "gameweek": s.gameweek_id,
            "kind": s.kind,
            "predicted_value": s.predicted_value,
            "confidence": s.confidence,
            "model_version": s.model_version,
            "created_at": s.created_at,
            "gameweek_finished": bool(gw and gw.finished),
            "scoreable": bool(gw and gw.finished),
        })

    return {
        "manager_id": manager_id,
        "pending": pending,
        "count": len(pending),
    }


@router.post("/{manager_id}/score", dependencies=[ManagerAccess])
@limiter.limit(UPSTREAM)
async def score(
    request: Request,
    manager_id: int,
    gameweek: int = Query(..., description="The gameweek to score"),
    force: bool = Query(
        False,
        description="Score on provisional results, and re-score anything "
                    "already graded. FPL's `finished` flag lags by days.",
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Grade the recommendations saved for a finished gameweek.

    Needs actual results in `player_gameweek_stats` — run
    POST /api/v1/projections/backtest/ingest-history first.
    """
    result = await score_gameweek(db, manager_id, gameweek, force=force)
    if result.get("error") and result.get("scored", 0) == 0:
        raise HTTPException(400, result["error"])
    return result


@router.post("/{manager_id}/score-all", dependencies=[ManagerAccess])
@limiter.limit(HEAVY)
async def score_all(
    request: Request,
    manager_id: int,
    force: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    """
    Score every gameweek that has recommendations awaiting a grade.

    Skips gameweeks with nothing saved rather than failing, so it is safe to
    call on a schedule.
    """
    gw_ids = (await db.execute(
        select(RecommendationSnapshot.gameweek_id)
        .where(RecommendationSnapshot.fpl_entry_id == manager_id)
        .distinct()
        .order_by(RecommendationSnapshot.gameweek_id)
    )).scalars().all()

    if not gw_ids:
        return {
            "manager_id": manager_id,
            "scored_gameweeks": [],
            "note": "No recommendations saved yet.",
        }

    scored, skipped = [], []
    for gw_id in gw_ids:
        result = await score_gameweek(db, manager_id, gw_id, force=force)
        if result.get("scored", 0) > 0:
            scored.append({"gameweek": gw_id, "count": result["scored"]})
        else:
            skipped.append({"gameweek": gw_id, "reason": result.get("error", "already scored")})

    return {
        "manager_id": manager_id,
        "scored_gameweeks": scored,
        "skipped": skipped,
    }
