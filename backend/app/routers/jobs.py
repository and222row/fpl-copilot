import secrets
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.config import settings
from app.rate_limit import limiter, HEAVY
from app.models.news import TrackedManager
from app.services.jobs import refresh_everything, register_manager
from app import scheduler

router = APIRouter(prefix="/jobs", tags=["jobs"])


async def require_job_token(
    x_job_token: str | None = Header(None, alias="X-Job-Token"),
) -> None:
    """
    Guard the refresh endpoint.

    A full refresh rewrites thousands of rows and makes hundreds of upstream
    calls, so it must not be publicly triggerable. When `JOB_TOKEN` is unset the
    endpoint stays open, which is fine locally — but it has to be set before the
    API is exposed.

    Compared with `compare_digest` so the check does not leak length or content
    through timing.
    """
    expected = settings.job_token
    if not expected:
        return
    if not x_job_token or not secrets.compare_digest(x_job_token, expected):
        raise HTTPException(401, "Invalid or missing X-Job-Token header")


@router.post("/refresh", dependencies=[Depends(require_job_token)])
@limiter.limit(HEAVY)
async def refresh(
    request: Request,
    horizon: int = Query(5, ge=1, le=10, description="Gameweeks to project"),
    include_alerts: bool = Query(True),
    db: AsyncSession = Depends(get_db),
):
    """
    Bring everything up to date: sync, detect changes, rebuild, raise alerts.

    The single entry point for scheduled work, so an external cron and the
    in-process scheduler do identical things. Each step is isolated — one
    failing stage is reported and the rest still run.

    Requires `X-Job-Token` when `JOB_TOKEN` is configured.
    """
    return await refresh_everything(
        db, horizon=horizon, include_alerts=include_alerts
    )


@router.get("/status", dependencies=[Depends(require_job_token)])
async def status(db: AsyncSession = Depends(get_db)):
    """Whether background refresh is on, and who it generates alerts for."""
    managers = (await db.execute(
        select(TrackedManager).order_by(TrackedManager.last_seen_at.desc())
    )).scalars().all()

    return {
        "scheduler_enabled": settings.scheduler_enabled,
        "scheduler_running": scheduler.is_running(),
        "interval_minutes": settings.refresh_interval_minutes,
        "job_token_required": bool(settings.job_token),
        "tracked_managers": [
            {
                "fpl_entry_id": m.fpl_entry_id,
                "team_name": m.team_name,
                "alerts_enabled": m.alerts_enabled,
                "last_seen_at": m.last_seen_at,
            }
            for m in managers
        ],
        "hint": (
            "Background refresh is off. Either set SCHEDULER_ENABLED=true (works "
            "while the process stays alive) or point an external cron at "
            "POST /api/v1/jobs/refresh."
        ) if not settings.scheduler_enabled else None,
    }


@router.post("/track/{manager_id}", dependencies=[Depends(require_job_token)])
async def track(
    manager_id: int,
    team_name: str = Query("", description="Optional label"),
    db: AsyncSession = Depends(get_db),
):
    """
    Register a team ID for background alerts.

    Called automatically when a squad is loaded; exposed separately so a manager
    can be added without opening the dashboard.
    """
    await register_manager(db, manager_id, team_name)
    return {"tracked": manager_id, "alerts_enabled": True}


@router.delete("/track/{manager_id}", dependencies=[Depends(require_job_token)])
async def untrack(manager_id: int, db: AsyncSession = Depends(get_db)):
    """Stop generating background alerts for a team ID."""
    row = await db.get(TrackedManager, manager_id)
    if row is None:
        raise HTTPException(404, f"Manager {manager_id} is not tracked")
    row.alerts_enabled = False
    await db.commit()
    return {"tracked": manager_id, "alerts_enabled": False}
