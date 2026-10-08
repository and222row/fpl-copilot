import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from app.config import settings
from app.observability import (
    configure_logging, init_error_tracking, RequestContextMiddleware, request_id_var,
)
from app.rate_limit import limiter
from app.redis_client import close_redis
from app.security import BodySizeLimitMiddleware, run_startup_checks
from app.services.fpl_client import close_client as close_fpl_client
from app.routers import (
    health, fpl, projections, decisions, news, feedback, planner, jobs,
    dream_team, notifications, chips, me, players, billing,
)
from app import scheduler

configure_logging()
# Before the app is built: Sentry instruments FastAPI and Starlette at init.
error_tracking = init_error_tracking()
logger = logging.getLogger("fpl_copilot")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "starting up",
        extra={
            "environment": settings.environment,
            "version": app.version,
            "release": settings.release or None,
            "error_tracking": error_tracking,
        },
    )
    await run_startup_checks()
    if settings.is_production:
        if not error_tracking:
            logger.warning("monitoring: SENTRY_DSN is not set; errors reach the logs only, with no alert")
        if not settings.healthchecks_ping_url:
            logger.warning("monitoring: HEALTHCHECKS_PING_URL is not set; a missed or failed refresh alerts nobody")
    # Background refresh, if enabled. Off by default — see app/scheduler.py.
    scheduler.start()
    yield
    await scheduler.stop()
    # Release pooled connections so a redeploy does not leak them
    await close_redis()
    await close_fpl_client()
    logger.info("shut down cleanly")


app = FastAPI(
    title="FPL Copilot API",
    version="0.9.0",
    description=(
        "AI-powered Fantasy Premier League decision platform. "
        "Deterministic optimisation makes the numerical decision; every "
        "recommendation carries a computed confidence and its evidence."
    ),
    # The schema maps every route, operator endpoints included; no need to
    # publish it from production.
    docs_url=None if settings.is_production else "/api/docs",
    redoc_url=None if settings.is_production else "/api/redoc",
    openapi_url=None if settings.is_production else "/openapi.json",
    lifespan=lifespan,
)

app.state.limiter = limiter

# Starlette makes the LAST middleware added the OUTERMOST. Added here, inner
# to outer: rate limits, body size, CORS, then the security headers below and
# the request context last of all.
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_bytes)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    # Bearer tokens, never cookies, so credentialed CORS is not needed.
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
    expose_headers=["X-Request-ID", "X-Response-Time-ms"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """
    Baseline hardening. This API serves JSON to a separate frontend origin, so
    it should never be framed, sniffed, or leak a referrer.
    """
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    # Responses carry account and squad data; nothing in between should keep them.
    response.headers.setdefault("Cache-Control", "no-store")
    if not settings.is_development:
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
    return response


# Outermost, so its request ID and log line cover every response, including
# ones refused by the middleware inside it (413 body too large, 429 default
# rate limit).
app.add_middleware(RequestContextMiddleware)


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    logger.warning(
        "rate limit exceeded",
        extra={"path": request.url.path, "limit": str(exc.detail)},
    )
    return JSONResponse(
        status_code=429,
        content={
            "detail": "Rate limit exceeded. This endpoint is expensive — "
                      "please slow down.",
            "limit": str(exc.detail),
            "request_id": request_id_var.get(),
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """
    Never leak a stack trace to a client. The request ID ties the opaque
    response back to the full traceback in the logs.
    """
    logger.exception("unhandled error", extra={"path": request.url.path})
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "request_id": request_id_var.get(),
        },
    )


app.include_router(health.router, prefix="/api/v1")
app.include_router(fpl.router, prefix="/api/v1")
app.include_router(projections.router, prefix="/api/v1")
app.include_router(decisions.router, prefix="/api/v1")
app.include_router(news.router, prefix="/api/v1")
app.include_router(feedback.router, prefix="/api/v1")
app.include_router(planner.router, prefix="/api/v1")
app.include_router(jobs.router, prefix="/api/v1")
app.include_router(dream_team.router, prefix="/api/v1")
app.include_router(notifications.router, prefix="/api/v1")
app.include_router(chips.router, prefix="/api/v1")
app.include_router(me.router, prefix="/api/v1")
app.include_router(players.router, prefix="/api/v1")
app.include_router(billing.router, prefix="/api/v1")


@app.get("/")
async def root():
    """Service name and version."""
    return {
        "service": "FPL Copilot API",
        "version": app.version,
        "docs": "/api/docs",
        "status": "running",
    }
