"""Request size limits and the production self-check run at startup."""
import json
import logging

from sqlalchemy import text

from app.config import settings
from app.database import engine

logger = logging.getLogger("fpl_copilot.security")


class _TooLarge(Exception):
    pass


class BodySizeLimitMiddleware:
    """
    Refuse request bodies over `max_bytes`, declared or streamed.

    Checking Content-Length alone would let a chunked upload with no length
    stream until memory runs out, so the bytes actually received are counted.
    """

    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        declared = dict(scope.get("headers") or []).get(b"content-length")
        if declared and declared.isdigit() and int(declared) > self.max_bytes:
            return await self._reject(send)

        received = 0
        started = False

        async def counting_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _TooLarge
            return message

        async def tracking_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except _TooLarge:
            if not started:
                await self._reject(send)

    async def _reject(self, send):
        body = json.dumps({"detail": "Request body too large"}).encode()
        await send({
            "type": "http.response.start",
            "status": 413,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
        })
        await send({"type": "http.response.body", "body": body})


def configuration_problems() -> list[str]:
    """Settings that leave a production deploy open or weaker than intended."""
    problems = []
    if not settings.auth_required:
        problems.append(
            "AUTH_REQUIRED is false: anyone can reach team routes and premium "
            "features without signing in"
        )
    if not settings.job_token:
        problems.append("JOB_TOKEN is not set: operator endpoints refuse every request")
    if settings.revenuecat_webhook_auth and not settings.revenuecat_webhook_signing_secret:
        problems.append("REVENUECAT_WEBHOOK_SIGNING_SECRET is not set: the billing webhook refuses deliveries")
    if not settings.expo_access_token:
        problems.append("EXPO_ACCESS_TOKEN is not set: push works, but without enhanced push security")
    if settings.trusted_proxy_hops == 0:
        problems.append("TRUSTED_PROXY_HOPS is 0: behind a proxy every anonymous caller shares one rate limit")
    return problems


async def unprotected_tables() -> list[str] | None:
    """
    Tables in Supabase's exposed `public` schema without row level security.

    Anyone holding the app's publishable key can read and write such a table
    through Supabase's Data API. None when the check cannot run (not Postgres).
    """
    if not settings.database_url.startswith("postgresql"):
        return None
    async with engine.connect() as conn:
        rows = await conn.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND NOT rowsecurity"
        ))
        return sorted(r[0] for r in rows)


async def run_startup_checks() -> None:
    if not settings.is_production:
        return
    for problem in configuration_problems():
        logger.error("security self-check: %s", problem)
    try:
        tables = await unprotected_tables()
    except Exception:
        logger.warning("security self-check: could not inspect row level security", exc_info=True)
        return
    if tables:
        logger.error(
            "security self-check: tables without row level security are exposed through "
            "Supabase's Data API: %s",
            ", ".join(tables),
        )
