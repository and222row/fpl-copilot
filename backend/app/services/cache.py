"""
Redis-backed response cache for the FPL API.

Scope is deliberately narrow, and what is *not* cached matters more than what
is.

**Never cache the bootstrap or fixtures.** They are the biggest payloads and so
look like the obvious win, but they are only ever fetched by the sync job, and
the sync exists to notice what changed since last time. `detect_changes`
compares the incoming snapshot against the stored one to find injuries,
suspensions and price moves; serving it a cached snapshot would make it
conclude that nothing moved. The 30-minute cron would then run forever
reporting no news. A cache there does not slow the app down — it silently
switches off the feature the app is for.

What *is* worth caching is the per-request manager endpoints. Loading the
dashboard once fans out into four independent handlers — the squad view, the
squad-state banner, the recommendation and the planner — and each of them
resolves the squad from scratch, so FPL receives four identical requests for
the same picks within a second or two. A short TTL collapses those into one.

The TTL is short on purpose. A manager's picks are immutable once a deadline
has passed, which invites a long TTL, but the same response also carries
`entry_history` — points, overall rank, bank, squad value — and those move
while matches are being played. Ninety seconds is long enough to absorb one
page load's duplicates and short enough that live points never look stuck.

Every operation fails open. Redis is a convenience here and nothing depends on
it; if it is unreachable the loader simply runs, exactly as it did before this
module existed.
"""
import json
import logging
from typing import Any, Awaitable, Callable

from app.config import settings
from app.redis_client import get_redis

logger = logging.getLogger("fpl_copilot")

# Bumping the version abandons every existing entry, which is the cheap way to
# invalidate after changing what a cached payload contains.
PREFIX = "fplc:v1"

# Hit/miss/error tallies for the cache stats endpoint. Process-local and reset
# on restart — indicative, not billing-grade.
STATS: dict[str, int] = {"hits": 0, "misses": 0, "errors": 0, "writes": 0}


def reset_stats() -> None:
    for k in STATS:
        STATS[k] = 0


def key_picks(manager_id: int, gameweek: int) -> str:
    return f"{PREFIX}:picks:{manager_id}:{gameweek}"


def key_entry(manager_id: int) -> str:
    return f"{PREFIX}:entry:{manager_id}"


def key_history(manager_id: int) -> str:
    return f"{PREFIX}:history:{manager_id}"


def key_element_summary(player_id: int) -> str:
    return f"{PREFIX}:element:{player_id}"


async def cached_json(
    key: str,
    loader: Callable[[], Awaitable[Any]],
    ttl_seconds: int | None = None,
) -> Any:
    """
    Return the cached value for `key`, or call `loader` and store its result.

    A Redis failure at any point is logged at debug and then ignored: the
    loader runs and its value is returned uncached. The caller cannot tell the
    difference, which is the point — turning Redis into a hard dependency would
    trade a working app for a faster one.
    """
    if not settings.cache_enabled:
        return await loader()

    ttl = settings.fpl_cache_ttl_seconds if ttl_seconds is None else ttl_seconds

    try:
        redis = await get_redis()
        raw = await redis.get(key)
        if raw is not None:
            STATS["hits"] += 1
            return json.loads(raw)
        STATS["misses"] += 1
    except Exception:
        STATS["errors"] += 1
        logger.debug("cache read failed, falling through", exc_info=True)
        return await loader()

    value = await loader()

    # A write failure must not discard a value the caller already paid for.
    try:
        redis = await get_redis()
        await redis.set(key, json.dumps(value), ex=ttl)
        STATS["writes"] += 1
    except Exception:
        STATS["errors"] += 1
        logger.debug("cache write failed, value still returned", exc_info=True)

    return value


async def invalidate(*keys: str) -> int:
    """
    Drop specific keys. Returns how many Redis reported deleting.

    Used when the app knows a cached response is stale sooner than its TTV —
    recording a manual transfer, for instance.
    """
    if not keys:
        return 0
    try:
        redis = await get_redis()
        return int(await redis.delete(*keys))
    except Exception:
        STATS["errors"] += 1
        logger.debug("cache invalidate failed", exc_info=True)
        return 0


def stats() -> dict[str, Any]:
    total = STATS["hits"] + STATS["misses"]
    return {
        "enabled": settings.cache_enabled,
        "ttl_seconds": settings.fpl_cache_ttl_seconds,
        "prefix": PREFIX,
        **STATS,
        "hit_rate": round(STATS["hits"] / total, 3) if total else None,
        "note": (
            "Only the per-request manager endpoints are cached. The bootstrap "
            "and fixtures are never cached: change detection compares each "
            "sync against the previous one, so a cached snapshot would report "
            "that nothing changed."
        ),
    }
