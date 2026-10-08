from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from app.auth import ManagerAccess, Premium
from app.database import get_db
from app.rate_limit import limiter, HEAVY, UPSTREAM
from app.models.fpl import Player, Team
from app.models.news import AvailabilityEvent, Alert
from app.services.change_detection import (
    detect_changes, generate_alerts, price_watch,
)
from app.services.news_parser import parse_news, resolve_availability, STATUS_LABEL
from app.services.fpl_sync import (
    get_active_gameweek, get_next_open_gameweek, get_latest_started_gameweek,
)
from app.services.squad_state import resolve_squad

router = APIRouter(prefix="/news", tags=["news"])

POS_NAME = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}


# ── Detection ─────────────────────────────────────────────────────────────────

@router.post("/detect")
@limiter.limit(HEAVY)
async def run_detection(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Diff current player state against the last snapshot and log any changes.

    The first run only establishes a baseline — it deliberately emits no
    events, so you do not get 609 alerts on day one.
    """
    return await detect_changes(db)


# ── Events feed ───────────────────────────────────────────────────────────────

@router.get("/events")
async def list_events(
    hours: int = Query(168, ge=1, le=2160, description="Look-back window"),
    min_materiality: float = Query(0.0, ge=0.0, le=1.0),
    event_type: str | None = Query(None),
    needs_review: bool | None = Query(None),
    limit: int = Query(60, ge=1, le=400),
    db: AsyncSession = Depends(get_db),
):
    """Chronological availability feed, newest first."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    q = (
        select(AvailabilityEvent, Player, Team.short_name)
        .join(Player, Player.id == AvailabilityEvent.player_id)
        .join(Team, Team.id == Player.team_id)
        .where(
            AvailabilityEvent.detected_at >= since,
            AvailabilityEvent.materiality >= min_materiality,
        )
    )
    if event_type:
        q = q.where(AvailabilityEvent.event_type == event_type)
    if needs_review is not None:
        q = q.where(AvailabilityEvent.requires_review.is_(needs_review))
    q = q.order_by(AvailabilityEvent.detected_at.desc()).limit(limit)

    rows = (await db.execute(q)).all()
    return [
        {
            "id": e.id,
            "detected_at": e.detected_at,
            "event_type": e.event_type,
            "player_id": p.id,
            "name": p.web_name,
            "team": short,
            "position": POS_NAME.get(p.position, "UNK"),
            "price": round(p.now_cost / 10, 1),
            "status_before": e.status_before,
            "status_after": e.status_after,
            "status_label": STATUS_LABEL.get(e.status_after or "a"),
            "availability_before": e.availability_before,
            "availability_after": e.availability_after,
            "cause": e.cause,
            "expected_return": e.expected_return,
            "news": e.news_text,
            "materiality": e.materiality,
            "requires_review": e.requires_review,
            "availability_source": e.availability_source,
        }
        for e, p, short in rows
    ]


# ── Alerts ────────────────────────────────────────────────────────────────────

@router.post("/alerts/{manager_id}/generate", dependencies=[ManagerAccess, Premium])
@limiter.limit(UPSTREAM)
async def create_alerts(
    request: Request,
    manager_id: int,
    hours: int = Query(168, ge=1, le=2160),
    min_materiality: float = Query(0.3, ge=0.0, le=1.0),
    db: AsyncSession = Depends(get_db),
):
    """
    Raise alerts for changes affecting this manager's squad.

    Uses the resolved squad, so a recorded transfer is respected — reading FPL
    picks directly would warn about players already sold.
    """
    target = await get_next_open_gameweek(db)
    started = await get_latest_started_gameweek(db)
    if not target or not started:
        raise HTTPException(400, "No gameweek found — sync FPL data first.")

    try:
        resolved = await resolve_squad(db, manager_id, target.id, started.id)
    except Exception as e:
        raise HTTPException(404, f"Could not fetch squad for manager {manager_id}: {e}")

    squad_ids = resolved.player_ids
    if not squad_ids:
        raise HTTPException(404, "No squad found")

    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    return await generate_alerts(
        db,
        fpl_entry_id=manager_id,
        squad_player_ids=squad_ids,
        since=since,
        min_materiality=min_materiality,
    )


@router.get("/alerts/{manager_id}", dependencies=[ManagerAccess, Premium])
async def list_alerts(
    manager_id: int,
    unread_only: bool = Query(False),
    include_sold: bool = Query(
        False,
        description="Include alerts about players no longer in the squad",
    ),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """
    This manager's alerts, newest first.

    Alerts about players who have since left the squad are hidden by default.
    An alert is meant to be actionable, and "the player you sold is about to
    rise" is not — it reads as a mistake even though it was true when raised.
    """
    q = select(Alert).where(Alert.fpl_entry_id == manager_id)
    if unread_only:
        q = q.where(Alert.read_at.is_(None))
    q = q.order_by(Alert.created_at.desc()).limit(limit)

    alerts = (await db.execute(q)).scalars().all()
    if not alerts:
        return []

    # Cross-check against the squad actually held now
    owned: set[int] | None = None
    try:
        target = await get_next_open_gameweek(db)
        started = await get_latest_started_gameweek(db)
        if target and started:
            resolved = await resolve_squad(db, manager_id, target.id, started.id)
            owned = set(resolved.player_ids)
    except Exception:
        # If the squad cannot be resolved, show everything rather than hiding
        # alerts on the basis of a failed lookup.
        owned = None

    out = []
    for a in alerts:
        still_owned = (
            None if owned is None or a.player_id is None
            else a.player_id in owned
        )
        if still_owned is False and not include_sold:
            continue
        out.append({
            "id": a.id,
            "severity": a.severity,
            "title": a.title,
            "body": a.body,
            "payload": a.payload,
            "player_id": a.player_id,
            "still_owned": still_owned,
            "read": a.read_at is not None,
            "created_at": a.created_at,
        })
    return out


@router.post("/alerts/{manager_id}/read", dependencies=[ManagerAccess, Premium])
async def mark_alerts_read(
    manager_id: int,
    alert_id: int | None = Query(None, description="Omit to mark all as read"),
    db: AsyncSession = Depends(get_db),
):
    stmt = update(Alert).where(
        Alert.fpl_entry_id == manager_id, Alert.read_at.is_(None)
    )
    if alert_id is not None:
        stmt = stmt.where(Alert.id == alert_id)
    result = await db.execute(stmt.values(read_at=datetime.now(timezone.utc)))
    await db.commit()
    return {"marked_read": result.rowcount}


# ── Price watch ───────────────────────────────────────────────────────────────

@router.get("/price-watch")
async def get_price_watch(
    threshold: float = Query(
        50.0, ge=0, le=100,
        description="Minimum % progress toward FPL's price-change threshold",
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Players near a price change, from FPL's own published projections.

    Deterministic — no model involved.
    """
    return await price_watch(db, threshold=threshold)


# ── Parser inspection ─────────────────────────────────────────────────────────

@router.get("/parse-check")
async def parse_check(
    limit: int = Query(200, ge=1, le=700),
    only_unparsed: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    """
    Show how the parser reads every current news string.

    An admin view for spotting a new FPL phrasing before it silently degrades
    availability handling.
    """
    rows = (await db.execute(
        select(Player, Team.short_name)
        .join(Team, Team.id == Player.team_id)
        .where(Player.news != "")
        .order_by(Player.web_name)
        .limit(limit)
    )).all()

    out = []
    unparsed = 0
    disagreements = 0

    for p, short in rows:
        parsed = parse_news(p.news)
        multiplier, source, _ = resolve_availability(
            p.status, p.chance_of_playing_this_round, p.news
        )
        if not parsed.parsed:
            unparsed += 1
        disagrees = (
            parsed.chance_percent is not None
            and p.chance_of_playing_this_round != parsed.chance_percent
        )
        if disagrees:
            disagreements += 1

        if only_unparsed and parsed.parsed:
            continue

        out.append({
            "player_id": p.id,
            "name": p.web_name,
            "team": short,
            "status": p.status,
            "chance_field": p.chance_of_playing_this_round,
            "news": p.news,
            "parsed": parsed.as_dict(),
            "availability_used": round(multiplier, 3),
            "availability_source": source,
            "field_disagrees_with_news": disagrees,
        })

    return {
        "total_with_news": len(rows),
        "unparsed": unparsed,
        "parse_rate": round((len(rows) - unparsed) / len(rows), 4) if rows else None,
        "field_disagreements": disagreements,
        "players": out,
    }
