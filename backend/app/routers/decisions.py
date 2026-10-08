import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.auth import ManagerAccess, Premium
from app.database import get_db
from app.rate_limit import limiter, HEAVY, UPSTREAM
from app.models.fpl import Player, Team, Fixture, Gameweek
from app.models.projections import Projection
from app.services.fpl_sync import (
    get_active_gameweek, get_next_open_gameweek, get_latest_started_gameweek,
    deadline_has_passed,
)
from app.services.fpl_client import fetch_manager_picks
from app.services.projection import MODEL_VERSION
from app.services.lineup import (
    SquadEntry, best_starting_xi, pick_captain_and_vice, captain_candidates,
)
from app.services.transfers import (
    TransferCandidate, optimise_transfers, compare_transfer_counts,
)
from app.services.confidence import compute_confidence
from app.services.feedback import (
    snapshot_recommendation, KIND_CAPTAIN, KIND_LINEUP, KIND_TRANSFER,
)
from app.services.squad_state import resolve_squad
from app.services.transfer_reasons import explain_plans

router = APIRouter(prefix="/decisions", tags=["decisions"])
logger = logging.getLogger("fpl_copilot.decisions")

POS_NAME = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}


# ── Shared loading ────────────────────────────────────────────────────────────

async def _resolve_gameweek(db: AsyncSession, requested: int | None) -> Gameweek:
    """
    The gameweek a recommendation should target.

    Defaults to the next gameweek with an OPEN deadline, not the one currently
    being played. Once a deadline passes the squad is locked, so advice about
    that gameweek describes a transfer the manager can no longer make.
    """
    if requested is not None:
        gw = await db.get(Gameweek, requested)
        if not gw:
            raise HTTPException(404, f"Gameweek {requested} not found")
        return gw
    gw = await get_next_open_gameweek(db)
    if not gw:
        raise HTTPException(400, "No gameweek found — sync FPL data first.")
    return gw


async def _load_squad(
    db: AsyncSession,
    manager_id: int,
    target_gw: int,
    picks_gw: int,
) -> tuple[list[SquadEntry], dict]:
    """
    Fetch a manager's 15 players and pair each with his projection for
    `target_gw`.

    `picks_gw` is the gameweek to read the squad from, which is not always the
    gameweek being projected: picks only exist for gameweeks that have started.
    """
    # Prefers a manager-recorded override, because FPL cannot expose transfers
    # made for a gameweek that has not started yet.
    try:
        resolved = await resolve_squad(db, manager_id, target_gw, picks_gw)
    except Exception:
        logger.warning("squad lookup failed", exc_info=True, extra={"manager_id": manager_id})
        raise HTTPException(
            404,
            f"Could not fetch picks for manager {manager_id} GW{picks_gw}. "
            "That gameweek may not have started.",
        )

    player_ids = resolved.player_ids
    if not player_ids:
        raise HTTPException(404, f"No picks for manager {manager_id} GW{picks_gw}")

    rows = (await db.execute(
        select(Player, Team.short_name, Projection)
        .join(Team, Team.id == Player.team_id)
        .outerjoin(
            Projection,
            (Projection.player_id == Player.id)
            & (Projection.gameweek_id == target_gw)
            & (Projection.model_version == MODEL_VERSION),
        )
        .where(Player.id.in_(player_ids))
    )).all()

    entries = [
        SquadEntry(player=p, projection=proj, team_short=short)
        for p, short, proj in rows
    ]
    if not entries:
        raise HTTPException(404, "None of the squad's players are in our database")

    missing = [e.player.web_name for e in entries if e.projection is None]

    meta = {
        "manager_id": manager_id,
        "target_gameweek": target_gw,
        "bank": resolved.bank,
        "team_value": sum(e.player.now_cost for e in entries),
        "free_transfers": resolved.free_transfers,
        "players_without_projection": missing,
        # Which squad this advice is about, and whether it may be stale.
        **resolved.meta(),
    }
    return entries, meta


async def _matches_played(db: AsyncSession) -> int:
    return (await db.execute(
        select(func.count(func.distinct(Fixture.gameweek_id)))
        .where((Fixture.finished.is_(True)) | (Fixture.finished_provisional.is_(True)))
    )).scalar() or 0


async def _picks_gameweek(db: AsyncSession, target: Gameweek) -> int:
    """
    Which gameweek to read the manager's squad from.

    FPL only exposes picks for gameweeks that have started, so this is the most
    recent started gameweek — deliberately not the same as the target, which is
    the next one still open.
    """
    started = await get_latest_started_gameweek(db)
    if started is not None:
        return started.id
    # Pre-season: nothing has started, so no picks exist anywhere.
    raise HTTPException(
        400,
        "No gameweek has started yet, so there is no squad to read. "
        "Recommendations become available once the season is under way.",
    )


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
    gw = await _resolve_gameweek(db, gameweek)
    squad, meta = await _load_squad(db, manager_id, gw.id, await _picks_gameweek(db, gw))

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
    gw = await _resolve_gameweek(db, gameweek)
    squad, meta = await _load_squad(db, manager_id, gw.id, await _picks_gameweek(db, gw))
    lineup = best_starting_xi(squad)
    matches = await _matches_played(db)

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
    gw = await _resolve_gameweek(db, gameweek)
    squad, meta = await _load_squad(db, manager_id, gw.id, await _picks_gameweek(db, gw))
    matches = await _matches_played(db)

    # Horizon window starting at the target gameweek
    horizon_gws = (await db.execute(
        select(Gameweek.id)
        .where(Gameweek.id >= gw.id)
        .order_by(Gameweek.id)
        .limit(horizon)
    )).scalars().all()

    if not horizon_gws:
        raise HTTPException(400, "No gameweeks in horizon")

    # Sum projected points per player across the horizon
    totals = dict((await db.execute(
        select(Projection.player_id, func.sum(Projection.xpts))
        .where(
            Projection.gameweek_id.in_(horizon_gws),
            Projection.model_version == MODEL_VERSION,
        )
        .group_by(Projection.player_id)
    )).all())

    if not totals:
        raise HTTPException(
            400,
            "No projections in the horizon. Run POST /api/v1/projections/rebuild first.",
        )

    owned_ids = {e.player.id for e in squad}
    owned = [
        TransferCandidate(
            player=e.player,
            horizon_xpts=float(totals.get(e.player.id, 0.0)),
            team_short=e.team_short,
        )
        for e in squad
    ]

    # Candidate pool: best projected players per position, excluding the squad
    # and anyone flagged unavailable.
    pool: list[TransferCandidate] = []
    per_position = max(10, pool_size // 4)
    for position in (1, 2, 3, 4):
        rows = (await db.execute(
            select(Player, Team.short_name, func.sum(Projection.xpts).label("total"))
            .join(Team, Team.id == Player.team_id)
            .join(Projection, Projection.player_id == Player.id)
            .where(
                Projection.gameweek_id.in_(horizon_gws),
                Projection.model_version == MODEL_VERSION,
                Player.position == position,
                Player.id.notin_(owned_ids),
                Player.status == "a",
            )
            .group_by(Player.id, Team.short_name)
            .order_by(func.sum(Projection.xpts).desc())
            .limit(per_position)
        )).all()
        pool.extend(
            TransferCandidate(player=p, horizon_xpts=float(total), team_short=short)
            for p, short, total in rows
        )

    plans = compare_transfer_counts(
        owned=owned,
        pool=pool,
        bank=int(meta["bank"]),
        free_transfers=int(meta["free_transfers"]),
        max_transfers=max_transfers,
    )

    # Recommend the plan with the best net gain; ties go to fewer transfers.
    best = max(plans, key=lambda p: (p.net_gain, -p.transfers_made))
    alternatives = [p for p in plans if p is not best]
    next_best = max((p.net_gain for p in alternatives), default=None)

    # Confidence rests on the players actually being moved, not the squad as a
    # whole: the incoming players' start probability is what the gain depends on.
    async def _min_p_start(player_ids: list[int]) -> float | None:
        if not player_ids:
            return None
        values = (await db.execute(
            select(Projection.p_start).where(
                Projection.player_id.in_(player_ids),
                Projection.gameweek_id == gw.id,
                Projection.model_version == MODEL_VERSION,
            )
        )).scalars().all()
        return min(values) if values else None

    in_ids = [p["player_id"] for p in best.players_in]
    out_ids = [p["player_id"] for p in best.players_out]

    p_start_in = await _min_p_start(in_ids)
    p_start_out = await _min_p_start(out_ids)

    # Holding has no incoming player; its reliability rests on the squad as-is.
    if p_start_in is None:
        p_start_in = min((e.p_start for e in squad), default=1.0)

    # Variance of the players involved, falling back to the squad average
    involved = [e for e in squad if e.player.id in set(out_ids)]
    variance = (
        sum(e.variance for e in involved) / len(involved) if involved
        else sum(e.variance for e in squad) / max(1, len(squad))
    )

    conf = compute_confidence(
        data_updated_at=max(
            (e.projection.updated_at for e in squad if e.projection), default=None
        ),
        p_start_in=p_start_in,
        p_start_out=p_start_out,
        variance=variance,
        expected_gain=best.net_gain,
        next_best_gain=next_best,
        matches_played=matches,
    )

    def plan_dict(p) -> dict:
        return {
            "transfers": p.transfers_made,
            "hit": p.hit,
            "out": p.players_out,
            "in": p.players_in,
            "squad_xpts_before": p.squad_xpts_before,
            "squad_xpts_after": p.squad_xpts_after,
            "net_gain": p.net_gain,
            "bank_after": p.bank_after,
            "note": p.note,
        }

    action = "HOLD"
    if best.transfers_made == 1:
        action = "TRANSFER"
    elif best.transfers_made > 1:
        action = f"TRANSFER x{best.transfers_made}"

    best_plan = plan_dict(best)
    alternative_plans = [plan_dict(p) for p in alternatives]
    await explain_plans(db, [best_plan, *alternative_plans], list(horizon_gws))

    return {
        **meta,
        "horizon": horizon_gws,
        "pool_size": len(pool),
        "recommendation": {
            "action": action,
            "horizon_gameweeks": len(horizon_gws),
            "expected_net_gain": best.net_gain,
            "hit_taken": best.hit,
            **conf.as_dict(),
            "plan": best_plan,
        },
        "alternatives": alternative_plans,
    }


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
    recommended transfer, in one response.
    """
    gw = await _resolve_gameweek(db, gameweek)
    squad, meta = await _load_squad(db, manager_id, gw.id, await _picks_gameweek(db, gw))

    lineup = best_starting_xi(squad)
    captain, vice, ranked = pick_captain_and_vice(lineup.starting, mode=captain_mode)

    issues = [
        {
            **e.brief(),
            "news": e.player.news,
            "chance_of_playing": e.player.chance_of_playing_this_round,
            "reason": (
                "Unavailable" if e.player.status in ("i", "s", "u", "n")
                else "Doubtful" if e.player.status == "d"
                else "Rotation risk"
            ),
        }
        for e in squad
        if e.player.status != "a" or e.p_start < 0.5
    ]

    transfers = await recommend_transfers(
        request=request, manager_id=manager_id, gameweek=gw.id, horizon=horizon,
        max_transfers=2, pool_size=140, db=db,
    )

    # Record the advice so it can be graded once the gameweek finishes.
    #
    # Only before the deadline: snapshotting afterwards would be recording a
    # "prediction" of a result we can already see, which would flatter the
    # accuracy history into meaninglessness.
    snapshotted = False
    if _before_deadline(gw):
        await _snapshot_advice(
            db,
            manager_id=manager_id,
            gameweek_id=gw.id,
            lineup=lineup,
            captain=captain,
            transfer=transfers["recommendation"],
        )
        snapshotted = True

    return {
        **meta,
        "recorded_for_accuracy": snapshotted,
        "gameweek": {
            "id": gw.id,
            "name": gw.name,
            "deadline_time": gw.deadline_time,
            "is_current": gw.is_current,
            "deadline_passed": deadline_has_passed(gw),
        },
        "lineup": {
            "formation": lineup.formation,
            "starting_xpts": lineup.starting_xpts,
            "bench_xpts": lineup.bench_xpts,
            "projected_total": round(
                lineup.starting_xpts + (captain.xpts if captain else 0.0), 2
            ),
            "starting": [e.brief() for e in lineup.starting],
            "bench": [
                {**e.brief(), "bench_order": i} for i, e in enumerate(lineup.bench)
            ],
        },
        "captain": {
            "pick": captain.brief() if captain else None,
            "vice": vice.brief() if vice else None,
            "mode": captain_mode,
            "ranking": ranked,
        },
        "squad_issues": issues,
        "transfer": transfers["recommendation"],
        "transfer_alternatives": transfers["alternatives"],
    }


# ── Accuracy recording ────────────────────────────────────────────────────────

def _before_deadline(gw: Gameweek) -> bool:
    """
    Has the gameweek deadline not yet passed?

    Advice recorded after the deadline cannot be a prediction, so it must not
    enter the accuracy history.
    """
    if gw.deadline_time is None:
        return False
    deadline = gw.deadline_time
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) < deadline


async def _snapshot_advice(
    db: AsyncSession,
    *,
    manager_id: int,
    gameweek_id: int,
    lineup,
    captain,
    transfer: dict,
) -> None:
    """Freeze the three gradeable decisions for this gameweek."""
    if captain is not None:
        await snapshot_recommendation(
            db,
            fpl_entry_id=manager_id,
            gameweek_id=gameweek_id,
            kind=KIND_CAPTAIN,
            model_version=MODEL_VERSION,
            payload={
                "player_id": captain.player.id,
                "name": captain.player.web_name,
                "team": captain.team_short,
            },
            # Captain scores double, so that is what we are predicting.
            predicted_value=round(captain.xpts * 2, 3),
        )

    await snapshot_recommendation(
        db,
        fpl_entry_id=manager_id,
        gameweek_id=gameweek_id,
        kind=KIND_LINEUP,
        model_version=MODEL_VERSION,
        payload={
            "starting_ids": [e.player.id for e in lineup.starting],
            "bench_ids": [e.player.id for e in lineup.bench],
            "formation": lineup.formation,
        },
        predicted_value=lineup.starting_xpts,
    )

    plan = transfer.get("plan", {}) or {}
    await snapshot_recommendation(
        db,
        fpl_entry_id=manager_id,
        gameweek_id=gameweek_id,
        kind=KIND_TRANSFER,
        model_version=MODEL_VERSION,
        payload={
            "action": transfer.get("action"),
            "in": [
                {"player_id": p["player_id"], "name": p.get("name")}
                for p in plan.get("in", [])
            ],
            "out": [
                {"player_id": p["player_id"], "name": p.get("name")}
                for p in plan.get("out", [])
            ],
            "hit": transfer.get("hit_taken", 0),
            "horizon_gameweeks": transfer.get("horizon_gameweeks"),
        },
        predicted_value=transfer.get("expected_net_gain", 0.0),
        confidence=transfer.get("confidence", 0),
    )
