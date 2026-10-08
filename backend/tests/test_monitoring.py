"""
Monitoring: upstream health, job-run history and heartbeat, billing webhook
signals, the operator endpoint, and what error tracking may send.

The privacy tests matter as much as the alerting ones: an error tracker is a
third party, and the spec forbids sending it tokens or personal data.
"""
import logging
from contextlib import contextmanager
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import select

from app.config import settings
from app.models.billing import BillingEvent
from app.models.fpl import utcnow
from app.models.ops import JobRun
from app.observability import _before_send, init_error_tracking, request_id_var
from app.services import job_monitor, upstreams
from app.services.jobs import refresh_everything
from app.services.upstreams import DOWN_AFTER, MonitoredTransport


@pytest.fixture(autouse=True)
def _fresh_upstreams():
    upstreams.reset()
    yield
    upstreams.reset()


def _client(provider: str, handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=MonitoredTransport(provider, httpx.MockTransport(handler)))


# ── Upstream tracking ────────────────────────────────────────────────────────

async def test_a_successful_call_is_recorded():
    async with _client("fpl", lambda r: httpx.Response(200)) as c:
        await c.get("https://fpl.test/x")
    s = upstreams.snapshot()["fpl"]
    assert (s["calls"], s["failures"], s["status"]) == (1, 0, "ok")
    assert s["last_ok_at"] and s["last_latency_ms"] is not None


async def test_a_client_error_is_not_the_providers_fault():
    """FPL answers 404 for a team that does not exist; that is not an outage."""
    async with _client("fpl", lambda r: httpx.Response(404)) as c:
        await c.get("https://fpl.test/entry/0/")
    assert upstreams.snapshot()["fpl"]["consecutive_failures"] == 0


@pytest.mark.parametrize("status", [500, 503, 429])
async def test_server_errors_and_rate_limits_count_as_failures(status):
    async with _client("expo_push", lambda r: httpx.Response(status)) as c:
        await c.post("https://expo.test/send")
    assert upstreams.snapshot()["expo_push"]["consecutive_failures"] == 1


async def test_a_provider_is_down_after_consecutive_failures_and_alerts_once(caplog):
    caplog.set_level(logging.WARNING, logger="fpl_copilot.upstreams")
    async with _client("revenuecat", lambda r: httpx.Response(503)) as c:
        for _ in range(DOWN_AFTER + 2):
            await c.get("https://rc.test/")
    assert upstreams.snapshot()["revenuecat"]["status"] == "down"
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1                    # one Sentry event per outage, not per call


async def test_recovery_resets_the_streak(caplog):
    caplog.set_level(logging.WARNING, logger="fpl_copilot.upstreams")
    statuses = iter([503] * DOWN_AFTER + [200])
    async with _client("fpl", lambda r: httpx.Response(next(statuses))) as c:
        for _ in range(DOWN_AFTER + 1):
            await c.get("https://fpl.test/")
    assert upstreams.snapshot()["fpl"]["status"] == "ok"
    assert any(r.getMessage() == "upstream recovered" for r in caplog.records)


async def test_a_transport_error_is_recorded_by_type_and_re_raised():
    def boom(request):
        raise httpx.ConnectError("connect failed to https://secret.test/?key=abc")

    async with _client("supabase_auth", boom) as c:
        with pytest.raises(httpx.ConnectError):
            await c.get("https://secret.test/")
    s = upstreams.snapshot()["supabase_auth"]
    assert s["last_error"] == "ConnectError"   # the type only: messages carry URLs
    assert s["last_status"] is None


def test_every_outbound_client_is_monitored():
    """A new client without the transport would be invisible to the ops view."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent / "app"
    for path in root.rglob("*.py"):
        if path.name in {"job_monitor.py", "upstreams.py"}:
            continue  # the heartbeat must not report on itself
        for line in path.read_text(encoding="utf-8").splitlines():
            if "httpx.AsyncClient(" in line and "transport=monitored(" not in line:
                # fpl_client spreads its arguments over several lines
                if path.name == "fpl_client.py":
                    assert 'transport=monitored("fpl")' in path.read_text(encoding="utf-8")
                    continue
                pytest.fail(f"{path.name}: {line.strip()}")


# ── Job runs ─────────────────────────────────────────────────────────────────

@contextmanager
def _refresh_steps(bootstrap=None):
    with patch("app.services.jobs.sync_bootstrap", bootstrap or AsyncMock(return_value={})), \
         patch("app.services.jobs.sync_fixtures", AsyncMock(return_value=0)), \
         patch("app.services.jobs.detect_changes", AsyncMock(return_value={})), \
         patch("app.services.jobs.rebuild_team_strength", AsyncMock(return_value={})), \
         patch("app.services.jobs.rebuild_projections", AsyncMock(return_value={})):
        yield


async def test_a_refresh_records_its_run(session):
    with _refresh_steps():
        await refresh_everything(session, include_alerts=False)
    run = (await session.execute(select(JobRun))).scalar_one()
    assert run.job == "refresh" and run.ok and run.errors == []


async def test_a_failed_refresh_records_its_errors(session):
    with _refresh_steps(AsyncMock(side_effect=RuntimeError("FPL timed out"))):
        await refresh_everything(session, include_alerts=False)
    run = (await session.execute(select(JobRun))).scalar_one()
    assert run.ok is False
    assert run.errors == ["bootstrap: FPL timed out"]


async def test_old_runs_are_pruned(session):
    session.add(JobRun(job="refresh", started_at=utcnow() - timedelta(days=31), ok=True, errors=[]))
    await session.commit()
    await job_monitor.record_run(session, "refresh", started_at=utcnow(), duration_seconds=1, errors=[])
    assert len((await session.execute(select(JobRun))).scalars().all()) == 1


async def test_job_health_reports_a_failure_streak(session):
    now = utcnow()
    for minutes, ok in [(90, True), (60, False), (30, False)]:
        session.add(JobRun(job="refresh", started_at=now - timedelta(minutes=minutes),
                           finished_at=now - timedelta(minutes=minutes), ok=ok, errors=[]))
    await session.commit()
    health = await job_monitor.job_health(session, "refresh", stale_after=timedelta(hours=2))
    assert health["consecutive_failures"] == 2
    assert health["problems"] == ["refresh: last 2 run(s) failed"]


async def test_job_health_flags_silence(session):
    """Nothing failing is not the same as healthy: runs may have stopped."""
    old = utcnow() - timedelta(hours=3)
    session.add(JobRun(job="refresh", started_at=old, finished_at=old, ok=True, errors=[]))
    await session.commit()
    health = await job_monitor.job_health(session, "refresh", stale_after=timedelta(minutes=95))
    assert "last success" in health["problems"][0]


async def test_job_health_with_no_runs(session):
    health = await job_monitor.job_health(session, "refresh", stale_after=timedelta(minutes=95))
    assert health["last_run"] is None
    assert health["problems"] == ["refresh: no successful run recorded"]


# ── Heartbeat ────────────────────────────────────────────────────────────────

def _capture_pings(monkeypatch):
    pings = []

    def handler(request):
        pings.append((request.url.path, request.content.decode()))
        return httpx.Response(200)

    real = httpx.AsyncClient
    monkeypatch.setattr(job_monitor.httpx, "AsyncClient",
                        lambda **kw: real(**{**kw, "transport": httpx.MockTransport(handler)}))
    monkeypatch.setattr(settings, "healthchecks_ping_url", "https://hc-ping.test/uuid-1")
    return pings


async def test_refresh_pings_start_and_success(session, monkeypatch):
    pings = _capture_pings(monkeypatch)
    with _refresh_steps():
        await refresh_everything(session, include_alerts=False)
    assert [p for p, _ in pings] == ["/uuid-1/start", "/uuid-1"]


async def test_failed_refresh_pings_fail_with_the_step(session, monkeypatch):
    pings = _capture_pings(monkeypatch)
    with _refresh_steps(AsyncMock(side_effect=RuntimeError("FPL timed out"))):
        await refresh_everything(session, include_alerts=False)
    assert pings[-1] == ("/uuid-1/fail", "bootstrap: FPL timed out")


async def test_heartbeat_is_off_without_a_url(monkeypatch):
    monkeypatch.setattr(settings, "healthchecks_ping_url", "")
    monkeypatch.setattr(job_monitor.httpx, "AsyncClient", lambda **kw: pytest.fail("pinged"))
    await job_monitor.heartbeat("start")


async def test_heartbeat_failure_never_fails_the_job(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("down")

    real = httpx.AsyncClient
    monkeypatch.setattr(job_monitor.httpx, "AsyncClient",
                        lambda **kw: real(**{**kw, "transport": httpx.MockTransport(handler)}))
    monkeypatch.setattr(settings, "healthchecks_ping_url", "https://hc-ping.test/uuid-1")
    await job_monitor.heartbeat("fail", "x")


# ── Operator endpoint ────────────────────────────────────────────────────────

async def test_ops_is_operator_only(client, monkeypatch):
    monkeypatch.setattr(settings, "job_token", "s3cret")
    assert (await client.get("/api/v1/health/ops")).status_code == 401
    r = await client.get("/api/v1/health/ops", headers={"X-Job-Token": "s3cret"})
    assert r.status_code == 200


async def test_ops_reports_problems(client, session):
    now = utcnow()
    session.add(JobRun(job="refresh", started_at=now, finished_at=now, ok=False, errors=["bootstrap: x"]))
    session.add(BillingEvent(event_id="e1", event_type="RENEWAL", payload={},
                             received_at=now - timedelta(hours=2), error="RevenueCat 503"))
    await session.commit()
    upstreams._states["expo_push"] = upstreams.UpstreamState(calls=3, failures=3, consecutive_failures=3)

    body = (await client.get("/api/v1/health/ops")).json()
    assert body["status"] == "degraded"
    assert "billing: 1 webhook event(s) unprocessed for over an hour" in body["problems"]
    assert "upstream expo_push is down" in body["problems"]
    assert "refresh: last 1 run(s) failed" in body["problems"]
    assert body["billing"]["overdue"][0]["event_type"] == "RENEWAL"


async def test_ops_is_ok_when_healthy(client, session):
    now = utcnow()
    session.add(JobRun(job="refresh", started_at=now, finished_at=now, ok=True, errors=[]))
    session.add(BillingEvent(event_id="e2", event_type="RENEWAL", payload={},
                             received_at=now, processed_at=now))
    await session.commit()
    body = (await client.get("/api/v1/health/ops")).json()
    assert body["status"] == "ok" and body["problems"] == []
    assert body["billing"]["received_24h"] == 1


async def test_public_health_does_not_leak_database_errors(client):
    from app.database import get_db
    from app.main import app

    class Broken:
        async def execute(self, *a, **k):
            raise RuntimeError("password authentication failed for user postgres at db.internal")

    async def broken_db():
        yield Broken()

    original = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = broken_db
    try:
        body = (await client.get("/api/v1/health")).json()
    finally:
        app.dependency_overrides[get_db] = original
    assert body["database"] == "error"
    assert "postgres" not in str(body)


# ── Billing webhook signals ──────────────────────────────────────────────────

async def test_rejected_webhooks_are_counted(client, monkeypatch):
    from app.routers import billing
    monkeypatch.setattr(settings, "revenuecat_webhook_auth", "Bearer right")
    monkeypatch.setattr(billing, "rejections", billing.WebhookRejections())
    r = await client.post("/api/v1/billing/revenuecat/webhook", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401
    assert billing.rejections.as_dict()["since_start"] == 1
    assert billing.rejections.as_dict()["last_reason"] == "authorization"


# ── Error tracking ───────────────────────────────────────────────────────────

def test_error_tracking_is_off_without_a_dsn(monkeypatch):
    monkeypatch.setattr(settings, "sentry_dsn", "")
    assert init_error_tracking() is False


def test_before_send_strips_identity_and_payloads():
    token = request_id_var.set("req-123")
    try:
        event = _before_send({
            "user": {"id": "u1", "email": "a@b.c", "ip_address": "1.2.3.4"},
            "request": {
                "url": "https://api.test/me",
                "data": {"fpl_entry_id": 1},
                "cookies": {"sb": "x"},
                "headers": {"Authorization": "Bearer eyJ...", "User-Agent": "app"},
            },
            "extra": {"apikey": "sb_secret_x", "path": "/me"},
        }, {})
    finally:
        request_id_var.reset(token)
    assert "user" not in event
    assert "data" not in event["request"] and "cookies" not in event["request"]
    assert event["request"]["headers"] == {"Authorization": "***", "User-Agent": "app"}
    assert event["extra"] == {"apikey": "***", "path": "/me"}
    assert event["tags"]["request_id"] == "req-123"


def test_sentry_events_leave_without_secrets(monkeypatch):
    """End to end through the real SDK, with a transport that only records."""
    import sentry_sdk
    from sentry_sdk.transport import Transport

    sent = []

    class Recording(Transport):
        def capture_envelope(self, envelope):
            event = envelope.get_event()
            if event:
                sent.append(event)

    monkeypatch.setattr(settings, "sentry_dsn", "https://public@o0.ingest.sentry.io/0")
    real_init = sentry_sdk.init
    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: real_init(**kw, transport=Recording))
    try:
        assert init_error_tracking() is True
        log = logging.getLogger("fpl_copilot.test")
        # Built at runtime: Sentry sends surrounding source lines as context,
        # so a literal here would show up as code rather than as leaked data.
        secret = "-".join(["tok", str(4096 * 7)])
        email = "@".join(["someone", "example.test"])
        try:
            access_token = secret  # noqa: F841 - a local; locals must not be sent
            raise ValueError("boom")
        except ValueError:
            log.exception("failed", extra={"authorization": f"Bearer {secret}", "email": email})
        sentry_sdk.flush()
    finally:
        sentry_sdk.init(dsn=None)

    assert len(sent) == 1
    text = str(sent[0])
    assert "boom" in text
    assert secret not in text and email not in text
    frames = sent[0]["exception"]["values"][0]["stacktrace"]["frames"]
    assert all("vars" not in f for f in frames)  # no local variables
