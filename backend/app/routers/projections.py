from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.rate_limit import limiter, HEAVY
from app.models.fpl import Player, Team, Gameweek
from app.models.projections import Projection, TeamStrength
from app.services.projection import rebuild_projections, MODEL_VERSION
from app.services.team_strength import rebuild_team_strength, MODEL_VERSION as FDR_VERSION
from app.services.backtest import backtest, ingest_player_history
from app.services.fpl_sync import get_active_gameweek

router = APIRouter(prefix="/projections", tags=["projections"])

POSITION_NAMES = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}


# ── Build ─────────────────────────────────────────────────────────────────────

@router.post("/rebuild/team-strength")
@limiter.limit(HEAVY)
async def rebuild_fdr(request: Request, db: AsyncSession = Depends(get_db)):
    """Recompute custom fixture-difficulty ratings from results so far."""
    return await rebuild_team_strength(db)


@router.post("/rebuild")
@limiter.limit(HEAVY)
async def rebuild(
    request: Request,
    horizon: int = Query(5, ge=1, le=38, description="How many upcoming GWs to project"),
    gameweeks: str | None = Query(None, description="Explicit GW list, e.g. '1,2,3'"),
    db: AsyncSession = Depends(get_db),
):
    """
    Rebuild player projections.

    Run POST /rebuild/team-strength first — projections read the FDR ratings.
    """
    gw_list = None
    if gameweeks:
        try:
            gw_list = [int(g.strip()) for g in gameweeks.split(",") if g.strip()]
        except ValueError:
            raise HTTPException(400, "gameweeks must be comma-separated integers")

    result = await rebuild_projections(db, gameweeks=gw_list, horizon=horizon)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


# ── Read ──────────────────────────────────────────────────────────────────────

@router.get("")
async def list_projections(
    gameweek: int | None = Query(None, description="Defaults to the active GW"),
    position: int | None = Query(None, ge=1, le=4),
    max_price: float | None = Query(None),
    min_minutes: float = Query(0, description="Filter out unlikely starters"),
    limit: int = Query(50, ge=1, le=300),
    db: AsyncSession = Depends(get_db),
):
    """Top projected players for a gameweek."""
    if gameweek is None:
        gw = await get_active_gameweek(db)
        if not gw:
            raise HTTPException(400, "No gameweek found — sync FPL data first.")
        gameweek = gw.id

    q = (
        select(Projection, Player, Team.short_name)
        .join(Player, Player.id == Projection.player_id)
        .join(Team, Team.id == Player.team_id)
        .where(
            Projection.gameweek_id == gameweek,
            Projection.model_version == MODEL_VERSION,
            Projection.expected_minutes >= min_minutes,
        )
    )
    if position:
        q = q.where(Player.position == position)
    if max_price is not None:
        q = q.where(Player.now_cost <= int(round(max_price * 10)))
    q = q.order_by(Projection.xpts.desc()).limit(limit)

    rows = (await db.execute(q)).all()
    if not rows:
        raise HTTPException(
            404,
            f"No projections for GW{gameweek}. Run POST /api/v1/projections/rebuild first.",
        )

    return [
        {
            "player_id": p.id,
            "name": p.web_name,
            "team": short,
            "position": POSITION_NAMES.get(p.position, "UNK"),
            "price": round(p.now_cost / 10, 1),
            "xpts": proj.xpts,
            "variance": proj.variance,
            "value": round(proj.xpts / (p.now_cost / 10), 3) if p.now_cost else 0,
            "expected_minutes": proj.expected_minutes,
            "p_start": proj.p_start,
            "p_60_plus": proj.p_60_plus,
            "custom_fdr": proj.custom_fdr,
            "fixture_count": proj.fixture_count,
            "is_penalty_taker": p.penalties_order == 1,
            "status": p.status,
        }
        for proj, p, short in rows
    ]


@router.get("/player/{player_id}")
async def player_projections(
    player_id: int,
    horizon: int = Query(5, ge=1, le=38),
    db: AsyncSession = Depends(get_db),
):
    """
    Full projection breakdown for one player across upcoming gameweeks.

    Returns every scoring component so a recommendation can be explained
    rather than asserted.
    """
    player = await db.get(Player, player_id)
    if not player:
        raise HTTPException(404, f"Player {player_id} not found")

    rows = (await db.execute(
        select(Projection)
        .where(
            Projection.player_id == player_id,
            Projection.model_version == MODEL_VERSION,
        )
        .order_by(Projection.gameweek_id)
        .limit(horizon)
    )).scalars().all()

    if not rows:
        raise HTTPException(404, "No projections. Run POST /api/v1/projections/rebuild first.")

    teams = {t.id: t.short_name for t in (await db.execute(select(Team))).scalars().all()}

    return {
        "player_id": player.id,
        "name": player.web_name,
        "team": teams.get(player.team_id),
        "position": POSITION_NAMES.get(player.position, "UNK"),
        "price": round(player.now_cost / 10, 1),
        "set_pieces": {
            "penalties": player.penalties_order,
            "corners_freekicks": player.corners_freekicks_order,
            "direct_freekicks": player.direct_freekicks_order,
        },
        "price_change": {
            "percent_to_threshold": player.price_change_percent,
            "net_transfers_gw": player.net_transfers,
            "projections": player.price_change_projections,
        },
        "total_xpts": round(sum(r.xpts for r in rows), 2),
        "gameweeks": [
            {
                "gameweek": r.gameweek_id,
                "xpts": r.xpts,
                "variance": r.variance,
                "expected_minutes": r.expected_minutes,
                "p_start": r.p_start,
                "p_60_plus": r.p_60_plus,
                "availability_multiplier": r.availability_multiplier,
                "custom_fdr": r.custom_fdr,
                "expected_team_goals": r.expected_team_goals,
                "expected_team_conceded": r.expected_team_conceded,
                "opponents": [
                    {**o, "opponent_name": teams.get(o.get("opponent"))}
                    for o in (r.opponents or [])
                ],
                "components": {
                    "appearance": r.xpts_appearance,
                    "goals": r.xpts_goals,
                    "assists": r.xpts_assists,
                    "clean_sheet": r.xpts_clean_sheet,
                    "goals_conceded": r.xpts_goals_conceded,
                    "saves": r.xpts_saves,
                    "defensive_contribution": r.xpts_defensive_contribution,
                    "bonus": r.xpts_bonus,
                    "cards": r.xpts_cards,
                    "penalties": r.xpts_penalties,
                },
            }
            for r in rows
        ],
    }


@router.get("/team-strength")
async def team_strength(db: AsyncSession = Depends(get_db)):
    """Derived attack/defence ratings behind the custom FDR."""
    rows = (await db.execute(
        select(TeamStrength, Team.short_name, Team.name)
        .join(Team, Team.id == TeamStrength.team_id)
        .where(TeamStrength.model_version == FDR_VERSION)
        .order_by(TeamStrength.attack_home.desc())
    )).all()

    if not rows:
        raise HTTPException(
            404, "No ratings. Run POST /api/v1/projections/rebuild/team-strength first."
        )

    return [
        {
            "team": short,
            "name": name,
            "matches_played": ts.matches_played,
            "attack_home": ts.attack_home,
            "attack_away": ts.attack_away,
            "defence_home": ts.defence_home,
            "defence_away": ts.defence_away,
            "observed_scored_per_match": ts.observed_scored_per_match,
            "observed_conceded_per_match": ts.observed_conceded_per_match,
            "prior_weight": ts.prior_weight,
        }
        for ts, short, name in rows
    ]


# ── Backtest ──────────────────────────────────────────────────────────────────

@router.post("/backtest/ingest-history")
@limiter.limit(HEAVY)
async def ingest_history(
    request: Request,
    limit: int = Query(100, ge=1, le=700, description="Top-N players by points"),
    db: AsyncSession = Depends(get_db),
):
    """
    Pull per-GW actual results for the backtest ground truth.

    One FPL request per player, so this takes a while for large limits.
    """
    return await ingest_player_history(db, limit=limit)


@router.get("/backtest")
async def run_backtest(
    gameweeks: str | None = Query(None, description="e.g. '1,2'; defaults to all finished"),
    min_expected_minutes: float = Query(0.0),
    model_version: str = Query(MODEL_VERSION),
    db: AsyncSession = Depends(get_db),
):
    """Score stored projections against recorded actuals."""
    gw_list = None
    if gameweeks:
        try:
            gw_list = [int(g.strip()) for g in gameweeks.split(",") if g.strip()]
        except ValueError:
            raise HTTPException(400, "gameweeks must be comma-separated integers")

    return await backtest(
        db,
        model_version=model_version,
        gameweeks=gw_list,
        min_expected_minutes=min_expected_minutes,
    )
