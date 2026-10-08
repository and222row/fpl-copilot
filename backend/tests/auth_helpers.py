"""Shared helpers for tests that sign requests with Supabase-shaped tokens."""
import time
import uuid

import jwt

from app.auth import jwks_cache
from app.config import settings
from app.models.accounts import FplAccount, User

SUPABASE_URL = "https://testproj.supabase.co"
ISSUER = f"{SUPABASE_URL}/auth/v1"
SECRET = "test-jwt-secret-that-is-at-least-32-bytes-long"
USER_A = uuid.UUID("11111111-1111-4111-8111-111111111111")
USER_B = uuid.UUID("22222222-2222-4222-8222-222222222222")


def configure_auth(monkeypatch) -> None:
    monkeypatch.setattr(settings, "supabase_url", SUPABASE_URL)
    monkeypatch.setattr(settings, "supabase_jwt_secret", SECRET)
    monkeypatch.setattr(settings, "auth_required", False)
    jwks_cache.clear()


def make_token(
    sub: uuid.UUID | str | None = USER_A,
    *,
    key=SECRET,
    alg: str = "HS256",
    aud: str | None = "authenticated",
    iss: str = ISSUER,
    exp_in: int = 3600,
    headers: dict | None = None,
    **extra,
) -> str:
    now = int(time.time())
    claims = {"iss": iss, "iat": now, "exp": now + exp_in, "role": "authenticated", **extra}
    if sub is not None:
        claims["sub"] = str(sub)
    if aud is not None:
        claims["aud"] = aud
    return jwt.encode(claims, key, algorithm=alg, headers=headers)


def bearer(token_or_user: str | uuid.UUID = USER_A) -> dict:
    token = token_or_user if isinstance(token_or_user, str) else make_token(token_or_user)
    return {"Authorization": f"Bearer {token}"}


async def seed_account(session, user_id: uuid.UUID, fpl_entry_id: int) -> None:
    """A user who has already proved control of a team."""
    if await session.get(User, user_id) is None:
        session.add(User(id=user_id))
    session.add(FplAccount(user_id=user_id, fpl_entry_id=fpl_entry_id, team_name="Seeded"))
    await session.commit()
