from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select, func
from app.database import get_db
from app.redis_client import ping_redis
from app.models.fpl import Player, Fixture, Gameweek
from app.models.projections import Projection, TeamStrength, ScoringRules
from app.services import cache
from app.services.fpl_sync import last_verified

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    """Liveness plus dependency reachability."""
    db_status = "ok"

    try:
        await db.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"error: {e}"

    # Rebuilds the client once if the cached connection was dropped, which
    # managed Redis providers do to idle connections.
    redis_ok, redis_status = await ping_redis()

    overall = "ok" if db_status == "ok" and redis_ok else "degraded"
    return {
        "status": overall,
        "database": db_status,
        "redis": redis_status,
    }


@router.get("/health/freshness")
async def data_freshness(db: AsyncSession = Depends(get_db)):
    """
    How stale is every data set we depend on?

    Blueprint §20: "Expose data freshness timestamps in the admin panel and,
    where useful, the user UI." A recommendation built on three-day-old prices
    looks identical to one built on live data unless this is surfaced.
    """
    now = datetime.now(timezone.utc)

    async def newest(column) -> datetime | None:
        return (await db.execute(select(func.max(column)))).scalar()

    async def count(model) -> int:
        return (await db.execute(select(func.count()).select_from(model))).scalar() or 0

    def _utc(ts: datetime | None) -> datetime | None:
        if ts is not None and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts

    verified = _utc(await last_verified(db))

    def age(changed: datetime | None) -> dict:
        """
        Judge freshness by when the data was last *confirmed*, not changed.

        Unchanged rows are no longer rewritten on every refresh, so a table's
        newest `updated_at` stops moving during a quiet spell. Reading that as
        age made three quiet hours look like three stale hours and failed
        refreshes that had succeeded. The effective time is whichever is more
        recent: the last change, or the last refresh that confirmed it.
        """
        changed = _utc(changed)
        if changed is None:
            # Confirmation cannot make an empty table current.
            return {"changed_at": None, "verified_at": None,
                    "age_minutes": None, "status": "missing"}
        effective = max(t for t in (changed, verified) if t is not None)
        minutes = (now - effective).total_seconds() / 60
        if minutes < 60:
            status = "fresh"
        elif minutes < 60 * 24:
            status = "aging"
        else:
            status = "stale"
        return {
            "changed_at": changed.isoformat(),
            "verified_at": verified.isoformat() if verified else None,
            "age_minutes": round(minutes, 1),
            "status": status,
        }

    players = age(await newest(Player.updated_at))
    projections = age(await newest(Projection.updated_at))
    team_strength = age(await newest(TeamStrength.updated_at))
    scoring = age(await newest(ScoringRules.synced_at))

    counts = {
        "players": await count(Player),
        "fixtures": await count(Fixture),
        "gameweeks": await count(Gameweek),
        "projections": await count(Projection),
    }

    # Matches played drives shrinkage; surfacing it explains early-season
    # low confidence without the user having to guess.
    matches_played = (await db.execute(
        select(func.count(func.distinct(Fixture.gameweek_id))).where(
            (Fixture.finished.is_(True)) | (Fixture.finished_provisional.is_(True))
        )
    )).scalar() or 0

    sets = {
        "players": players,
        "projections": projections,
        "team_strength": team_strength,
        "scoring_rules": scoring,
    }
    statuses = [v["status"] for v in sets.values()]
    if "missing" in statuses or "stale" in statuses:
        overall = "stale"
    elif "aging" in statuses:
        overall = "aging"
    else:
        overall = "fresh"

    return {
        "status": overall,
        "checked_at": now.isoformat(),
        # Time since the last refresh that confirmed the data. This, not
        # row age, is what reveals a skipped schedule slot.
        "last_verified": {
            "at": verified.isoformat() if verified else None,
            "age_minutes": round((now - verified).total_seconds() / 60, 1) if verified else None,
        },
        "data_sets": sets,
        "row_counts": counts,
        "matches_played": matches_played,
        "hint": (
            "Run POST /api/v1/fpl/sync/bootstrap then /sync/fixtures, "
            "/news/detect, /projections/rebuild/team-strength and "
            "/projections/rebuild to refresh."
        ) if overall != "fresh" else None,
    }


@router.get("/health/cache")
async def cache_stats():
    """
    Hit rate for the FPL response cache.

    Counters are process-local and reset when the service restarts, so treat
    them as indicative. A low hit rate right after a deploy is normal; a hit
    rate near zero once warm means the TTL is shorter than the gap between
    duplicate requests.
    """
    return cache.stats()
