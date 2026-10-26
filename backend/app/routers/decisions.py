import logging
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.auth import ManagerAccess, Premium
from app.database import get_db
from app.rate_limit import limiter, HEAVY, UPSTREAM
from app.services import advice
from app.services.advice import AdviceError
from app.services.lineup import best_starting_xi, pick_captain_and_vice, captain_candidates
from app.services.confidence import compute_confidence

router = APIRouter(prefix="/decisions", tags=["decisions"])
logger = logging.getLogger("fpl_copilot.decisions")


async def _squad(db: AsyncSession, manager_id: int, gameweek: int | None):
    gw = await advice.target_gameweek(db, gameweek)
    squad, meta = await advice.load_squad(db, manager_id, gw.id, await advice.picks_gameweek(db))
    return gw, squad, meta


# ── Lineup ────────────────────────────────────────────────────────────────────

@router.get("/{manager_id}/lineup", dependencies=[ManagerAccess, Premium])
@limiter.limit(UPSTREAM)
async def recommend_lineup(
    request: Request,
    manager_id: int,
    gameweek: int | None = Query(None),
    captain_mode: str = Query("balanced", pattern="^(safe|balanced|differential)$"),
    db: AsyncSession = Depends(get_db),
):
    """Optimal starting XI, bench order, captain and vice."""
    try:
        _, squad, meta = await _squad(db, manager_id, gameweek)
    except AdviceError as e:
        raise HTTPException(e.status, e.message)

    try:
        lineup = best_starting_xi(squad)
    except ValueError as e:
        raise HTTPException(422, str(e))

    captain, vice, ranked = pick_captain_and_vice(lineup.starting, mode=captain_mode)

    return {
        **meta,
        "formation": lineup.formation,
        "formations_considered": lineup.considered,
        "starting_xpts": lineup.starting_xpts,
        "bench_xpts": lineup.bench_xpts,
        "projected_total": round(
            lineup.starting_xpts + (captain.xpts if captain else 0.0), 2
        ),
        "captain": captain.brief() if captain else None,
        "vice_captain": vice.brief() if vice else None,
        "captain_ranking": ranked,
        "starting": [e.brief() for e in lineup.starting],
        "bench": [
            {**e.brief(), "bench_order": i}
            for i, e in enumerate(lineup.bench)
        ],
    }


# ── Captain ───────────────────────────────────────────────────────────────────

@router.get("/{manager_id}/captain", dependencies=[ManagerAccess, Premium])
@limiter.limit(UPSTREAM)
async def recommend_captain(
    request: Request,
    manager_id: int,
    gameweek: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Captain ranking under all three risk modes, side by side."""
    try:
        _, squad, meta = await _squad(db, manager_id, gameweek)
    except AdviceError as e:
        raise HTTPException(e.status, e.message)
    lineup = best_starting_xi(squad)
    matches = await advice.matches_played(db)

    modes = {}
    for mode in ("safe", "balanced", "differential"):
        ranked = captain_candidates(lineup.starting, mode=mode, top_n=5)
        top = ranked[0] if ranked else None
        runner_up = ranked[1] if len(ranked) > 1 else None

        conf = None
        if top:
            entry = next(e for e in lineup.starting if e.player.id == top["player_id"])
            conf = compute_confidence(
                data_updated_at=entry.projection.updated_at if entry.projection else None,
                p_start_in=entry.p_start,
                variance=entry.variance,
                expected_gain=top["expected_captain_points"],
                next_best_gain=runner_up["expected_captain_points"] if runner_up else None,
                matches_played=matches,
            ).as_dict()

        modes[mode] = {"ranking": ranked, "confidence": conf}

    return {**meta, "modes": modes}


# ── Transfers ─────────────────────────────────────────────────────────────────

@router.get("/{manager_id}/transfers", dependencies=[ManagerAccess, Premium])
@limiter.limit(HEAVY)
async def recommend_transfers(
    request: Request,
    manager_id: int,
    gameweek: int | None = Query(None),
    horizon: int = Query(5, ge=1, le=10, description="Gameweeks to optimise over"),
    max_transfers: int = Query(2, ge=1, le=3),
    pool_size: int = Query(140, ge=40, le=400, description="Candidates per position"),
    db: AsyncSession = Depends(get_db),
):
    """
    Best transfer options over a horizon, compared against rolling.

    The points hit is inside the objective, so a -4 is only suggested when it
    pays for itself across the horizon.
    """
    try:
        gw, squad, meta = await _squad(db, manager_id, gameweek)
        return await advice.transfer_advice(
            db, gw, squad, meta, horizon=horizon, max_transfers=max_transfers, pool_size=pool_size,
        )
    except AdviceError as e:
        raise HTTPException(e.status, e.message)


# ── Everything, in one call ───────────────────────────────────────────────────

@router.get("/{manager_id}", dependencies=[ManagerAccess, Premium])
@limiter.limit(HEAVY)
async def full_recommendation(
    request: Request,
    manager_id: int,
    gameweek: int | None = Query(None),
    horizon: int = Query(5, ge=1, le=10),
    captain_mode: str = Query("balanced", pattern="^(safe|balanced|differential)$"),
    db: AsyncSession = Depends(get_db),
):
    """
    The dashboard's primary call: lineup, captain, squad issues and the
    recommended transfer, in one response. The default request is usually
    answered from advice worked out ahead by the refresh job.
    """
    try:
        gw = await advice.target_gameweek(db, gameweek)
        if gameweek is None and horizon == advice.DEFAULT_HORIZON and captain_mode == advice.DEFAULT_CAPTAIN_MODE:
            return await advice.default_advice(db, manager_id, gw)
        return await advice.full_advice(db, manager_id, gw, horizon=horizon, captain_mode=captain_mode)
    except AdviceError as e:
        raise HTTPException(e.status, e.message)
