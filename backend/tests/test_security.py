"""Hardening from the pre-release security review."""
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, Request

from app.config import settings
from app.rate_limit import client_ip
from app.security import BodySizeLimitMiddleware, configuration_problems
from tests.auth_helpers import configure_auth


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    configure_auth(monkeypatch)


# ── Request body limit ───────────────────────────────────────────────────────

def _echo_app(limit: int) -> FastAPI:
    app = FastAPI()

    @app.post("/echo")
    async def echo(request: Request):
        return {"bytes": len(await request.body())}

    app.add_middleware(BodySizeLimitMiddleware, max_bytes=limit)
    return app


async def _post(app, **kwargs):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        return await c.post("/echo", **kwargs)


async def test_declared_oversize_body_is_refused_unread():
    r = await _post(_echo_app(100), content=b"x" * 101)
    assert r.status_code == 413


async def test_streamed_oversize_body_without_length_is_refused():
    async def chunks():
        for _ in range(10):
            yield b"x" * 50

    r = await _post(_echo_app(100), content=chunks())
    assert r.status_code == 413


async def test_body_under_the_limit_passes():
    r = await _post(_echo_app(100), content=b"x" * 100)
    assert r.json() == {"bytes": 100}


async def test_the_real_app_has_the_limit(client, monkeypatch):
    r = await client.post("/api/v1/me/fpl-accounts", content=b"x" * (settings.max_request_bytes + 1),
                          headers={"Content-Type": "application/json"})
    assert r.status_code == 413


async def test_middleware_rejections_still_carry_request_id_and_headers(client):
    """Request context and security headers wrap every other middleware."""
    r = await client.post("/api/v1/me/fpl-accounts", content=b"x" * (settings.max_request_bytes + 1),
                          headers={"Content-Type": "application/json", "X-Request-ID": "big-body-1"})
    assert r.status_code == 413
    assert r.headers["x-request-id"] == "big-body-1"
    assert r.headers["x-content-type-options"] == "nosniff"


# ── Headers ──────────────────────────────────────────────────────────────────

async def test_responses_are_not_cacheable(client):
    r = await client.get("/api/v1/health")
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize("supplied,kept", [
    ("abc-123_x.y", True),
    ("x" * 65, False),
    ("evil\tvalue", False),
    ("ok but spaces", False),
])
async def test_only_plain_request_ids_are_echoed(client, supplied, kept):
    r = await client.get("/api/v1/health", headers={"X-Request-ID": supplied})
    assert (r.headers["x-request-id"] == supplied) is kept


async def test_cors_does_not_allow_credentials(client):
    r = await client.options("/api/v1/health", headers={
        "Origin": settings.cors_origins_list[0],
        "Access-Control-Request-Method": "GET",
    })
    assert "access-control-allow-credentials" not in r.headers


# ── Client IP behind a proxy ─────────────────────────────────────────────────

def _req(xff=None, peer="10.0.0.1"):
    headers = {"x-forwarded-for": xff} if xff else {}
    return SimpleNamespace(headers=headers, client=SimpleNamespace(host=peer))


def test_without_trusted_proxies_the_socket_peer_is_used(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxy_hops", 0)
    assert client_ip(_req("1.2.3.4", peer="10.0.0.1")) == "10.0.0.1"


def test_one_hop_takes_the_entry_the_proxy_appended(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxy_hops", 1)
    # The client forged "6.6.6.6"; the proxy appended the real address.
    assert client_ip(_req("6.6.6.6, 203.0.113.9")) == "203.0.113.9"
    assert client_ip(_req("203.0.113.9")) == "203.0.113.9"


def test_missing_header_falls_back_to_the_peer(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxy_hops", 1)
    assert client_ip(_req(None, peer="10.0.0.5")) == "10.0.0.5"


# ── Fail closed in production ────────────────────────────────────────────────

async def test_operator_endpoints_fail_closed_in_production_without_a_token(client, monkeypatch):
    monkeypatch.setattr(settings, "job_token", "")
    monkeypatch.setattr(settings, "environment", "production")
    assert (await client.post("/api/v1/jobs/refresh")).status_code == 503
    assert (await client.post("/api/v1/news/detect")).status_code == 503


async def test_operator_endpoints_stay_open_locally_without_a_token(client, monkeypatch):
    monkeypatch.setattr(settings, "job_token", "")
    assert (await client.get("/api/v1/jobs/status")).status_code == 200


async def test_billing_webhook_requires_signing_in_production(client, monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "revenuecat_webhook_auth", "Bearer x")
    monkeypatch.setattr(settings, "revenuecat_webhook_signing_secret", "")
    r = await client.post("/api/v1/billing/revenuecat/webhook", content=b"{}",
                          headers={"Authorization": "Bearer x"})
    assert r.status_code == 503


# ── Production self-check ────────────────────────────────────────────────────

def test_self_check_names_every_weak_setting(monkeypatch):
    for name, value in {
        "auth_required": False, "job_token": "", "revenuecat_webhook_auth": "x",
        "revenuecat_webhook_signing_secret": "", "expo_access_token": "", "trusted_proxy_hops": 0,
    }.items():
        monkeypatch.setattr(settings, name, value)
    problems = " ".join(configuration_problems())
    for setting in ("AUTH_REQUIRED", "JOB_TOKEN", "REVENUECAT_WEBHOOK_SIGNING_SECRET", "EXPO_ACCESS_TOKEN", "TRUSTED_PROXY_HOPS"):
        assert setting in problems


def test_self_check_is_quiet_when_configured(monkeypatch):
    for name, value in {
        "auth_required": True, "job_token": "t", "revenuecat_webhook_auth": "x",
        "revenuecat_webhook_signing_secret": "s", "expo_access_token": "e", "trusted_proxy_hops": 1,
    }.items():
        monkeypatch.setattr(settings, name, value)
    assert configuration_problems() == []
