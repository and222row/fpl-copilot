"""
Rate limiting.

Blueprint §18: "Apply per-user and per-IP rate limits to expensive endpoints."

Two distinct risks are being managed:
  * our own cost — an optimiser solve or a full projection rebuild is CPU-heavy
  * our upstream reputation — endpoints that fan out to the FPL API can get us
    blocked if hammered, and the FPL endpoints are unofficial

Limits are per-IP. There is no account system yet; when one arrives, key on
user ID instead so a shared NAT does not throttle everyone behind it.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.config import settings

# Tests and local development would trip limits constantly.
_ENABLED = not settings.is_development and settings.environment != "test"

limiter = Limiter(
    key_func=get_remote_address,
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
