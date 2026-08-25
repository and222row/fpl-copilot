from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.rate_limit import limiter, HEAVY, UPSTREAM
from app.models.fpl import Player, Team, Gameweek, Fixture
from app.services.fpl_sync import (
    sync_bootstrap, sync_fixtures, get_active_gameweek,
    get_next_open_gameweek, deadline_has_passed,
)
from app.services.fpl_client import fetch_manager_info, fetch_manager_picks
from app.services.jobs import register_manager
from app.services.squad_state import (
    resolve_squad, apply_transfers, clear_override,
)
from app.services.fpl_sync import get_latest_started_gameweek
from pydantic import BaseModel, Field

router = APIRouter(prefix="/fpl", tags=["fpl"])

POSITION_NAMES = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
STATUS_NAMES = {
    "a": "Available",
    "d": "Doubtful",
    "i": "Injured",
    "s": "Suspended",
    "u": "Unavailable",
    "n": "Not in squad",
}


# ── Sync ──────────────────────────────────────────────────────────────────────

@router.post("/sync/bootstrap")
@limiter.limit(HEAVY)
async def trigger_bootstrap_sync(request: Request, db: AsyncSession = Depends(get_db)):
    """Pull latest teams, gameweeks and players from FPL into our database."""
    try:
        result = await sync_bootstrap(db)
    except Exception as e:
        raise HTTPException(502, f"FPL bootstrap sync failed: {e}")
    return {"ok": True, "synced": result}


@router.post("/sync/fixtures")
@limiter.limit(HEAVY)
async def trigger_fixture_sync(request: Request, db: AsyncSession = Depends(get_db)):
    """Pull all season fixtures from FPL. Run after /sync/bootstrap."""
    try:
        count = await sync_fixtures(db)
    except Exception as e:
        raise HTTPException(502, f"FPL fixture sync failed: {e}")
    return {"ok": True, "fixtures_synced": count}


# ── Gameweeks ─────────────────────────────────────────────────────────────────

@router.get("/gameweek")
async def active_gameweek(db: AsyncSession = Depends(get_db)):
    """
    The gameweek the dashboard works on: the next one with an OPEN deadline.

    Not the gameweek currently being played. Showing a passed deadline in the
    header while offering transfer advice implies the advice is actionable when
    it is not. `current_gameweek` still reports what is live, so nothing is lost.
    """
    gw = await get_next_open_gameweek(db)
    if not gw:
        raise HTTPException(404, "No gameweek found — run POST /api/v1/fpl/sync/bootstrap first.")

    live = await get_active_gameweek(db)
    return {
        "id": gw.id,
        "name": gw.name,
        "deadline_time": gw.deadline_time,
        "deadline_passed": deadline_has_passed(gw),
        "finished": gw.finished,
        "is_current": gw.is_current,
        "is_next": gw.is_next,
        "average_entry_score": gw.average_entry_score,
        "highest_score": gw.highest_score,
        "current_gameweek": live.id if live else None,
    }


# ── Players ───────────────────────────────────────────────────────────────────

PHOTO_BASE = "https://resources.premierleague.com/premierleague/photos/players"


def player_photo(code: int) -> str | None:
    """FPL headshot URL, or None when the code is missing."""
    return f"{PHOTO_BASE}/110x140/p{code}.png" if code else None


def _player_summary(p: Player, team_short: str) -> dict:
    return {
        "id": p.id,
        "name": p.web_name,
        "photo": player_photo(p.code),
        "full_name": f"{p.first_name} {p.second_name}".strip(),
        "team": team_short,
        "position": POSITION_NAMES.get(p.position, "UNK"),
        "price": round(p.now_cost / 10, 1),
        "total_points": p.total_points,
        "form": p.form,
        "ep_this": p.ep_this,
        "ep_next": p.ep_next,
        "selected_by_percent": p.selected_by_percent,
        "status": p.status,
        "status_label": STATUS_NAMES.get(p.status, p.status),
        "news": p.news,
        "chance_this": p.chance_of_playing_this_round,
        "minutes": p.minutes,
    }


@router.get("/players")
async def list_players(
    position: int | None = Query(None, ge=1, le=4, description="1=GK 2=DEF 3=MID 4=FWD"),
    team_id: int | None = Query(None),
    status: str | None = Query(None, description="a|d|i|s|u|n"),
    max_price: float | None = Query(None, description="In millions, e.g. 8.5"),
    sort_by: str = Query("total_points", pattern="^(total_points|form|ep_next|now_cost|selected_by_percent)$"),
    limit: int = Query(50, ge=1, le=300),
    db: AsyncSession = Depends(get_db),
):
    sort_col = {
        "total_points": Player.total_points,
        "form": Player.form,
        "ep_next": Player.ep_next,
        "now_cost": Player.now_cost,
        "selected_by_percent": Player.selected_by_percent,
    }[sort_by]

    q = select(Player, Team.short_name).join(Team, Player.team_id == Team.id)
    if position:
        q = q.where(Player.position == position)
    if team_id:
        q = q.where(Player.team_id == team_id)
    if status:
        q = q.where(Player.status == status)
    if max_price is not None:
        q = q.where(Player.now_cost <= int(round(max_price * 10)))
    q = q.order_by(sort_col.desc()).limit(limit)

    rows = (await db.execute(q)).all()
    return [_player_summary(p, short) for p, short in rows]


@router.get("/players/{player_id}")
async def get_player(player_id: int, db: AsyncSession = Depends(get_db)):
    row = (await db.execute(
        select(Player, Team.name, Team.short_name)
        .join(Team, Player.team_id == Team.id)
        .where(Player.id == player_id)
    )).one_or_none()

    if row is None:
        raise HTTPException(404, f"Player {player_id} not found")

    p, team_name, team_short = row
    return {
        **_player_summary(p, team_short),
        "team_full": team_name,
        "chance_next": p.chance_of_playing_next_round,
        "starts": p.starts,
        "goals": p.goals_scored,
        "assists": p.assists,
        "clean_sheets": p.clean_sheets,
        "goals_conceded": p.goals_conceded,
        "yellow_cards": p.yellow_cards,
        "red_cards": p.red_cards,
        "saves": p.saves,
        "bonus": p.bonus,
        "bps": p.bps,
        "ict_index": p.ict_index,
        "expected_goals": p.expected_goals,
        "expected_assists": p.expected_assists,
        "expected_goal_involvements": p.expected_goal_involvements,
        "transfers_in_gw": p.transfers_in_event,
        "transfers_out_gw": p.transfers_out_event,
        "net_transfers_gw": p.transfers_in_event - p.transfers_out_event,
    }


# ── Teams ─────────────────────────────────────────────────────────────────────

@router.get("/teams")
async def list_teams(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Team).order_by(Team.name))).scalars().all()
    return [
        {
            "id": t.id,
            "name": t.name,
            "short_name": t.short_name,
            "strength": t.strength,
            "strength_attack_home": t.strength_attack_home,
            "strength_attack_away": t.strength_attack_away,
            "strength_defence_home": t.strength_defence_home,
            "strength_defence_away": t.strength_defence_away,
        }
        for t in rows
    ]


# ── Fixtures ──────────────────────────────────────────────────────────────────

@router.get("/fixtures")
async def list_fixtures(
    gameweek: int | None = Query(None),
    team_id: int | None = Query(None),
    limit: int = Query(50, ge=1, le=400),
    db: AsyncSession = Depends(get_db),
):
    q = select(Fixture)
    if gameweek:
        q = q.where(Fixture.gameweek_id == gameweek)
    if team_id:
        q = q.where((Fixture.team_h == team_id) | (Fixture.team_a == team_id))
    q = q.order_by(Fixture.kickoff_time.nulls_last()).limit(limit)

    fixtures = (await db.execute(q)).scalars().all()

    # Resolve team names in one query
    teams = {t.id: t.short_name for t in (await db.execute(select(Team))).scalars().all()}

    return [
        {
            "id": f.id,
            "gameweek": f.gameweek_id,
            "kickoff_time": f.kickoff_time,
            "home": teams.get(f.team_h, str(f.team_h)),
            "away": teams.get(f.team_a, str(f.team_a)),
            "home_score": f.team_h_score,
            "away_score": f.team_a_score,
            "home_difficulty": f.team_h_difficulty,
            "away_difficulty": f.team_a_difficulty,
            "finished": f.finished,
            "started": f.started,
        }
        for f in fixtures
    ]


# ── Manager ───────────────────────────────────────────────────────────────────

@router.get("/manager/{manager_id}")
@limiter.limit(UPSTREAM)
async def get_manager(request: Request, manager_id: int):
    """Manager profile straight from FPL — no local data needed."""
    try:
        info = await fetch_manager_info(manager_id)
    except Exception as e:
        raise HTTPException(404, f"Could not fetch manager {manager_id}: {e}")

    return {
        "id": info["id"],
        "manager_name": f"{info.get('player_first_name','')} {info.get('player_last_name','')}".strip(),
        "team_name": info.get("name"),
        "overall_points": info.get("summary_overall_points"),
        "overall_rank": info.get("summary_overall_rank"),
        "gameweek_points": info.get("summary_event_points"),
        "gameweek_rank": info.get("summary_event_rank"),
        "bank": (info.get("last_deadline_bank") or 0) / 10,
        "team_value": (info.get("last_deadline_value") or 0) / 10,
        "total_transfers": info.get("last_deadline_total_transfers"),
        "started_event": info.get("started_event"),
    }


@router.get("/manager/{manager_id}/squad")
@limiter.limit(UPSTREAM)
async def get_manager_squad(
    request: Request,
    manager_id: int,
    gameweek: int | None = Query(None, description="Defaults to the active GW"),
    db: AsyncSession = Depends(get_db),
):
    """
    A manager's 15-player squad, enriched with our player data.
    slot 1-11 = starting XI, slot 12-15 = bench.
    """
    # Everything that reads a squad goes through resolve_squad, so a recorded
    # transfer is reflected here too. Reading FPL picks directly showed players
    # the manager had already sold.
    target_gw = gameweek
    if target_gw is None:
        gw = await get_next_open_gameweek(db)
        if not gw:
            raise HTTPException(400, "No gameweek found — run POST /api/v1/fpl/sync/bootstrap first.")
        target_gw = gw.id

    started = await get_latest_started_gameweek(db)
    if started is None:
        raise HTTPException(400, "No gameweek has started yet, so there is no squad to show.")

    try:
        resolved = await resolve_squad(db, manager_id, target_gw, started.id)
    except Exception as e:
        raise HTTPException(
            404,
            f"Could not fetch picks for manager {manager_id} GW{started.id}. ({e})",
        )

    picks_data = await fetch_manager_picks(manager_id, started.id)
    picks = picks_data.get("picks", [])

    # An override changes who is in the squad, so the slot/captain data from FPL
    # no longer lines up. Rebuild it: incoming players take the slot of whoever
    # they replaced, and a captain who has been sold is dropped.
    if resolved.is_override:
        owned = set(resolved.player_ids)
        original = [p["element"] for p in picks]
        departed = [pid for pid in original if pid not in owned]
        arrived = [pid for pid in resolved.player_ids if pid not in set(original)]
        replacement = dict(zip(departed, arrived))

        rebuilt = []
        for pick in picks:
            pid = pick["element"]
            if pid in owned:
                rebuilt.append(pick)
            elif pid in replacement:
                rebuilt.append({
                    **pick,
                    "element": replacement[pid],
                    # A player just brought in was not the captain
                    "is_captain": False,
                    "is_vice_captain": False,
                    "multiplier": pick.get("multiplier", 1),
                    "transferred_in": True,
                    "replaced": pid,
                })
        picks = rebuilt
    if not picks:
        raise HTTPException(404, f"No picks returned for manager {manager_id} GW{gameweek}")

    player_ids = [p["element"] for p in picks]
    rows = (await db.execute(
        select(Player, Team.short_name)
        .join(Team, Player.team_id == Team.id)
        .where(Player.id.in_(player_ids))
    )).all()
    player_map = {p.id: (p, short) for p, short in rows}

    # Names of players who left, so a card can show "Raya → Tzolakis"
    replaced_ids = [pk["replaced"] for pk in picks if pk.get("replaced")]
    player_names: dict[int, str] = {}
    if replaced_ids:
        player_names = dict((await db.execute(
            select(Player.id, Player.web_name).where(Player.id.in_(replaced_ids))
        )).all())

    squad = []
    for pick in picks:
        pid = pick["element"]
        entry = player_map.get(pid)
        if entry is None:
            # Player exists in FPL but not in our DB — sync is stale
            squad.append({
                "slot": pick["position"],
                "player_id": pid,
                "name": f"Unknown ({pid})",
                "unmapped": True,
                "is_captain": pick["is_captain"],
                "is_vice_captain": pick["is_vice_captain"],
                "multiplier": pick["multiplier"],
            })
            continue
        p, team_short = entry
        entry = {
            "slot": pick["position"],
            "is_starting": pick["position"] <= 11,
            "is_captain": pick["is_captain"],
            "is_vice_captain": pick["is_vice_captain"],
            "multiplier": pick["multiplier"],
            **_player_summary(p, team_short),
        }
        if pick.get("transferred_in"):
            entry["transferred_in"] = True
            entry["replaced_player_id"] = pick.get("replaced")
            entry["replaced_name"] = player_names.get(pick.get("replaced"))
        squad.append(entry)

    squad.sort(key=lambda x: x["slot"])

    # Remember this team so the background job can generate its alerts.
    await register_manager(db, manager_id)

    entry_history = picks_data.get("entry_history", {}) or {}
    transfers = picks_data.get("transfers", {}) or {}

    return {
        "manager_id": manager_id,
        "gameweek": gameweek,
        "points": entry_history.get("points"),
        "total_points": entry_history.get("total_points"),
        "overall_rank": entry_history.get("overall_rank"),
        "bank": (entry_history.get("bank") or 0) / 10,
        "team_value": (entry_history.get("value") or 0) / 10,
        "event_transfers": entry_history.get("event_transfers"),
        "event_transfers_cost": entry_history.get("event_transfers_cost"),
        "free_transfers": transfers.get("limit"),
        "active_chip": picks_data.get("active_chip"),
        "squad": squad,
    }


# ── Squad overrides ───────────────────────────────────────────────────────────
#
# FPL cannot expose transfers made for a gameweek that has not started, so the
# newest squad it reports is the one locked at the last deadline. These let a
# manager correct that rather than receiving advice about a squad they no longer
# own — including a re-suggestion of a transfer they already made.

class TransferMoveIn(BaseModel):
    out_player: int = Field(..., alias="out", description="Player leaving")
    in_player: int = Field(..., alias="in", description="Player arriving")

    model_config = {"populate_by_name": True}


class ApplyTransfersIn(BaseModel):
    moves: list[TransferMoveIn] = Field(..., min_length=1, max_length=15)


@router.get("/manager/{manager_id}/squad-state")
async def squad_state(
    manager_id: int,
    gameweek: int | None = Query(None, description="Defaults to the next open GW"),
    db: AsyncSession = Depends(get_db),
):
    """
    Which squad the app believes you hold, and where that came from.

    `squad_source` is `fpl_api` (locked at the last deadline) or
    `manager_override` (what you told us). When they differ from the target
    gameweek, `stale_warning` explains why.
    """
    target = gameweek
    if target is None:
        gw = await get_next_open_gameweek(db)
        if not gw:
            raise HTTPException(400, "No gameweek found — sync FPL data first.")
        target = gw.id

    started = await get_latest_started_gameweek(db)
    if started is None:
        raise HTTPException(400, "No gameweek has started yet.")

    try:
        resolved = await resolve_squad(db, manager_id, target, started.id)
    except Exception as e:
        raise HTTPException(404, f"Could not resolve squad: {e}")

    rows = (await db.execute(
        select(Player, Team.short_name)
        .join(Team, Team.id == Player.team_id)
        .where(Player.id.in_(resolved.player_ids))
    )).all()

    return {
        "manager_id": manager_id,
        "target_gameweek": target,
        **resolved.meta(),
        "bank": round(resolved.bank / 10, 1),
        "free_transfers": resolved.free_transfers,
        "squad": [_player_summary(p, short) for p, short in rows],
    }


@router.post("/manager/{manager_id}/squad-state/transfers")
@limiter.limit(UPSTREAM)
async def record_transfers(
    request: Request,
    manager_id: int,
    body: ApplyTransfersIn,
    gameweek: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """
    Tell the app about transfers you have already made.

    Bank and free transfers are adjusted with them — an override is only useful
    if the money moves too. Discarded automatically once the gameweek starts,
    since FPL becomes authoritative again then.
    """
    target = gameweek
    if target is None:
        gw = await get_next_open_gameweek(db)
        if not gw:
            raise HTTPException(400, "No gameweek found — sync FPL data first.")
        target = gw.id

    started = await get_latest_started_gameweek(db)
    if started is None:
        raise HTTPException(400, "No gameweek has started yet.")

    ids = {m.out_player for m in body.moves} | {m.in_player for m in body.moves}
    costs = dict((await db.execute(
        select(Player.id, Player.now_cost).where(Player.id.in_(ids))
    )).all())

    unknown = ids - set(costs)
    if unknown:
        raise HTTPException(400, f"Unknown player IDs: {sorted(unknown)}")

    try:
        resolved = await apply_transfers(
            db,
            manager_id=manager_id,
            gameweek_id=target,
            picks_gw=started.id,
            moves=[{"out": m.out_player, "in": m.in_player} for m in body.moves],
            player_costs=costs,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    return {
        "manager_id": manager_id,
        "target_gameweek": target,
        **resolved.meta(),
        "bank": round(resolved.bank / 10, 1),
        "free_transfers": resolved.free_transfers,
        "squad_size": len(resolved.player_ids),
    }


@router.delete("/manager/{manager_id}/squad-state")
async def reset_squad_state(
    manager_id: int,
    gameweek: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Discard the override and go back to what FPL reports."""
    target = gameweek
    if target is None:
        gw = await get_next_open_gameweek(db)
        if not gw:
            raise HTTPException(400, "No gameweek found.")
        target = gw.id

    cleared = await clear_override(db, manager_id, target)
    return {"cleared": cleared, "target_gameweek": target}
