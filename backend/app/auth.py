"""
Verification of Supabase Auth access tokens, and the dependencies that enforce
who may call what.

Supabase issues and refreshes tokens; this API never mints one. Each request's
bearer token is verified locally (signature, issuer, audience, expiry) so no
network call to Supabase sits on the request path beyond a cached JWKS fetch.

Known limit: a signed-out session's access token stays valid until it expires,
because verification is stateless. Keep the Supabase JWT expiry short.
"""
import logging
import secrets
import time
import uuid
from dataclasses import dataclass, field

import httpx
import jwt
from fastapi import Depends, Header, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.accounts import DeletedUser, FplAccount, User
from app.models.fpl import utcnow
from app.services.entitlements import get_entitlement

logger = logging.getLogger("fpl_copilot.auth")

ASYMMETRIC_ALGORITHMS = frozenset({"ES256", "RS256"})
JWKS_TTL_SECONDS = 600
# Floor between JWKS fetches, so tokens with random `kid`s cannot turn this API
# into a request amplifier against Supabase.
JWKS_MIN_REFRESH_SECONDS = 30
CLOCK_LEEWAY_SECONDS = 30
LAST_SEEN_WRITE_INTERVAL_SECONDS = 3600

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthUser:
    id: uuid.UUID
    email: str | None = None
    phone: str | None = None
    providers: list[str] = field(default_factory=list)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(401, detail, headers={"WWW-Authenticate": "Bearer"})


class _JwksCache:
    def __init__(self) -> None:
        self.keys: dict[str, jwt.PyJWK] = {}
        self.fetched_at = 0.0
        self.attempted_at = 0.0

    def clear(self) -> None:
        self.__init__()

    async def get(self, kid: str | None) -> jwt.PyJWK | None:
        if not kid:
            return None
        now = time.monotonic()
        stale = now - self.fetched_at > JWKS_TTL_SECONDS
        if (kid not in self.keys or stale) and now - self.attempted_at >= JWKS_MIN_REFRESH_SECONDS:
            await self._refresh(now)
        return self.keys.get(kid)

    async def _refresh(self, now: float) -> None:
        self.attempted_at = now
        url = f"{settings.supabase_issuer}/.well-known/jwks.json"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(url)
                response.raise_for_status()
            jwk_set = jwt.PyJWKSet.from_dict(response.json())
        except (httpx.HTTPError, ValueError, jwt.PyJWTError):
            # Keep serving the keys we already have; a Supabase blip must not
            # log every user out.
            logger.warning("JWKS refresh failed", exc_info=True)
            if not self.keys:
                raise HTTPException(503, "Authentication is temporarily unavailable")
            return
        self.keys = {k.key_id: k for k in jwk_set.keys if k.key_id}
        self.fetched_at = now


jwks_cache = _JwksCache()


async def decode_token(token: str) -> dict:
    """Verify a Supabase access token and return its claims, or raise 401."""
    if not settings.supabase_url:
        raise _unauthorized("Authentication is not configured")

    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError:
        raise _unauthorized("Malformed token")

    # The key is chosen by algorithm family and never by anything else in the
    # token, so a token cannot talk us into verifying HS256 with a public key.
    alg = header.get("alg")
    if alg == "HS256":
        if not settings.supabase_jwt_secret:
            raise _unauthorized("Unsupported token algorithm")
        key = settings.supabase_jwt_secret
    elif alg in ASYMMETRIC_ALGORITHMS:
        jwk = await jwks_cache.get(header.get("kid"))
        if jwk is None or jwk.algorithm_name != alg:
            raise _unauthorized("Unknown signing key")
        key = jwk.key
    else:
        raise _unauthorized("Unsupported token algorithm")

    try:
        # The audience check is what rejects Supabase's public anon and
        # service-role keys: they share the signing key but are not user tokens.
        claims = jwt.decode(
            token,
            key,
            algorithms=[alg],
            audience=settings.supabase_jwt_audience,
            issuer=settings.supabase_issuer,
            leeway=CLOCK_LEEWAY_SECONDS,
            options={"require": ["exp", "iat", "sub", "aud", "iss"]},
        )
    except jwt.ExpiredSignatureError:
        raise _unauthorized("Token expired")
    except jwt.PyJWTError:
        raise _unauthorized("Invalid token")

    if claims.get("is_anonymous") is True:
        raise _unauthorized("Anonymous sessions are not accepted")
    return claims


def _auth_user(claims: dict) -> AuthUser:
    try:
        user_id = uuid.UUID(str(claims["sub"]))
    except ValueError:
        raise _unauthorized("Invalid token")
    app_meta = claims.get("app_metadata") or {}
    providers = app_meta.get("providers") or (
        [app_meta["provider"]] if app_meta.get("provider") else []
    )
    return AuthUser(
        id=user_id,
        email=claims.get("email") or None,
        phone=claims.get("phone") or None,
        providers=list(providers),
    )


async def optional_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthUser | None:
    """The caller if a bearer token was sent; None if not. A bad token is a 401."""
    if credentials is None:
        return None
    user = _auth_user(await decode_token(credentials.credentials))
    # Read by the rate limiter so limits follow the account, not a shared IP.
    request.state.user_id = str(user.id)
    return user


async def _touch_user(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Create the local user row on first sight; refresh last_seen sparingly."""
    row = await db.get(User, user_id)
    now = utcnow()
    if row is None:
        db.add(User(id=user_id, created_at=now, last_seen_at=now))
        try:
            await db.flush()
        except IntegrityError:
            # A concurrent first request created it first.
            await db.rollback()
        return
    last = row.last_seen_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=now.tzinfo)
    if (now - last).total_seconds() > LAST_SEEN_WRITE_INTERVAL_SECONDS:
        row.last_seen_at = now


async def current_user(
    user: AuthUser | None = Depends(optional_user),
    db: AsyncSession = Depends(get_db),
) -> AuthUser:
    """Require a signed-in caller."""
    if user is None:
        raise _unauthorized("Not signed in")
    if await db.get(DeletedUser, user.id) is not None:
        raise _unauthorized("This account has been deleted")
    await _touch_user(db, user.id)
    return user


async def require_manager_access(
    manager_id: int,
    user: AuthUser | None = Depends(optional_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    Gate any route keyed by an FPL team id to the account that connected it.

    Anonymous callers pass only while AUTH_REQUIRED is off (the legacy web
    dashboard has no login). A token, when present, is always enforced.
    """
    if user is None:
        if settings.auth_required:
            raise _unauthorized("Not signed in")
        return
    owned = await db.scalar(
        select(FplAccount.id).where(
            FplAccount.user_id == user.id,
            FplAccount.fpl_entry_id == manager_id,
        )
    )
    if owned is None:
        raise HTTPException(403, "This FPL team is not connected to your account")


async def require_premium(
    user: AuthUser | None = Depends(optional_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    Gate the model's advice to users with a live trial or subscription.

    402 carries the entitlement so the app can show the paywall. Same anonymous
    rule as ownership: while AUTH_REQUIRED is off, dropping the token bypasses
    this, which is why it must be on before launch.
    """
    if user is None:
        if settings.auth_required:
            raise _unauthorized("Not signed in")
        return
    entitlement = await get_entitlement(db, user.id)
    if not entitlement.premium:
        raise HTTPException(402, {
            "code": "PREMIUM_REQUIRED",
            "message": "Your free trial has ended. Subscribe to keep using FPL Copilot.",
            "entitlement": jsonable_encoder(entitlement.as_dict()),
        })


async def require_job_token(
    x_job_token: str | None = Header(None, alias="X-Job-Token"),
) -> None:
    """
    Guard operator-only work: syncs, rebuilds and the scheduled refresh.

    Each one rewrites thousands of rows or fans out to the unofficial FPL API,
    so anyone able to trigger them could get us IP-blocked by FPL or burn the
    database bandwidth allowance. Open without JOB_TOKEN only outside
    production; a production deploy missing it fails closed rather than open.
    compare_digest so timing leaks neither length nor content.
    """
    expected = settings.job_token
    if not expected:
        if settings.is_production:
            raise HTTPException(503, "Operator endpoints are disabled until JOB_TOKEN is set")
        return
    if not x_job_token or not secrets.compare_digest(x_job_token, expected):
        raise HTTPException(401, "Invalid or missing X-Job-Token header")


ManagerAccess = Depends(require_manager_access)
Premium = Depends(require_premium)
JobToken = Depends(require_job_token)
