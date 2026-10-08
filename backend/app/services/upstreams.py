"""
Health of the external services the API calls.

Every outbound HTTP client is built with `MonitoredTransport`, which records
each call's outcome per provider. Nothing is probed: FPL is exercised by every
scheduled refresh, Expo by every push run, RevenueCat and Supabase by real
traffic. That costs no requests and reports what users actually hit.

State is per process and resets on restart, which on Render's free tier means
after an idle spell. It answers "what is failing now"; Sentry keeps the
history, because the first call of a sustained failure is logged as an error.
"""
import logging
import time
from dataclasses import asdict, dataclass

import httpx

from app.models.fpl import utcnow

logger = logging.getLogger("fpl_copilot.upstreams")

# Consecutive failures before a provider counts as down. One timeout is
# routine for FPL; three in a row is an outage worth an alert.
DOWN_AFTER = 3


@dataclass
class UpstreamState:
    calls: int = 0
    failures: int = 0
    consecutive_failures: int = 0
    last_ok_at: str | None = None
    last_failure_at: str | None = None
    last_error: str | None = None
    last_status: int | None = None
    last_latency_ms: float | None = None

    @property
    def status(self) -> str:
        if self.calls == 0:
            return "unknown"
        return "down" if self.consecutive_failures >= DOWN_AFTER else "ok"


_states: dict[str, UpstreamState] = {}


def is_failure(status: int) -> bool:
    """5xx and rate limiting are the provider's problem; other 4xx are ours."""
    return status >= 500 or status == 429


def record(provider: str, *, status: int | None, latency_ms: float, error: str | None = None) -> None:
    state = _states.setdefault(provider, UpstreamState())
    state.calls += 1
    state.last_status = status
    state.last_latency_ms = round(latency_ms, 1)
    now = utcnow().isoformat()

    if error is None and status is not None and not is_failure(status):
        if state.consecutive_failures >= DOWN_AFTER:
            logger.warning("upstream recovered", extra={
                "provider": provider, "after_failures": state.consecutive_failures,
            })
        state.consecutive_failures = 0
        state.last_ok_at = now
        return

    state.failures += 1
    state.consecutive_failures += 1
    state.last_failure_at = now
    state.last_error = error or f"HTTP {status}"
    # ERROR once, at the transition, so Sentry gets one event per outage
    # rather than one per call.
    level = logging.ERROR if state.consecutive_failures == DOWN_AFTER else logging.WARNING
    logger.log(level, "upstream call failed", extra={
        "provider": provider,
        "status": status,
        "error": state.last_error,
        "consecutive_failures": state.consecutive_failures,
        "latency_ms": state.last_latency_ms,
    })


def snapshot() -> dict[str, dict]:
    return {
        name: {**asdict(state), "status": state.status}
        for name, state in sorted(_states.items())
    }


def reset() -> None:
    _states.clear()


class MonitoredTransport(httpx.AsyncBaseTransport):
    """Wraps a transport and records every response or transport error."""

    def __init__(self, provider: str, inner: httpx.AsyncBaseTransport | None = None):
        self.provider = provider
        self._inner = inner or httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        started = time.perf_counter()
        try:
            response = await self._inner.handle_async_request(request)
        except Exception as e:
            # The type only: messages can carry the full URL.
            record(self.provider, status=None, error=type(e).__name__,
                   latency_ms=(time.perf_counter() - started) * 1000)
            raise
        record(self.provider, status=response.status_code,
               latency_ms=(time.perf_counter() - started) * 1000)
        return response

    async def aclose(self) -> None:
        await self._inner.aclose()


def monitored(provider: str) -> MonitoredTransport:
    return MonitoredTransport(provider)
