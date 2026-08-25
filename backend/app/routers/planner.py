from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.rate_limit import limiter, HEAVY
from app.models.fpl import Gameweek
from app.services.fpl_sync import (
    get_active_gameweek, get_next_open_gameweek, get_latest_started_gameweek,
)
from app.services.squad_state import resolve_squad
from app.services.planner import plan_horizon, serialise, MAX_FREE_TRANSFERS

router = APIRouter(prefix="/planner", tags=["planner"])


@router.get("/{manager_id}")
@limiter.limit(HEAVY)
async def build_plan(
    request: Request,
    manager_id: int,
    horizon: int = Query(5, ge=2, le=8, description="Gameweeks to plan across"),
    beam_width: int = Query(
        4, ge=1, le=6,
        description="Paths kept at each gameweek. Higher explores more but is "
                    "markedly slower — every branch runs the optimiser.",
    ),
    max_transfers_per_gw: int = Query(2, ge=1, le=2),
    pool_per_position: int = Query(
        30, ge=10, le=80,
        description="Replacement candidates considered per position",
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Multi-gameweek transfer plan as a branching decision tree.

    At every gameweek the search branches on roll / one transfer / two with a
    hit, solves which players to move, and keeps the best `beam_width` states.
    The response carries the whole tree — pruned branches included — so the
    rejected alternatives stay visible rather than being asserted away.

    This is the heaviest endpoint in the API: expect several seconds.
    """
    gw = await get_active_gameweek(db)
    if not gw:
        raise HTTPException(400, "No gameweek found — sync FPL data first.")

    # Picks only exist for gameweeks that have started.
    started = await get_latest_started_gameweek(db)
    if started is None:
        raise HTTPException(
            400,
            "No gameweek has started yet, so there is no squad to plan from.",
        )
    picks_gw = started.id
    # Plan from the squad the manager actually holds, not the one locked at the
    # last deadline — otherwise the plan re-suggests transfers already made.
    open_gw = await get_next_open_gameweek(db)
    target_gw = open_gw.id if open_gw else gw.id

    try:
        resolved = await resolve_squad(db, manager_id, target_gw, picks_gw)
    except Exception as e:
        raise HTTPException(404, f"Could not fetch squad for manager {manager_id}: {e}")

    if not resolved.player_ids:
        raise HTTPException(404, f"No squad found for manager {manager_id}")

    free_transfers = max(1, min(MAX_FREE_TRANSFERS, int(resolved.free_transfers)))

    # Plan from the first gameweek whose deadline is still open. Planning for
    # a gameweek already underway is pointless — the squad is locked.
    start_gw = target_gw

    try:
        result = await plan_horizon(
            db,
            squad_ids=resolved.player_ids,
            bank=resolved.bank,
            free_transfers=free_transfers,
            start_gw=start_gw,
            horizon=horizon,
            beam_width=beam_width,
            max_transfers_per_gw=max_transfers_per_gw,
            pool_per_position=pool_per_position,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    payload = serialise(result)
    payload.update({
        "manager_id": manager_id,
        "starting_bank": round(resolved.bank / 10, 1),
        "squad_source": resolved.source,
        "starting_free_transfers": free_transfers,
        "max_free_transfers": MAX_FREE_TRANSFERS,
    })
    return payload

