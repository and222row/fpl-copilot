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
import uuid
from types import SimpleNamespace

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException
from fastapi.routing import APIRoute
from sqlalchemy import select

from app.auth import ManagerAccess, decode_token, jwks_cache
from app.config import settings
from app.models.accounts import FplAccount, User
from app.models.feedback import SquadOverride
from app.models.news import TrackedManager
from app.rate_limit import rate_limit_key

SUPABASE_URL = "https://testproj.supabase.co"
ISSUER = f"{SUPABASE_URL}/auth/v1"
SECRET = "test-jwt-secret-that-is-at-least-32-bytes-long"
USER_A = uuid.UUID("11111111-1111-4111-8111-111111111111")
USER_B = uuid.UUID("22222222-2222-4222-8222-222222222222")


@pytest.fixture(autouse=True)
def auth_settings(monkeypatch):
    monkeypatch.setattr(settings, "supabase_url", SUPABASE_URL)
    monkeypatch.setattr(settings, "supabase_jwt_secret", SECRET)
    monkeypatch.setattr(settings, "auth_required", False)
    jwks_cache.clear()
    yield
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


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


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


# ── Connecting an FPL team ───────────────────────────────────────────────────

FPL_ENTRY = {"name": "Haaland Globetrotters", "player_first_name": "Ada", "player_last_name": "Lovelace"}


@pytest.fixture
def fpl_ok(monkeypatch):
    calls = []

    async def fake(entry_id):
        calls.append(entry_id)
        return FPL_ENTRY

    monkeypatch.setattr("app.routers.me.fetch_manager_info", fake)
    return calls


def _fpl_raises(monkeypatch, exc):
    async def fake(entry_id):
        raise exc
    monkeypatch.setattr("app.routers.me.fetch_manager_info", fake)


async def connect(client, entry_id: int, user=USER_A):
    return await client.post(
        "/api/v1/me/fpl-accounts", json={"fpl_entry_id": entry_id}, headers=bearer(make_token(user))
    )


async def test_connect_validates_with_fpl_and_stores(client, session, fpl_ok):
    r = await connect(client, 1234)
    assert r.status_code == 201
    assert r.json()["team_name"] == "Haaland Globetrotters"
    assert r.json()["manager_name"] == "Ada Lovelace"
    assert fpl_ok == [1234]
    tracked = await session.get(TrackedManager, 1234)
    assert tracked is not None and tracked.team_name == "Haaland Globetrotters"


async def test_connect_is_idempotent_for_the_owner(client, fpl_ok):
    assert (await connect(client, 1234)).status_code == 201
    r = await connect(client, 1234)
    assert r.status_code == 200
    assert fpl_ok == [1234], "re-connecting should not hit FPL again"


async def test_team_owned_by_someone_else_cannot_be_connected(client, fpl_ok):
    assert (await connect(client, 1234, USER_A)).status_code == 201
    r = await connect(client, 1234, USER_B)
    assert r.status_code == 409


async def test_only_one_team_per_account(client, fpl_ok):
    assert (await connect(client, 1234)).status_code == 201
    assert (await connect(client, 5678)).status_code == 409


async def test_nonexistent_team_is_404(client, monkeypatch):
    resp = httpx.Response(404, request=httpx.Request("GET", "https://fpl/entry/9/"))
    _fpl_raises(monkeypatch, httpx.HTTPStatusError("nf", request=resp.request, response=resp))
    assert (await connect(client, 9)).status_code == 404


async def test_fpl_unreachable_is_503(client, monkeypatch):
    _fpl_raises(monkeypatch, httpx.ConnectTimeout("slow"))
    assert (await connect(client, 9)).status_code == 503


async def test_fpl_server_error_is_502(client, monkeypatch):
    resp = httpx.Response(500, request=httpx.Request("GET", "https://fpl/entry/9/"))
    _fpl_raises(monkeypatch, httpx.HTTPStatusError("err", request=resp.request, response=resp))
    assert (await connect(client, 9)).status_code == 502


@pytest.mark.parametrize("body", [
    {"fpl_entry_id": 0},
    {"fpl_entry_id": -5},
    {"fpl_entry_id": "abc"},
    {"fpl_entry_id": 1234, "user_id": str(USER_B)},
    {},
])
async def test_connect_rejects_malformed_bodies(client, fpl_ok, body):
    r = await client.post("/api/v1/me/fpl-accounts", json=body, headers=bearer(make_token()))
    assert r.status_code == 422
    assert fpl_ok == []


async def test_connect_requires_auth(client, fpl_ok):
    r = await client.post("/api/v1/me/fpl-accounts", json={"fpl_entry_id": 1})
    assert r.status_code == 401


# ── Disconnecting ────────────────────────────────────────────────────────────

async def test_disconnect_clears_private_state(client, session, fpl_ok):
    await connect(client, 1234)
    session.add(SquadOverride(
        fpl_entry_id=1234, gameweek_id=5, player_ids=[1, 2], bank=0,
        free_transfers=1, transfers_applied=[],
    ))
    tracked = await session.get(TrackedManager, 1234)
    tracked.telegram_chat_id = "999"
    tracked.telegram_enabled = True
    await session.commit()

    r = await client.delete("/api/v1/me/fpl-accounts/1234", headers=bearer(make_token()))
    assert r.status_code == 204

    session.expire_all()
    assert (await session.execute(select(FplAccount))).scalars().all() == []
    assert (await session.execute(select(SquadOverride))).scalars().all() == []
    tracked = await session.get(TrackedManager, 1234)
    assert tracked.telegram_chat_id is None
    assert tracked.telegram_enabled is False
    assert tracked.alerts_enabled is False

    # Now free for someone else.
    assert (await connect(client, 1234, USER_B)).status_code == 201


async def test_cannot_disconnect_someone_elses_team(client, fpl_ok):
    await connect(client, 1234, USER_A)
    r = await client.delete("/api/v1/me/fpl-accounts/1234", headers=bearer(make_token(USER_B)))
    assert r.status_code == 404


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


OWNED_ROUTE = "/api/v1/feedback/1234/accuracy"


async def test_owner_can_reach_their_team(client, fpl_ok):
    await connect(client, 1234, USER_A)
    r = await client.get(OWNED_ROUTE, headers=bearer(make_token(USER_A)))
    assert r.status_code == 200


async def test_other_user_is_forbidden(client, fpl_ok):
    await connect(client, 1234, USER_A)
    r = await client.get(OWNED_ROUTE, headers=bearer(make_token(USER_B)))
    assert r.status_code == 403


async def test_user_cannot_write_another_users_squad_override(client, fpl_ok):
    await connect(client, 1234, USER_A)
    r = await client.post(
        "/api/v1/fpl/manager/1234/squad-state/transfers",
        json={"transfers": [{"out": 1, "in": 2}]},
        headers=bearer(make_token(USER_B)),
    )
    assert r.status_code == 403


async def test_user_cannot_reset_another_users_squad_override(client, fpl_ok):
    await connect(client, 1234, USER_A)
    r = await client.delete(
        "/api/v1/fpl/manager/1234/squad-state", headers=bearer(make_token(USER_B))
    )
    assert r.status_code == 403


async def test_signed_in_user_without_the_team_is_forbidden(client):
    r = await client.get(OWNED_ROUTE, headers=bearer(make_token(USER_B)))
    assert r.status_code == 403


async def test_invalid_token_on_team_route_is_401_even_when_auth_optional(client):
    r = await client.get(OWNED_ROUTE, headers=bearer(make_token(exp_in=-120)))
    assert r.status_code == 401


async def test_anonymous_allowed_only_while_auth_optional(client, monkeypatch):
    assert (await client.get(OWNED_ROUTE)).status_code == 200
    monkeypatch.setattr(settings, "auth_required", True)
    assert (await client.get(OWNED_ROUTE)).status_code == 401


# ── Operational endpoints ────────────────────────────────────────────────────

@pytest.mark.parametrize("method,path", [
    ("GET", "/api/v1/jobs/status"),
    ("POST", "/api/v1/jobs/track/1234"),
    ("DELETE", "/api/v1/jobs/track/1234"),
])
async def test_job_endpoints_need_the_job_token(client, monkeypatch, method, path):
    monkeypatch.setattr(settings, "job_token", "s3cret")
    assert (await client.request(method, path)).status_code == 401


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
