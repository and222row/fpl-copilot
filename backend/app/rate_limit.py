"""
Rate limiting.

Blueprint §18: "Apply per-user and per-IP rate limits to expensive endpoints."

Two distinct risks are being managed:
  * our own cost — an optimiser solve or a full projection rebuild is CPU-heavy
  * our upstream reputation — endpoints that fan out to the FPL API can get us
    blocked if hammered, and the FPL endpoints are unofficial

Signed-in requests are limited per account, so mobile users behind one carrier
NAT do not throttle each other. Anonymous requests fall back to per-IP.
"""
from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.config import settings

# Tests and local development would trip limits constantly.
_ENABLED = not settings.is_development and settings.environment != "test"


def client_ip(request: Request) -> str:
    """
    The caller's IP. Behind TRUSTED_PROXY_HOPS proxies it is the entry the
    nearest trusted proxy appended to X-Forwarded-For, counted from the
    right; entries further left are whatever the client chose to send.
    """
    hops = settings.trusted_proxy_hops
    if hops > 0:
        chain = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
        if len(chain) >= hops:
            return chain[-hops]
    return get_remote_address(request)


def rate_limit_key(request: Request) -> str:
    # Set by app.auth.optional_user only after the token has been verified, so a
    # forged token cannot pick someone else's bucket.
    user_id = getattr(request.state, "user_id", None)
    return f"user:{user_id}" if user_id else client_ip(request)


limiter = Limiter(
    key_func=rate_limit_key,
    enabled=_ENABLED,
    default_limits=["240/minute"],
)

# Named tiers, so the intent is visible at the call site.
#   HEAVY    runs a solver or rebuilds thousands of rows
#   UPSTREAM fans out to the unofficial FPL API
#   READ     serves from our own database
HEAVY = "6/minute"
UPSTREAM = "30/minute"
READ = "120/minute"
