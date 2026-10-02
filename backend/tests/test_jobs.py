"""
Scheduled-refresh and pre-emptive price alert tests.

Two things matter here beyond "does it run":

  * the price alert must fire on the *crossing*, not on the level. Alerting
    whenever the percentage sits above the line would send the same warning
    every 30 minutes until the price actually moved.
  * the job endpoint must be protected. A full refresh rewrites thousands of
    rows and makes hundreds of upstream calls.
"""
import pytest
from unittest.mock import AsyncMock, patch
from tests.conftest import make_team, make_player, make_gameweek
from app.models.news import (
    PlayerAvailabilitySnapshot, AvailabilityEvent, TrackedManager, Alert,
)
from app.services.change_detection import (
    detect_changes, PRICE_ALERT_PERCENT, PRICE_WARN_PERCENT,
)
from app.services.jobs import register_manager, refresh_everything


# ── Thresholds ───────────────────────────────────────────────────────────────

def test_alert_threshold_is_stricter_than_the_watchlist():
    """An alert should mean "likely tonight", not "drifting upward"."""
    assert PRICE_ALERT_PERCENT > PRICE_WARN_PERCENT


# ── Pre-emptive price detection ──────────────────────────────────────────────

@pytest.fixture
async def one_player(session):
    session.add(make_team(1, "AAA"))
    await session.flush()
    p = make_player(1, team_id=1, web_name="Riser")
    p.price_change_percent = 10.0
    session.add(p)
    await session.commit()
    await detect_changes(session)          # establish the baseline
    return session, p


async def _events(session, player_id: int = 1):
    from sqlalchemy import select
    return (await session.execute(
        select(AvailabilityEvent)
        .where(AvailabilityEvent.player_id == player_id)
        .order_by(AvailabilityEvent.detected_at)
    )).scalars().all()


async def test_baseline_records_the_price_percentage(one_player):
    session, _ = one_player
    snap = await session.get(PlayerAvailabilitySnapshot, 1)
    assert snap.price_change_percent == 10.0


async def test_crossing_the_rise_threshold_fires_an_event(one_player):
    session, player = one_player
    player.price_change_percent = PRICE_ALERT_PERCENT + 5
    await session.commit()

    result = await detect_changes(session)
    assert result["events_detected"] == 1

    event = (await _events(session))[0]
    assert event.event_type == "price_imminent"
    assert event.cause == "price_rise_imminent"
    assert event.materiality >= 0.5
    assert "rise" in event.news_text


async def test_crossing_the_fall_threshold_fires_an_event(one_player):
    session, player = one_player
    player.price_change_percent = -(PRICE_ALERT_PERCENT + 5)
    await session.commit()

    await detect_changes(session)
    event = (await _events(session))[0]
    assert event.cause == "price_fall_imminent"
    assert "fall" in event.news_text


async def test_staying_above_the_threshold_does_not_re_alert(one_player):
    """The anti-spam guarantee: one warning per crossing, not one per sync."""
    session, player = one_player

    player.price_change_percent = 80.0
    await session.commit()
    assert (await detect_changes(session))["events_detected"] == 1

    # Creeps higher over the next few syncs — still the same pending change
    for pct in (85.0, 90.0, 95.0):
        player.price_change_percent = pct
        await session.commit()
        assert (await detect_changes(session))["events_detected"] == 0

    assert len(await _events(session)) == 1


async def test_drifting_below_the_threshold_is_silent(one_player):
    session, player = one_player
    player.price_change_percent = PRICE_ALERT_PERCENT - 10
    await session.commit()
    assert (await detect_changes(session))["events_detected"] == 0


async def test_falling_back_then_crossing_again_re_alerts(one_player):
    """A genuine second approach deserves a second warning."""
    session, player = one_player

    player.price_change_percent = 80.0
    await session.commit()
    await detect_changes(session)

    player.price_change_percent = 20.0      # transfers reversed
    await session.commit()
    await detect_changes(session)

    player.price_change_percent = 80.0      # approaching again
    await session.commit()
    await detect_changes(session)

    imminent = [e for e in await _events(session) if e.event_type == "price_imminent"]
    assert len(imminent) == 2


async def test_an_actual_price_change_takes_precedence(one_player):
    """
    Once the price has moved, report the move — not a prediction of it.
    """
    session, player = one_player
    player.now_cost = player.now_cost + 1
    player.price_change_percent = 90.0
    await session.commit()

    await detect_changes(session)
    types = {e.event_type for e in await _events(session)}
    assert "price_change" in types
    assert "price_imminent" not in types


# ── Manager tracking ─────────────────────────────────────────────────────────

async def test_registering_a_manager_is_idempotent(session):
    await register_manager(session, 123, "First")
    await register_manager(session, 123, "Renamed")

    from sqlalchemy import select, func
    count = (await session.execute(
        select(func.count()).select_from(TrackedManager)
    )).scalar()
    assert count == 1

    row = await session.get(TrackedManager, 123)
    assert row.team_name == "Renamed"
    assert row.alerts_enabled is True


async def test_track_and_untrack_endpoints(client):
    assert (await client.post("/api/v1/jobs/track/999")).status_code == 200

    status = (await client.get("/api/v1/jobs/status")).json()
    assert any(m["fpl_entry_id"] == 999 for m in status["tracked_managers"])

    r = await client.delete("/api/v1/jobs/track/999")
    assert r.json()["alerts_enabled"] is False


async def test_untracking_an_unknown_manager_404s(client):
    assert (await client.delete("/api/v1/jobs/track/424242")).status_code == 404


# ── Job status ───────────────────────────────────────────────────────────────

async def test_status_reports_scheduler_state(client):
    body = (await client.get("/api/v1/jobs/status")).json()
    assert body["scheduler_enabled"] is False        # off in tests
    assert body["scheduler_running"] is False
    assert body["interval_minutes"] > 0
    assert body["hint"] is not None                  # explains how to enable


# ── Token protection ─────────────────────────────────────────────────────────

async def test_refresh_is_open_when_no_token_is_configured(client):
    """Unauthenticated is acceptable locally; the guard activates with a token."""
    with patch("app.services.jobs.sync_bootstrap", AsyncMock(return_value={})), \
         patch("app.services.jobs.sync_fixtures", AsyncMock(return_value=0)), \
         patch("app.services.jobs.detect_changes", AsyncMock(return_value={})), \
         patch("app.services.jobs.rebuild_team_strength", AsyncMock(return_value={})), \
         patch("app.services.jobs.rebuild_projections", AsyncMock(return_value={})):
        r = await client.post("/api/v1/jobs/refresh?include_alerts=false")
    assert r.status_code == 200


async def test_refresh_rejects_a_missing_token_when_one_is_required(client):
    from app.config import settings
    original = settings.job_token
    settings.job_token = "s3cret"
    try:
        r = await client.post("/api/v1/jobs/refresh")
        assert r.status_code == 401
    finally:
        settings.job_token = original


async def test_refresh_rejects_a_wrong_token(client):
    from app.config import settings
    original = settings.job_token
    settings.job_token = "s3cret"
    try:
        r = await client.post(
            "/api/v1/jobs/refresh", headers={"X-Job-Token": "guess"}
        )
        assert r.status_code == 401
    finally:
        settings.job_token = original


async def test_refresh_accepts_the_correct_token(client):
    from app.config import settings
    original = settings.job_token
    settings.job_token = "s3cret"
    try:
        with patch("app.services.jobs.sync_bootstrap", AsyncMock(return_value={})), \
             patch("app.services.jobs.sync_fixtures", AsyncMock(return_value=0)), \
             patch("app.services.jobs.detect_changes", AsyncMock(return_value={})), \
             patch("app.services.jobs.rebuild_team_strength", AsyncMock(return_value={})), \
             patch("app.services.jobs.rebuild_projections", AsyncMock(return_value={})):
            r = await client.post(
                "/api/v1/jobs/refresh?include_alerts=false",
                headers={"X-Job-Token": "s3cret"},
            )
        assert r.status_code == 200
    finally:
        settings.job_token = original


# ── Failure isolation ────────────────────────────────────────────────────────

async def test_one_failing_step_does_not_abort_the_rest(session):
    """A transient FPL blip must not leave the whole dataset stale."""
    with patch("app.services.jobs.sync_bootstrap",
               AsyncMock(side_effect=RuntimeError("FPL timed out"))), \
         patch("app.services.jobs.sync_fixtures", AsyncMock(return_value=380)), \
         patch("app.services.jobs.detect_changes",
               AsyncMock(return_value={"events_detected": 0})), \
         patch("app.services.jobs.rebuild_team_strength",
               AsyncMock(return_value={"teams_updated": 20})), \
         patch("app.services.jobs.rebuild_projections",
               AsyncMock(return_value={"written": 100})):
        result = await refresh_everything(session, include_alerts=False)

    assert result["ok"] is False
    assert any("bootstrap" in e for e in result["errors"])
    # Later stages still ran
    assert result["steps"]["fixtures"] == 380
    assert result["steps"]["projections"]["written"] == 100


async def test_refresh_reports_when_nobody_is_tracked(session):
    with patch("app.services.jobs.sync_bootstrap", AsyncMock(return_value={})), \
         patch("app.services.jobs.sync_fixtures", AsyncMock(return_value=0)), \
         patch("app.services.jobs.detect_changes", AsyncMock(return_value={})), \
         patch("app.services.jobs.rebuild_team_strength", AsyncMock(return_value={})), \
         patch("app.services.jobs.rebuild_projections", AsyncMock(return_value={})):
        result = await refresh_everything(session, include_alerts=True)

    alerts = result["steps"]["alerts"]
    assert alerts["managers"] == 0
    assert "load a squad" in alerts["note"].lower()


async def test_an_unreachable_manager_does_not_break_the_others(session):
    """One bad team ID must not stop alerts for everyone else."""
    session.add(make_gameweek(1, is_current=True))
    await session.flush()
    await register_manager(session, 111)
    await register_manager(session, 222)

    calls = []

    # The job resolves the squad (respecting recorded transfers) rather
    # than reading FPL picks directly.
    async def flaky(db, manager_id, target_gw, picks_gw):
        calls.append(manager_id)
        if manager_id == 111:
            raise RuntimeError("404 from FPL")
        from app.services.squad_state import ResolvedSquad, SOURCE_FPL
        return ResolvedSquad(
            player_ids=[1], bank=0, free_transfers=1,
            source=SOURCE_FPL, picks_gameweek=picks_gw,
        )

    with patch("app.services.jobs.sync_bootstrap", AsyncMock(return_value={})), \
         patch("app.services.jobs.sync_fixtures", AsyncMock(return_value=0)), \
         patch("app.services.jobs.detect_changes", AsyncMock(return_value={})), \
         patch("app.services.jobs.rebuild_team_strength", AsyncMock(return_value={})), \
         patch("app.services.jobs.rebuild_projections", AsyncMock(return_value={})), \
         patch("app.services.jobs.resolve_squad", flaky), \
         patch("app.services.jobs.generate_alerts",
               AsyncMock(return_value={"alerts_created": 1})):
        result = await refresh_everything(session, include_alerts=True)

    alerts = result["steps"]["alerts"]
    assert sorted(calls) == [111, 222]          # both attempted
    assert alerts["alerts_created"] == 1        # the healthy one succeeded
    assert len(alerts["failures"]) == 1


# ── Scheduler wiring ─────────────────────────────────────────────────────────

def test_scheduler_stays_off_unless_enabled():
    from app import scheduler
    from app.config import settings
    assert settings.scheduler_enabled is False
    assert scheduler.start() is False
    assert scheduler.is_running() is False


def test_scheduler_interval_has_a_floor():
    """
    Guard against a misconfiguration hammering the unofficial FPL endpoints.
    A refresh takes over a minute, so a shorter interval would also overlap.
    """
    from app import scheduler
    from app.config import Settings
    s = Settings(refresh_interval_minutes=1)
    effective = max(scheduler.MIN_INTERVAL_SECONDS, s.refresh_interval_minutes * 60)
    assert effective == scheduler.MIN_INTERVAL_SECONDS == 300


async def test_scheduler_survives_a_failing_job():
    """
    One bad run must not kill the loop — the next tick may well succeed.
    Verified by the loop still being alive after the job raised.
    """
    import asyncio
    from unittest.mock import patch
    from app import scheduler
    from app.config import settings

    calls = []

    async def always_fails(db, **kw):
        calls.append(1)
        raise RuntimeError("upstream blew up")

    original = settings.scheduler_enabled
    settings.scheduler_enabled = True
    try:
        with patch.object(scheduler, "refresh_everything", always_fails),              patch.object(scheduler, "STARTUP_DELAY_SECONDS", 0),              patch.object(scheduler, "MIN_INTERVAL_SECONDS", 0),              patch.object(settings, "refresh_interval_minutes", 0):
            assert scheduler.start() is True
            await asyncio.sleep(0.3)
            assert len(calls) > 1, "loop stopped after the first failure"
            assert scheduler.is_running()
            await scheduler.stop()
    finally:
        settings.scheduler_enabled = original
        await scheduler.stop()


# ── Not rewriting the database to record that nothing happened ───────────────

async def test_quiet_refresh_skips_the_expensive_rebuilds(session):
    """
    The bug that suspended the service.

    Rebuilding team strength and projections writes ~3,000 rows to a remote
    Postgres. Doing it 96 times a day when FPL had not moved reached 5 GB of
    egress in 25 days — the entire free allowance — to recompute identical
    numbers.
    """
    from unittest.mock import AsyncMock, patch
    import app.services.jobs as jobs

    with patch.object(jobs, "sync_bootstrap", AsyncMock(return_value={})), \
         patch.object(jobs, "sync_fixtures", AsyncMock(return_value={})), \
         patch.object(jobs, "detect_changes",
                      AsyncMock(return_value={"events_detected": 0, "first_run": False})), \
         patch.object(jobs, "rebuild_team_strength", AsyncMock()) as ts, \
         patch.object(jobs, "rebuild_projections", AsyncMock()) as pr:
        report = await jobs.refresh_everything(session, include_alerts=False)

    ts.assert_not_awaited()
    pr.assert_not_awaited()
    assert "skipped" in report["steps"]["projections"]
    assert report["ok"] is True


async def test_a_real_change_still_rebuilds(session):
    from unittest.mock import AsyncMock, patch
    import app.services.jobs as jobs

    with patch.object(jobs, "sync_bootstrap", AsyncMock(return_value={})), \
         patch.object(jobs, "sync_fixtures", AsyncMock(return_value={})), \
         patch.object(jobs, "detect_changes",
                      AsyncMock(return_value={"events_detected": 3, "first_run": False})), \
         patch.object(jobs, "rebuild_team_strength", AsyncMock()) as ts, \
         patch.object(jobs, "rebuild_projections", AsyncMock()) as pr:
        await jobs.refresh_everything(session, include_alerts=False)

    ts.assert_awaited_once()
    pr.assert_awaited_once()


async def test_the_first_run_always_rebuilds(session):
    """A baseline run reports zero events but has everything still to build."""
    from unittest.mock import AsyncMock, patch
    import app.services.jobs as jobs

    with patch.object(jobs, "sync_bootstrap", AsyncMock(return_value={})), \
         patch.object(jobs, "sync_fixtures", AsyncMock(return_value={})), \
         patch.object(jobs, "detect_changes",
                      AsyncMock(return_value={"events_detected": 0, "first_run": True})), \
         patch.object(jobs, "rebuild_team_strength", AsyncMock()) as ts, \
         patch.object(jobs, "rebuild_projections", AsyncMock()) as pr:
        await jobs.refresh_everything(session, include_alerts=False)

    ts.assert_awaited_once()
    pr.assert_awaited_once()


async def test_force_overrides_the_skip(session):
    from unittest.mock import AsyncMock, patch
    import app.services.jobs as jobs

    with patch.object(jobs, "sync_bootstrap", AsyncMock(return_value={})), \
         patch.object(jobs, "sync_fixtures", AsyncMock(return_value={})), \
         patch.object(jobs, "detect_changes",
                      AsyncMock(return_value={"events_detected": 0, "first_run": False})), \
         patch.object(jobs, "rebuild_team_strength", AsyncMock()) as ts, \
         patch.object(jobs, "rebuild_projections", AsyncMock()) as pr:
        await jobs.refresh_everything(session, include_alerts=False, force=True)

    ts.assert_awaited_once()
    pr.assert_awaited_once()


async def test_a_failed_bootstrap_does_not_trigger_the_skip(session):
    """
    Zero events after a failed bootstrap means nothing was *written*, not that
    nothing moved. Skipping on that evidence would leave the data stale exactly
    when a refresh mattered.
    """
    from unittest.mock import AsyncMock, patch
    import app.services.jobs as jobs

    with patch.object(jobs, "sync_bootstrap", AsyncMock(side_effect=RuntimeError("FPL down"))), \
         patch.object(jobs, "sync_fixtures", AsyncMock(return_value=380)), \
         patch.object(jobs, "detect_changes",
                      AsyncMock(return_value={"events_detected": 0, "first_run": False})), \
         patch.object(jobs, "rebuild_team_strength", AsyncMock()) as ts, \
         patch.object(jobs, "rebuild_projections", AsyncMock()) as pr:
        await jobs.refresh_everything(session, include_alerts=False)

    ts.assert_awaited_once()
    pr.assert_awaited_once()


# ── "Confirmed current" versus "last changed" ────────────────────────────────

async def test_a_clean_refresh_records_that_it_verified(session):
    from unittest.mock import AsyncMock, patch
    import app.services.jobs as jobs
    from app.services.fpl_sync import last_verified

    with patch.object(jobs, "sync_bootstrap", AsyncMock(return_value={})), \
         patch.object(jobs, "sync_fixtures", AsyncMock(return_value={})), \
         patch.object(jobs, "detect_changes",
                      AsyncMock(return_value={"events_detected": 0, "first_run": False})):
        await jobs.refresh_everything(session, include_alerts=False)

    assert await last_verified(session) is not None


async def test_a_failed_refresh_does_not_claim_verification(session):
    """A refresh that errored has confirmed nothing; freshness must not say otherwise."""
    from unittest.mock import AsyncMock, patch
    import app.services.jobs as jobs
    from app.services.fpl_sync import last_verified

    with patch.object(jobs, "sync_bootstrap", AsyncMock(side_effect=RuntimeError("down"))), \
         patch.object(jobs, "sync_fixtures", AsyncMock(return_value={})), \
         patch.object(jobs, "detect_changes", AsyncMock(return_value={"events_detected": 0})), \
         patch.object(jobs, "rebuild_team_strength", AsyncMock()), \
         patch.object(jobs, "rebuild_projections", AsyncMock()):
        await jobs.refresh_everything(session, include_alerts=False)

    assert await last_verified(session) is None
