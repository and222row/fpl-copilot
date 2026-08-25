"""
Resilience tests.

Managed Redis providers drop idle connections — Upstash's free tier does so
within minutes. A cached client that never rebuilds reports the service as
degraded after any quiet period, which is what happened in production before
`ping_redis` gained its retry.
"""
import pytest
from unittest.mock import AsyncMock, patch
import app.redis_client as rc


@pytest.fixture(autouse=True)
async def _clear_cached_client():
    await rc.reset_redis()
    yield
    await rc.reset_redis()


async def test_ping_succeeds_when_redis_is_healthy():
    fake = AsyncMock()
    fake.ping = AsyncMock(return_value=True)
    with patch.object(rc, "_build", return_value=fake):
        ok, detail = await rc.ping_redis()
    assert ok is True
    assert detail == "ok"


async def test_dropped_connection_is_rebuilt_and_reported_as_ok():
    """The exact production failure: first ping fails, a fresh client works."""
    dead = AsyncMock()
    dead.ping = AsyncMock(side_effect=ConnectionError(
        "Error 10054 while writing to socket. An existing connection was "
        "forcibly closed by the remote host."
    ))
    dead.aclose = AsyncMock()

    healthy = AsyncMock()
    healthy.ping = AsyncMock(return_value=True)

    with patch.object(rc, "_build", side_effect=[dead, healthy]):
        ok, detail = await rc.ping_redis()

    assert ok is True
    assert "reconnected" in detail
    dead.aclose.assert_awaited()          # the dead pool was released


async def test_genuine_outage_degrades_rather_than_raises():
    dead = AsyncMock()
    dead.ping = AsyncMock(side_effect=ConnectionError("host unreachable"))
    dead.aclose = AsyncMock()

    with patch.object(rc, "_build", return_value=dead):
        ok, detail = await rc.ping_redis()

    assert ok is False
    assert "error" in detail
    assert "unreachable" in detail


async def test_reset_survives_a_close_that_itself_fails():
    """A broken socket can raise on close; that must not propagate."""
    broken = AsyncMock()
    broken.aclose = AsyncMock(side_effect=OSError("socket already gone"))
    with patch.object(rc, "_build", return_value=broken):
        await rc.get_redis()
        await rc.reset_redis()      # must not raise
    assert rc._redis is None


async def test_client_is_cached_between_calls():
    fake = AsyncMock()
    with patch.object(rc, "_build", return_value=fake) as build:
        await rc.get_redis()
        await rc.get_redis()
    assert build.call_count == 1


async def test_health_endpoint_degrades_without_redis(client):
    """
    Redis is genuinely unreachable in the test environment, so the endpoint
    must still answer 200 with a degraded status rather than erroring.
    """
    r = await client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("ok", "degraded")
    assert body["database"] == "ok"
