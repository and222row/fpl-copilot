"""
FPL response cache.

The behaviour worth protecting is not the speed-up. It is that the cache never
becomes load-bearing (Redis going down must change nothing but latency) and
that it never touches the bootstrap, because change detection compares each
sync against the previous one and a cached snapshot would make every gameweek
look uneventful.
"""
import json
import pytest
from unittest.mock import AsyncMock, patch

import app.redis_client as rc
from app.config import settings
from app.services import cache
from app.services import fpl_client


@pytest.fixture(autouse=True)
async def _isolate():
    """
    conftest disables the cache suite-wide so no other test depends on whether
    Redis happens to be running. These tests are about the cache, so they turn
    it back on and supply their own Redis double.
    """
    await rc.reset_redis()
    cache.reset_stats()
    with patch.object(settings, "cache_enabled", True):
        yield
    await rc.reset_redis()
    cache.reset_stats()


def _fake_redis(store: dict | None = None):
    """A Redis double backed by a plain dict, ignoring TTL."""
    data = store if store is not None else {}
    fake = AsyncMock()

    async def _get(key):
        return data.get(key)

    async def _set(key, value, ex=None):
        data[key] = value
        return True

    async def _delete(*keys):
        return sum(1 for k in keys if data.pop(k, None) is not None)

    fake.get = AsyncMock(side_effect=_get)
    fake.set = AsyncMock(side_effect=_set)
    fake.delete = AsyncMock(side_effect=_delete)
    fake._data = data
    return fake


# ── Core behaviour ────────────────────────────────────────────────────────────

async def test_miss_then_hit_calls_the_loader_once():
    fake = _fake_redis()
    calls = []

    async def loader():
        calls.append(1)
        return {"picks": [1, 2, 3]}

    with patch.object(rc, "_build", return_value=fake):
        first = await cache.cached_json("k", loader)
        second = await cache.cached_json("k", loader)

    assert first == second == {"picks": [1, 2, 3]}
    assert len(calls) == 1, "second call should have been served from cache"
    assert cache.STATS["hits"] == 1
    assert cache.STATS["misses"] == 1


async def test_ttl_is_passed_to_redis():
    fake = _fake_redis()

    with patch.object(rc, "_build", return_value=fake):
        await cache.cached_json("k", AsyncMock(return_value={"a": 1}), ttl_seconds=42)

    _, kwargs = fake.set.call_args
    assert kwargs["ex"] == 42


async def test_default_ttl_comes_from_settings():
    fake = _fake_redis()

    with patch.object(rc, "_build", return_value=fake):
        await cache.cached_json("k", AsyncMock(return_value={"a": 1}))

    _, kwargs = fake.set.call_args
    assert kwargs["ex"] == settings.fpl_cache_ttl_seconds


async def test_invalidate_removes_the_entry():
    fake = _fake_redis()

    async def loader():
        return {"v": 1}

    with patch.object(rc, "_build", return_value=fake):
        await cache.cached_json("k", loader)
        removed = await cache.invalidate("k")
        assert removed == 1
        assert await fake.get("k") is None


# ── Failing open ──────────────────────────────────────────────────────────────

async def test_read_failure_falls_through_to_the_loader():
    dead = AsyncMock()
    dead.get = AsyncMock(side_effect=ConnectionError("host unreachable"))
    dead.aclose = AsyncMock()

    with patch.object(rc, "_build", return_value=dead):
        value = await cache.cached_json("k", AsyncMock(return_value={"live": True}))

    assert value == {"live": True}
    assert cache.STATS["errors"] == 1


async def test_write_failure_still_returns_the_value():
    half_dead = AsyncMock()
    half_dead.get = AsyncMock(return_value=None)
    half_dead.set = AsyncMock(side_effect=ConnectionError("write refused"))

    with patch.object(rc, "_build", return_value=half_dead):
        value = await cache.cached_json("k", AsyncMock(return_value={"n": 7}))

    assert value == {"n": 7}, "a failed write must not discard the loaded value"
    assert cache.STATS["errors"] == 1


async def test_total_redis_outage_is_invisible_to_callers():
    """Redis down must cost latency and nothing else."""
    with patch.object(rc, "_build", side_effect=ConnectionError("no route")):
        value = await cache.cached_json("k", AsyncMock(return_value={"ok": 1}))
    assert value == {"ok": 1}


async def test_disabling_the_cache_bypasses_redis_entirely():
    fake = _fake_redis()
    with patch.object(rc, "_build", return_value=fake):
        with patch.object(settings, "cache_enabled", False):
            value = await cache.cached_json("k", AsyncMock(return_value={"x": 1}))
    assert value == {"x": 1}
    fake.get.assert_not_called()
    fake.set.assert_not_called()


# ── What must never be cached ─────────────────────────────────────────────────

async def test_bootstrap_is_never_cached():
    """
    The regression that would silently disable change detection.

    `detect_changes` diffs each sync against the stored snapshot. If the
    bootstrap were served from cache, consecutive syncs would see identical
    data and conclude no player had been injured, suspended or repriced.
    """
    fake = _fake_redis()
    payload = {"elements": [], "teams": [], "events": []}

    with patch.object(rc, "_build", return_value=fake):
        with patch.object(fpl_client, "_get", AsyncMock(return_value=payload)) as get:
            await fpl_client.fetch_bootstrap()
            await fpl_client.fetch_bootstrap()

    assert get.await_count == 2, "bootstrap must hit FPL every time"
    fake.get.assert_not_called()
    fake.set.assert_not_called()


async def test_fixtures_are_never_cached():
    fake = _fake_redis()

    with patch.object(rc, "_build", return_value=fake):
        with patch.object(fpl_client, "_get", AsyncMock(return_value=[])) as get:
            await fpl_client.fetch_fixtures()
            await fpl_client.fetch_fixtures()

    assert get.await_count == 2
    fake.set.assert_not_called()


# ── The endpoints that are cached ─────────────────────────────────────────────

async def test_repeated_picks_lookups_hit_fpl_once():
    """The dashboard fan-out: four handlers, one upstream request."""
    fake = _fake_redis()
    payload = {"picks": [{"element": 1}], "entry_history": {"points": 54}}

    with patch.object(rc, "_build", return_value=fake):
        with patch.object(fpl_client, "_get", AsyncMock(return_value=payload)) as get:
            results = [await fpl_client.fetch_manager_picks(6727534, 1) for _ in range(4)]

    assert get.await_count == 1
    assert all(r == payload for r in results)


async def test_picks_are_keyed_per_manager_and_gameweek():
    fake = _fake_redis()

    with patch.object(rc, "_build", return_value=fake):
        with patch.object(fpl_client, "_get", AsyncMock(return_value={"picks": []})) as get:
            await fpl_client.fetch_manager_picks(1, 1)
            await fpl_client.fetch_manager_picks(1, 2)      # different gameweek
            await fpl_client.fetch_manager_picks(2, 1)      # different manager

    assert get.await_count == 3, "keys must not collide across manager/gameweek"
    assert cache.key_picks(1, 1) in fake._data
    assert cache.key_picks(1, 2) in fake._data
    assert cache.key_picks(2, 1) in fake._data


async def test_manager_info_is_cached():
    fake = _fake_redis()

    with patch.object(rc, "_build", return_value=fake):
        with patch.object(fpl_client, "_get", AsyncMock(return_value={"id": 1})) as get:
            await fpl_client.fetch_manager_info(1)
            await fpl_client.fetch_manager_info(1)

    assert get.await_count == 1
    assert cache.key_entry(1) in fake._data


async def test_cached_payload_round_trips_as_json():
    """Values come back as data, not as a JSON string."""
    fake = _fake_redis()
    payload = {"picks": [{"element": 1, "multiplier": 2}], "active_chip": None}

    with patch.object(rc, "_build", return_value=fake):
        with patch.object(fpl_client, "_get", AsyncMock(return_value=payload)):
            await fpl_client.fetch_manager_picks(9, 3)
            again = await fpl_client.fetch_manager_picks(9, 3)

    assert again == payload
    assert json.loads(fake._data[cache.key_picks(9, 3)]) == payload


# ── Reporting ─────────────────────────────────────────────────────────────────

async def test_stats_reports_hit_rate():
    fake = _fake_redis()

    with patch.object(rc, "_build", return_value=fake):
        await cache.cached_json("k", AsyncMock(return_value=1))   # miss
        await cache.cached_json("k", AsyncMock(return_value=1))   # hit

    s = cache.stats()
    assert s["hits"] == 1 and s["misses"] == 1
    assert s["hit_rate"] == 0.5
    assert "bootstrap" in s["note"], "the note must explain the exclusion"


async def test_stats_hit_rate_is_none_before_any_traffic():
    assert cache.stats()["hit_rate"] is None
