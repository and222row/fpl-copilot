"""
Redis client.

Managed Redis providers close idle connections aggressively — Upstash's free
tier does so within minutes. A cached client that never reconnects therefore
fails the first request after any quiet period with
"connection forcibly closed by the remote host", which shows up as a degraded
health check on an otherwise healthy service.

`health_check_interval` makes redis-py ping a pooled connection before reusing
it if it has been idle, and the retry policy re-establishes a dropped socket
transparently instead of surfacing the error.
"""
import logging
from redis.asyncio import from_url, Redis
from redis.asyncio.retry import Retry
from redis.backoff import ExponentialBackoff
from redis.exceptions import ConnectionError as RedisConnectionError, TimeoutError as RedisTimeoutError
from app.config import settings

logger = logging.getLogger("fpl_copilot")

_redis: Redis | None = None

# Ping a connection that has been idle this long before handing it out.
HEALTH_CHECK_INTERVAL_SECONDS = 30


def _build() -> Redis:
    return from_url(
        settings.redis_url,
        decode_responses=True,
        health_check_interval=HEALTH_CHECK_INTERVAL_SECONDS,
        socket_keepalive=True,
        socket_connect_timeout=5,
        socket_timeout=5,
        retry=Retry(ExponentialBackoff(base=0.1, cap=1.0), retries=3),
        retry_on_error=[RedisConnectionError, RedisTimeoutError],
    )


async def get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = _build()
    return _redis


async def reset_redis() -> None:
    """
    Drop the cached client so the next call builds a fresh connection.

    Used when a command fails despite the retry policy — better to rebuild than
    to keep handing out a pool whose connections are all dead.
    """
    global _redis
    if _redis is not None:
        try:
            await _redis.aclose()
        except Exception:
            logger.debug("redis close failed during reset", exc_info=True)
    _redis = None


async def ping_redis() -> tuple[bool, str]:
    """
    Check reachability, rebuilding the client once if the first attempt fails.

    Returns (ok, detail) rather than raising: a Redis outage should degrade the
    health report, not take down the endpoint.
    """
    try:
        redis = await get_redis()
        await redis.ping()
        return True, "ok"
    except Exception as first_error:
        await reset_redis()
        try:
            redis = await get_redis()
            await redis.ping()
            logger.info("redis reconnected after a dropped connection")
            return True, "ok (reconnected)"
        except Exception as e:
            logger.warning("redis unreachable", extra={"error": str(e)})
            return False, f"error: {e}"


async def close_redis() -> None:
    await reset_redis()
