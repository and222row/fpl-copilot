"""
Structured logging and request correlation.

Blueprint §20: "Use structured JSON logs with request_id, job_id, user_id
(non-sensitive internal ID) and provider." Plain-text logs are unsearchable
once anything is running on a schedule, and without a request ID a slow
endpoint cannot be traced through the services it calls.
"""
import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from app.config import settings

# Correlates every log line emitted while handling one request.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

# Never log these, in any casing, even if they appear in a payload.
REDACTED_KEYS = {
    "password", "token", "secret", "api_key", "apikey", "authorization",
    "anthropic_api_key", "api_football_key", "database_url", "redis_url",
    "secret_key", "cookie", "set-cookie",
    "supabase_jwt_secret", "access_token", "refresh_token", "id_token",
    "otp", "phone", "email",
    "revenuecat_secret_key", "revenuecat_webhook_auth", "revenuecat_webhook_signing_secret",
    "supabase_service_key", "expo_access_token", "apikey",
}


def redact(value: object, key: str | None = None) -> object:
    """Recursively strip anything that looks like a credential."""
    if key and key.lower() in REDACTED_KEYS:
        return "***"
    if isinstance(value, dict):
        return {k: redact(v, k) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        rid = request_id_var.get()
        if rid:
            payload["request_id"] = rid

        # Anything passed via logger.info("...", extra={...})
        reserved = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
            "message", "asctime", "taskName",
        }
        for key, val in record.__dict__.items():
            if key not in reserved and not key.startswith("_"):
                payload[key] = redact(val, key)

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


def configure_logging() -> None:
    """
    Install the JSON formatter on the root logger.

    Human-readable output is kept in development — JSON is for aggregation,
    and reading it by eye while building is miserable.
    """
    handler = logging.StreamHandler(sys.stdout)
    if settings.is_development:
        handler.setFormatter(
            logging.Formatter("%(levelname)-8s %(name)s: %(message)s")
        )
    else:
        handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)

    # uvicorn duplicates access logs through its own handlers
    for name in ("uvicorn.access", "uvicorn.error"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True


logger = logging.getLogger("fpl_copilot")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """
    Attach a request ID, log the outcome, and time every request.

    The ID is echoed back as `X-Request-ID` so a user reporting a problem can
    quote something that points at the exact log lines.
    """

    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        token = request_id_var.set(rid)
        started = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "request failed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                },
            )
            request_id_var.reset(token)
            raise

        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        response.headers["X-Request-ID"] = rid
        response.headers["X-Response-Time-ms"] = str(duration_ms)

        # Health checks are polled constantly; logging them buries everything else.
        if request.url.path != "/api/v1/health":
            logger.info(
                "request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": duration_ms,
                },
            )

        request_id_var.reset(token)
        return response
