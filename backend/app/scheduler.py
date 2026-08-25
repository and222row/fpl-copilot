"""
In-process background scheduler.

A plain asyncio loop rather than APScheduler: the only requirement is "run this
one job on an interval", and a dependency-free version is easier to reason about
and one less thing to install on a free tier.

Off by default. It is only useful where the process stays alive — local
development, or a host that does not idle out. On a free tier that sleeps after
inactivity the loop dies with the process, so an external trigger (GitHub
Actions hitting `/api/v1/jobs/refresh`) is the reliable path there.
"""
import asyncio
import logging
from app.config import settings
from app.database import AsyncSessionLocal
from app.services.jobs import refresh_everything

logger = logging.getLogger("fpl_copilot")

_task: asyncio.Task | None = None

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


def start() -> bool:
    """Start the loop if enabled. Returns whether it was started."""
    global _task
    if not settings.scheduler_enabled:
        logger.info("scheduler disabled (set SCHEDULER_ENABLED=true to turn on)")
        return False
    if _task is not None and not _task.done():
        return True
    _task = asyncio.create_task(_loop(), name="fpl-refresh-scheduler")
    return True


async def stop() -> None:
    global _task
    if _task is None:
        return
    _task.cancel()
    try:
        await _task
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("scheduler stopped with an error")
    _task = None


def is_running() -> bool:
    return _task is not None and not _task.done()
