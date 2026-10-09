"""
The scheduled refresh job.

Blueprint §2 promises the product is *proactive* — that the user is told when
something changes rather than having to look. That was not true while every
refresh required a button press: an injury at 9pm went unnoticed until the next
visit.

This module is the single entry point for "bring everything up to date", so
both the in-process scheduler and an external cron trigger identical work.

Step order is not arbitrary — each stage depends on the one before it:

    bootstrap      players, prices, news, scoring rules
    fixtures       results, needed for team strength
    detect         diff against the previous sync -> availability events
    team strength  custom FDR from results so far
    projections    xPts, reads the FDR ratings
    alerts         per tracked manager, from the events above
"""
import logging
import time
from dataclasses import dataclass, field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.news import TrackedManager, utcnow
from app.services.fpl_sync import (
    sync_bootstrap, sync_fixtures, get_active_gameweek,
    get_latest_started_gameweek, get_next_open_gameweek, record_verified,
)
from app.services.change_detection import detect_changes, generate_alerts
from app.services import feedback, job_monitor, notifications, push
from app.services import chips
from app.services.team_strength import rebuild_team_strength
from app.services.projection import rebuild_projections
from app.services.squad_state import resolve_squad

logger = logging.getLogger("fpl_copilot")


@dataclass
class JobReport:
    started_at: str
    duration_seconds: float = 0.0
    steps: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "started_at": self.started_at,
            "duration_seconds": round(self.duration_seconds, 2),
            "steps": self.steps,
            "errors": self.errors,
            "ok": not self.errors,
        }


async def register_manager(
    db: AsyncSession, fpl_entry_id: int, team_name: str = ""
) -> None:
    """
    Remember a team ID so the scheduler knows whose alerts to generate.

    Called whenever a squad is loaded. Without this the background job has no
    idea who is using the app.
    """
    existing = await db.get(TrackedManager, fpl_entry_id)
    if existing is None:
        db.add(TrackedManager(fpl_entry_id=fpl_entry_id, team_name=team_name or ""))
    else:
        existing.last_seen_at = utcnow()
        if team_name:
            existing.team_name = team_name
    await db.commit()


async def refresh_everything(
    db: AsyncSession,
    *,
    horizon: int = 5,
    include_alerts: bool = True,
    force: bool = False,
) -> dict:
    """
    Run the full refresh chain.

    Each step is wrapped: a failure in one stage is recorded and the rest still
    run. A transient FPL blip should not leave the whole dataset stale.
    """
    started_at = utcnow()
    report = JobReport(started_at=started_at.isoformat())
    started = time.perf_counter()
    # Lets Healthchecks.io time the run and flag one that never finishes.
    await job_monitor.heartbeat("start")

    async def step(name: str, coro):
        try:
            report.steps[name] = await coro
        except Exception as e:
            logger.exception("refresh step failed", extra={"step": name})
            report.steps[name] = {"error": str(e)}
            report.errors.append(f"{name}: {e}")

    await step("bootstrap", sync_bootstrap(db))
    await step("fixtures", sync_fixtures(db))
    await step("detect_changes", detect_changes(db))

    # Rebuilding team strength and projections writes ~3,000 rows to a remote
    # Postgres. At 96 refreshes a day that reached 5 GB of egress in 25 days and
    # got the service suspended — while producing identical numbers, because FPL
    # prices move once a day and news a handful of times.
    #
    # detect_changes has just established whether anything actually moved, so
    # use its answer rather than rebuilding on faith. The explicit rebuild
    # endpoints still force the work when it is genuinely wanted.
    detected = report.steps.get("detect_changes") or {}
    nothing_moved = (
        detected.get("events_detected") == 0
        and not detected.get("first_run")
        and not force
        # Only trustworthy if the steps feeding it succeeded. A failed
        # bootstrap also yields zero events — because nothing was written,
        # not because nothing moved — and skipping on that evidence would
        # leave the dataset stale precisely when a refresh mattered most.
        and not report.errors
    )

    if nothing_moved:
        skipped = {"skipped": "no player data changed since the last refresh"}
        report.steps["team_strength"] = skipped
        report.steps["projections"] = skipped
    else:
        await step("team_strength", rebuild_team_strength(db))
        await step("projections", rebuild_projections(db, horizon=horizon))

    # The data is now confirmed current — rebuilt, or checked and found
    # unchanged. Record that separately from row timestamps, which only move
    # when something changes; freshness reads this. Not stamped on any data
    # error, because a failed refresh has confirmed nothing.
    if not report.errors:
        await step("verified", record_verified(db))

    # Grade advice for gameweeks FPL has finished: the track record.
    await step("accuracy", feedback.score_finished(db))

    if include_alerts:
        report.steps["alerts"] = await _alerts_for_tracked(db)
        # Model-free, and the one chip signal nobody spots by eye.
        await step("gameweek_shape", chips.alert_on_shape_changes(db))
        # Push whatever that produced to anyone who opted in. Wrapped in the
        # same step() isolation as everything else: a Telegram outage must not
        # fail a refresh whose actual work already succeeded, and the alerts
        # are saved and visible in the dashboard regardless.
        await step("notifications", notifications.send_pending(db))
        # Same isolation: an Expo outage leaves the alerts in the app and the
        # pushes un-recorded, so the next refresh sends them.
        await step("push", push.send_due(db))

    report.duration_seconds = time.perf_counter() - started
    logger.info(
        "refresh complete",
        extra={
            "duration_seconds": round(report.duration_seconds, 2),
            "errors": len(report.errors),
            "failed_steps": [e.split(":", 1)[0] for e in report.errors],
        },
    )
    await job_monitor.record_run(
        db, "refresh", started_at=started_at,
        duration_seconds=report.duration_seconds, errors=report.errors,
    )
    await job_monitor.heartbeat(
        "fail" if report.errors else "",
        "\n".join(report.errors) or f"ok in {report.duration_seconds:.1f}s",
    )
    return report.as_dict()


async def _alerts_for_tracked(db: AsyncSession) -> dict:
    """Generate alerts for every manager the app has seen."""
    managers = (await db.execute(
        select(TrackedManager).where(TrackedManager.alerts_enabled.is_(True))
    )).scalars().all()

    if not managers:
        return {
            "managers": 0,
            "alerts_created": 0,
            "note": "No managers tracked yet — load a squad to start receiving alerts.",
        }

    started = await get_latest_started_gameweek(db)
    if started is None:
        return {"managers": len(managers), "alerts_created": 0,
                "note": "No gameweek has started, so no squads to check."}

    # Alerts must be about the squad the manager actually holds. Reading FPL
    # picks directly would use the squad locked at the last deadline and warn
    # about players they have already sold.
    target = await get_next_open_gameweek(db)
    target_gw = target.id if target else started.id

    total = 0
    failures = []
    for m in managers:
        try:
            resolved = await resolve_squad(
                db, m.fpl_entry_id, target_gw=target_gw, picks_gw=started.id
            )
            squad_ids = resolved.player_ids
            if not squad_ids:
                continue
            result = await generate_alerts(
                db,
                fpl_entry_id=m.fpl_entry_id,
                squad_player_ids=squad_ids,
                min_materiality=0.3,
            )
            total += result["alerts_created"]
        except Exception as e:
            # One unreachable manager must not abort the rest
            logger.warning(
                "alert generation failed for a manager",
                extra={"fpl_entry_id": m.fpl_entry_id, "error": str(e)},
            )
            failures.append({"fpl_entry_id": m.fpl_entry_id, "error": str(e)})

    return {
        "managers": len(managers),
        "alerts_created": total,
        "failures": failures,
        "picks_gameweek": started.id,
    }
