"""
In-process background scheduler.

A plain asyncio loop rather than APScheduler: the only requirement is "run this
one job on an interval", and a dependency-free version is easier to reason about
and one less thing to install on a free tier.

Off by default. It is only useful where the process stays alive — local
development, or a host that does not idle out. On a free tier that sleeps after
inactivity the loop dies with the process, so an external trigger (QStash
hitting `/api/v1/jobs/refresh`) is the reliable path there.

A second loop sends live match pushes (services/live_alerts.py). It is on in
production by default; see _live_alerts_loop for why it runs in-process.
"""
import asyncio
import logging
from app.config import settings
from app.database import AsyncSessionLocal
from app.services import live_alerts
from app.services.jobs import refresh_everything

logger = logging.getLogger("fpl_copilot")

_task: asyncio.Task | None = None
_live_task: asyncio.Task | None = None

# Wait before the first run so startup is not competing with a heavy refresh.
STARTUP_DELAY_SECONDS = 30

# Floor on the interval. A misconfigured 1-minute loop would hammer the
# unofficial FPL endpoints and risk getting the app blocked; a refresh also
# takes over a minute, so anything shorter would overlap itself.
MIN_INTERVAL_SECONDS = 300


async def _loop() -> None:
    interval = max(MIN_INTERVAL_SECONDS, settings.refresh_interval_minutes * 60)
    logger.info(
        "scheduler started",
        extra={"interval_minutes": interval / 60},
    )
    await asyncio.sleep(STARTUP_DELAY_SECONDS)

    while True:
        try:
            async with AsyncSessionLocal() as db:
                result = await refresh_everything(db)
            logger.info(
                "scheduled refresh finished",
                extra={
                    "ok": result["ok"],
                    "duration_seconds": result["duration_seconds"],
                    "alerts_created": (result["steps"].get("alerts") or {}).get(
                        "alerts_created", 0
                    ),
                },
            )
        except asyncio.CancelledError:
            logger.info("scheduler cancelled")
            raise
        except Exception:
            # Never let one bad run kill the loop — the next tick may succeed.
            logger.exception("scheduled refresh raised")

        await asyncio.sleep(interval)


async def _live_alerts_loop() -> None:
    """
    Goal and full-time pushes. Unlike the refresh, this one runs in-process on
    Render: the QStash keepalive keeps the service awake, and polling through
    QStash every minute of every match would exceed its free daily messages.
    If the service does sleep, the next wake-up restarts the loop, and the
    pushes it missed inside the match window go out then.
    """
    logger.info("live alerts started")
    await asyncio.sleep(STARTUP_DELAY_SECONDS)
    while True:
        delay = live_alerts.IDLE_SECONDS
        try:
            async with AsyncSessionLocal() as db:
                result = await live_alerts.tick(db)
            if result.get("active"):
                delay = live_alerts.POLL_SECONDS
                if result.get("sent"):
                    logger.info("live alerts sent", extra=result)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("live alerts tick raised")
        await asyncio.sleep(delay)


def start() -> bool:
    """Start the loops that are enabled. Returns whether the refresh loop was started."""
    global _task, _live_task
    if settings.live_alerts_on and (_live_task is None or _live_task.done()):
        _live_task = asyncio.create_task(_live_alerts_loop(), name="fpl-live-alerts")
    if not settings.scheduler_enabled:
        logger.info("scheduler disabled (set SCHEDULER_ENABLED=true to turn on)")
        return False
    if _task is not None and not _task.done():
        return True
    _task = asyncio.create_task(_loop(), name="fpl-refresh-scheduler")
    return True


async def stop() -> None:
    global _task, _live_task
    for task in (_task, _live_task):
        if task is None:
            continue
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("scheduler stopped with an error")
    _task = _live_task = None


def is_running() -> bool:
    return _task is not None and not _task.done()
