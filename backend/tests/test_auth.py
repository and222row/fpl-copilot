"""
Token verification, account endpoints and per-team ownership.

The ownership tests are the security boundary for every route keyed by an FPL
team id: a signed-in user must never reach another user's team.
"""
import base64
import hashlib
import hmac
import json
import time
from types import SimpleNamespace

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException
from fastapi.routing import APIRoute

from app.auth import ManagerAccess, decode_token, jwks_cache
from app.config import settings
from app.models.accounts import User
from app.rate_limit import rate_limit_key
from tests.auth_helpers import (
    ISSUER, USER_A, USER_B, bearer, configure_auth, make_token, seed_account,
)


@pytest.fixture(autouse=True)
def auth_settings(monkeypatch):
    configure_auth(monkeypatch)
    yield
    jwks_cache.clear()


async def expect_401(token: str, detail: str | None = None):
    with pytest.raises(HTTPException) as exc:
        await decode_token(token)
    assert exc.value.status_code == 401
    if detail:
        assert exc.value.detail == detail


# ── Token verification ────────────────────────────────────────────────────────

async def test_valid_hs256_token_is_accepted():
    claims = await decode_token(make_token(email="a@example.com"))
    assert claims["sub"] == str(USER_A)
    assert claims["email"] == "a@example.com"


async def test_expired_token_is_rejected():
    await expect_401(make_token(exp_in=-120), "Token expired")


async def test_token_signed_with_another_secret_is_rejected():
    await expect_401(make_token(key="another-secret-that-is-also-32-bytes-long!"), "Invalid token")


async def test_wrong_issuer_is_rejected():
    await expect_401(make_token(iss="https://evil.supabase.co/auth/v1"), "Invalid token")


async def test_anon_key_shaped_token_is_rejected():
    # Supabase's public anon key is signed with the same secret but carries no
    # user audience or subject. Accepting it would make every visitor a user.
    token = make_token(sub=None, aud=None, role="anon")
    await expect_401(token, "Invalid token")


async def test_service_role_audience_is_rejected():
    await expect_401(make_token(aud="service_role"), "Invalid token")


async def test_missing_subject_is_rejected():
    await expect_401(make_token(sub=None), "Invalid token")


async def test_alg_none_is_rejected():
    now = int(time.time())
    token = jwt.encode(
        {"sub": str(USER_A), "aud": "authenticated", "iss": ISSUER, "iat": now, "exp": now + 60},
        key=None, algorithm="none",
    )
    await expect_401(token, "Unsupported token algorithm")


async def test_hs256_rejected_when_no_secret_configured(monkeypatch):
    monkeypatch.setattr(settings, "supabase_jwt_secret", "")
    await expect_401(make_token(), "Unsupported token algorithm")


async def test_anonymous_supabase_session_is_rejected():
    await expect_401(make_token(is_anonymous=True), "Anonymous sessions are not accepted")


async def test_garbage_is_rejected():
    await expect_401("not.a.jwt", "Malformed token")


async def test_auth_unconfigured_rejects_everything(monkeypatch):
    monkeypatch.setattr(settings, "supabase_url", "")
    await expect_401(make_token(), "Authentication is not configured")


# ── Asymmetric (JWKS) keys ───────────────────────────────────────────────────

@pytest.fixture
def ec_key():
    private = ec.generate_private_key(ec.SECP256R1())
    jwk = jwt.algorithms.ECAlgorithm.to_jwk(private.public_key(), as_dict=True)
    jwk.update(kid="kid-1", alg="ES256", use="sig")
    return private, jwk


async def test_es256_token_verified_against_jwks(ec_key, monkeypatch):
    private, jwk = ec_key
    calls = []

    async def fake_refresh(now):
        calls.append(now)
        jwks_cache.keys = {"kid-1": jwt.PyJWK(jwk)}
        jwks_cache.fetched_at = now
        jwks_cache.attempted_at = now

    monkeypatch.setattr(jwks_cache, "_refresh", fake_refresh)
    token = make_token(key=private, alg="ES256", headers={"kid": "kid-1"})
    assert (await decode_token(token))["sub"] == str(USER_A)
    await decode_token(token)
    assert len(calls) == 1, "JWKS should be cached between requests"


async def test_unknown_kid_is_rejected(ec_key, monkeypatch):
    private, jwk = ec_key
    jwks_cache.keys = {"kid-1": jwt.PyJWK(jwk)}
    jwks_cache.fetched_at = jwks_cache.attempted_at = time.monotonic()
    token = make_token(key=private, alg="ES256", headers={"kid": "kid-unknown"})
    await expect_401(token, "Unknown signing key")


async def test_hs256_signed_with_public_key_cannot_impersonate(ec_key, monkeypatch):
    # Classic algorithm-confusion attack: sign HS256 using the published public
    # key as the HMAC secret. Only the configured secret is ever used for HS256.
    private, jwk = ec_key
    monkeypatch.setattr(settings, "supabase_jwt_secret", "")
    pem = private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    jwks_cache.keys = {"kid-1": jwt.PyJWK(jwk)}

    # PyJWT refuses to HMAC-sign with a PEM, so the forged token is built by hand.
    def b64(b: bytes) -> str:
        return base64.urlsafe_b64encode(b).rstrip(b"=").decode()

    header = b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": "kid-1"}).encode())
    now = int(time.time())
    payload = b64(json.dumps({
        "sub": str(USER_A), "aud": "authenticated", "iss": ISSUER, "iat": now, "exp": now + 60,
    }).encode())
    sig = b64(hmac.new(pem, f"{header}.{payload}".encode(), hashlib.sha256).digest())
    token = f"{header}.{payload}.{sig}"
    await expect_401(token, "Unsupported token algorithm")


async def test_jwks_outage_without_cached_keys_is_503(ec_key, monkeypatch):
    private, _ = ec_key

    class Boom:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url): raise httpx.ConnectError("down")

    monkeypatch.setattr("app.auth.httpx.AsyncClient", Boom)
    token = make_token(key=private, alg="ES256", headers={"kid": "kid-1"})
    with pytest.raises(HTTPException) as exc:
        await decode_token(token)
    assert exc.value.status_code == 503


async def test_jwks_outage_keeps_serving_cached_keys(ec_key, monkeypatch):
    private, jwk = ec_key
    jwks_cache.keys = {"kid-1": jwt.PyJWK(jwk)}
    jwks_cache.fetched_at = jwks_cache.attempted_at = 0.0  # stale, refresh will be attempted

    class Boom:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url): raise httpx.ConnectError("down")

    monkeypatch.setattr("app.auth.httpx.AsyncClient", Boom)
    token = make_token(key=private, alg="ES256", headers={"kid": "kid-1"})
    assert (await decode_token(token))["sub"] == str(USER_A)


# ── /me ───────────────────────────────────────────────────────────────────────

async def test_me_requires_a_token(client):
    r = await client.get("/api/v1/me")
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"


async def test_me_with_bad_token_is_401(client):
    r = await client.get("/api/v1/me", headers=bearer("nope"))
    assert r.status_code == 401


async def test_me_provisions_the_user_row(client, session):
    token = make_token(email="a@example.com", app_metadata={"providers": ["google", "apple"]})
    r = await client.get("/api/v1/me", headers=bearer(token))
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == str(USER_A)
    assert body["email"] == "a@example.com"
    assert body["providers"] == ["google", "apple"]
    assert body["fpl_accounts"] == []
    assert await session.get(User, USER_A) is not None


# ── Ownership on every team-keyed route ──────────────────────────────────────

def test_every_manager_route_enforces_ownership():
    """Structural guard: a new /{manager_id} route without the check fails here."""
    from app.main import app

    unguarded = [
        f"{','.join(sorted(r.methods))} {r.path}"
        for r in app.routes
        if isinstance(r, APIRoute)
        and "{manager_id}" in r.path
        and not r.path.startswith("/api/v1/jobs/")
        and ManagerAccess not in r.dependencies
    ]
    assert unguarded == []


# Not premium, so these isolate ownership from entitlement.
OWNED_READ = "/api/v1/fpl/manager/1234/squad-state"


async def test_other_user_is_forbidden(client, session):
    await seed_account(session, USER_A, 1234)
    r = await client.get(OWNED_READ, headers=bearer(USER_B))
    assert r.status_code == 403


async def test_owner_passes_the_ownership_check(client, session):
    await seed_account(session, USER_A, 1234)
    r = await client.get(OWNED_READ, headers=bearer(USER_A))
    assert r.status_code != 403


async def test_user_cannot_write_another_users_squad_override(client, session):
    await seed_account(session, USER_A, 1234)
    r = await client.post(
        "/api/v1/fpl/manager/1234/squad-state/transfers",
        json={"transfers": [{"out": 1, "in": 2}]},
        headers=bearer(USER_B),
    )
    assert r.status_code == 403


async def test_user_cannot_reset_another_users_squad_override(client, session):
    await seed_account(session, USER_A, 1234)
    r = await client.delete("/api/v1/fpl/manager/1234/squad-state", headers=bearer(USER_B))
    assert r.status_code == 403


async def test_user_cannot_rebind_another_users_telegram(client, session):
    await seed_account(session, USER_A, 1234)
    r = await client.post(
        "/api/v1/notifications/1234/telegram/link", headers=bearer(USER_B)
    )
    assert r.status_code == 403


async def test_signed_in_user_without_the_team_is_forbidden(client):
    r = await client.get(OWNED_READ, headers=bearer(USER_B))
    assert r.status_code == 403


async def test_invalid_token_on_team_route_is_401_even_when_auth_optional(client):
    r = await client.get(OWNED_READ, headers=bearer(make_token(exp_in=-120)))
    assert r.status_code == 401


async def test_anonymous_allowed_only_while_auth_optional(client, monkeypatch):
    assert (await client.get("/api/v1/feedback/1234/accuracy")).status_code == 200
    monkeypatch.setattr(settings, "auth_required", True)
    assert (await client.get("/api/v1/feedback/1234/accuracy")).status_code == 401


# ── Operational endpoints ────────────────────────────────────────────────────

@pytest.mark.parametrize("method,path", [
    ("POST", "/api/v1/jobs/refresh"),
    ("GET", "/api/v1/jobs/status"),
    ("POST", "/api/v1/jobs/track/1234"),
    ("DELETE", "/api/v1/jobs/track/1234"),
    ("POST", "/api/v1/fpl/sync/bootstrap"),
    ("POST", "/api/v1/fpl/sync/fixtures"),
    ("POST", "/api/v1/news/detect"),
    ("POST", "/api/v1/projections/rebuild/team-strength"),
    ("POST", "/api/v1/projections/rebuild"),
    ("POST", "/api/v1/projections/backtest/ingest-history"),
])
async def test_operator_endpoints_need_the_job_token(client, monkeypatch, method, path):
    monkeypatch.setattr(settings, "job_token", "s3cret")
    assert (await client.request(method, path)).status_code == 401
    # A signed-in user is not an operator.
    assert (await client.request(method, path, headers=bearer(USER_A))).status_code == 401


# Guarded inside the handler instead: /me and billing sync require a signed-in
# user, and the webhooks check their sender's secret.
SELF_GUARDED_WRITES = {
    "/api/v1/me/fpl-accounts",
    "/api/v1/me/fpl-accounts/{fpl_entry_id}/verify",
    "/api/v1/me/fpl-accounts/{fpl_entry_id}",
    "/api/v1/telegram/webhook",
    "/api/v1/billing/revenuecat/webhook",
    "/api/v1/billing/sync",
    "/api/v1/me",
    "/api/v1/me/devices",
    "/api/v1/me/devices/{token}",
    "/api/v1/me/notifications",
}


def test_every_write_route_is_guarded():
    """A new POST/DELETE that nobody thought to protect fails here."""
    from app.auth import JobToken
    from app.main import app

    unguarded = [
        f"{','.join(sorted(r.methods))} {r.path}"
        for r in app.routes
        if isinstance(r, APIRoute)
        and r.methods & {"POST", "DELETE", "PUT", "PATCH"}
        and JobToken not in r.dependencies
        and ManagerAccess not in r.dependencies
        and r.path not in SELF_GUARDED_WRITES
    ]
    assert unguarded == []


# ── Rate limiting key ────────────────────────────────────────────────────────

def _request(user_id=None, host="10.0.0.1"):
    state = SimpleNamespace()
    if user_id:
        state.user_id = user_id
    return SimpleNamespace(state=state, client=SimpleNamespace(host=host), headers={})


def test_rate_limit_keys_on_user_when_signed_in():
    assert rate_limit_key(_request(str(USER_A))) == f"user:{USER_A}"


def test_rate_limit_falls_back_to_ip_when_anonymous():
    assert rate_limit_key(_request()) == "10.0.0.1"

