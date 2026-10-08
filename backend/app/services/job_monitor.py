"""
Background-job monitoring: run history, and a heartbeat to Healthchecks.io.

Two different failures need two different detectors:

* A run that fails is recorded here and pinged as a failure.
* A run that never happens (the scheduler dropped it, the API was down) leaves
  nothing to record. Only something outside expecting a ping on schedule can
  notice silence, which is what Healthchecks.io's free tier is for.
"""
import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.fpl import utcnow
from app.models.ops import JobRun

logger = logging.getLogger("fpl_copilot.jobs")

RETENTION_DAYS = 30
MAX_ERROR_CHARS = 300
# The refresh is scheduled every 30 minutes. Three missed or failed slots in a
# row is an outage rather than a blip.
REFRESH_STALE_AFTER = timedelta(minutes=95)


def _utc(ts: datetime | None) -> datetime | None:
    if ts is not None and ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


async def record_run(db: AsyncSession, job: str, *, started_at: datetime,
                     duration_seconds: float, errors: list[str]) -> None:
    """Store a run and prune old ones. Never raises: monitoring must not fail the job."""
    run = JobRun(
        job=job,
        started_at=started_at,
        finished_at=utcnow(),
        duration_seconds=round(duration_seconds, 2),
        ok=not errors,
        errors=[e[:MAX_ERROR_CHARS] for e in errors],
    )
    for attempt in range(2):
        try:
            db.add(run)
            await db.execute(delete(JobRun).where(
                JobRun.started_at < utcnow() - timedelta(days=RETENTION_DAYS)
            ))
            await db.commit()
            return
        except Exception:
            # A step that hit a database error leaves the session needing a
            # rollback; clear it and try once more.
            await db.rollback()
            if attempt:
                logger.exception("could not record job run", extra={"job": job})


async def heartbeat(signal: str = "", body: str = "") -> None:
    """
    Ping Healthchecks.io: "start", "" (success) or "fail". Never raises.

    The body is shown in the alert, so it carries step names and short
    messages only.
    """
    if not settings.healthchecks_ping_url:
        return
    url = settings.healthchecks_ping_url.rstrip("/") + (f"/{signal}" if signal else "")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(url, content=body[:10_000].encode())
    except httpx.HTTPError:
        logger.warning("heartbeat ping failed", extra={"signal": signal or "success"})


async def job_health(db: AsyncSession, job: str, *, stale_after: timedelta) -> dict:
    """Last run, last success and the current failure streak for one job."""
    now = utcnow()
    recent = (await db.execute(
        select(JobRun).where(JobRun.job == job).order_by(JobRun.started_at.desc()).limit(50)
    )).scalars().all()
    last_ok = await db.scalar(
        select(JobRun).where(JobRun.job == job, JobRun.ok.is_(True))
        .order_by(JobRun.started_at.desc()).limit(1)
    )

    streak = 0
    for run in recent:
        if run.ok:
            break
        streak += 1

    last_ok_at = _utc(last_ok.finished_at) if last_ok else None
    problems = []
    if last_ok_at is None:
        problems.append(f"{job}: no successful run recorded")
    elif now - last_ok_at > stale_after:
        problems.append(
            f"{job}: last success {round((now - last_ok_at).total_seconds() / 60)} minutes ago"
        )
    if streak:
        problems.append(f"{job}: last {streak} run(s) failed")

    last = recent[0] if recent else None
    return {
        "last_run": {
            "started_at": _utc(last.started_at).isoformat(),
            "duration_seconds": last.duration_seconds,
            "ok": last.ok,
            "errors": last.errors,
        } if last else None,
        "last_success_at": last_ok_at.isoformat() if last_ok_at else None,
        "consecutive_failures": streak,
        "problems": problems,
    }
