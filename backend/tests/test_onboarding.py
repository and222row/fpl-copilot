"""
Connecting an FPL team (proved by a code in the team name), the free trial it
starts, and the premium gate that trial controls.
"""
from datetime import timedelta
from email.utils import format_datetime

import httpx
import pytest
from fastapi.routing import APIRoute
from sqlalchemy import select

from app.auth import Premium, jwks_cache
from app.config import settings
from app.models.accounts import FplAccount, FplClaim, Trial, User
from app.models.feedback import SquadOverride
from app.models.fpl import utcnow
from app.models.news import TrackedManager
from app.routers.me import CODE_ALPHABET, CODE_LENGTH, MAX_VERIFY_ATTEMPTS
from app.services.entitlements import (
    TRIAL_DAYS, get_entitlement, start_trial_if_eligible,
)
from tests.auth_helpers import USER_A, USER_B, bearer, configure_auth, make_token, seed_account

ORIGINAL_NAME = "Haaland Globetrotters"
PREMIUM_ROUTE = "/api/v1/projections"


@pytest.fixture(autouse=True)
def auth_settings(monkeypatch):
    configure_auth(monkeypatch)
    yield
    jwks_cache.clear()


class FakeFpl:
    def __init__(self):
        self.name = ORIGINAL_NAME
        self.calls: list[int] = []
        self.fresh_calls: list[int] = []
        self.error: Exception | None = None

    def _entry(self, entry_id):
        if self.error:
            raise self.error
        return {"id": entry_id, "name": self.name,
                "player_first_name": "Ada", "player_last_name": "Lovelace"}

    async def cached(self, entry_id):
        self.calls.append(entry_id)
        return self._entry(entry_id)

    async def fresh(self, entry_id):
        self.fresh_calls.append(entry_id)
        return self._entry(entry_id)


@pytest.fixture
def fpl(monkeypatch):
    fake = FakeFpl()
    monkeypatch.setattr("app.routers.me.fetch_manager_info", fake.cached)
    monkeypatch.setattr("app.routers.me.fetch_manager_info_fresh", fake.fresh)
    return fake


def http_error(status: int) -> httpx.HTTPStatusError:
    resp = httpx.Response(status, request=httpx.Request("GET", "https://fpl/entry/1/"))
    return httpx.HTTPStatusError("err", request=resp.request, response=resp)


async def start(client, entry=1234, user=USER_A):
    return await client.post("/api/v1/me/fpl-accounts", json={"fpl_entry_id": entry}, headers=bearer(user))


async def verify(client, entry=1234, user=USER_A):
    return await client.post(f"/api/v1/me/fpl-accounts/{entry}/verify", headers=bearer(user))


async def connect(client, fpl, entry=1234, user=USER_A):
    """The whole happy path: claim, put the code in the name, verify."""
    code = (await start(client, entry, user)).json()["code"]
    fpl.name = f"GT {code}"
    r = await verify(client, entry, user)
    fpl.name = ORIGINAL_NAME
    return r


# ── Starting a connection ────────────────────────────────────────────────────

async def test_start_issues_a_code_without_connecting(client, session, fpl):
    r = await start(client)
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "verification_required"
    assert len(body["code"]) == CODE_LENGTH and set(body["code"]) <= set(CODE_ALPHABET)
    assert body["team_name"] == ORIGINAL_NAME
    assert body["attempts_remaining"] == MAX_VERIFY_ATTEMPTS
    assert (await session.execute(select(FplAccount))).scalars().all() == []
    assert (await session.execute(select(Trial))).scalars().all() == []


async def test_restarting_reuses_the_live_code(client, fpl):
    first = (await start(client)).json()["code"]
    assert (await start(client)).json()["code"] == first
    assert fpl.calls == [1234]


async def test_expired_claim_gets_a_new_code(client, session, fpl):
    await start(client)
    claim = await session.scalar(select(FplClaim))
    claim.expires_at = utcnow() - timedelta(minutes=1)
    claim.attempts = 4
    await session.commit()
    second = (await start(client)).json()
    assert second["status"] == "verification_required"
    assert fpl.calls == [1234, 1234]
    assert second["attempts_remaining"] == MAX_VERIFY_ATTEMPTS


@pytest.mark.parametrize("error,status", [
    (http_error(404), 404), (http_error(500), 502), (httpx.ConnectTimeout("slow"), 503),
])
async def test_start_reports_fpl_failures_distinctly(client, fpl, error, status):
    fpl.error = error
    assert (await start(client)).status_code == status


@pytest.mark.parametrize("body", [
    {"fpl_entry_id": 0}, {"fpl_entry_id": -5}, {"fpl_entry_id": "abc"},
    {"fpl_entry_id": 1234, "user_id": str(USER_B)}, {"fpl_entry_id": 1234, "verified": True}, {},
])
async def test_start_rejects_malformed_bodies(client, fpl, body):
    r = await client.post("/api/v1/me/fpl-accounts", json=body, headers=bearer())
    assert r.status_code == 422
    assert fpl.calls == []


async def test_start_requires_auth(client, fpl):
    r = await client.post("/api/v1/me/fpl-accounts", json={"fpl_entry_id": 1})
    assert r.status_code == 401


async def test_start_does_not_reveal_another_users_ownership(client, session, fpl):
    await seed_account(session, USER_A, 1234)
    r = await start(client, 1234, USER_B)
    assert r.status_code == 202


async def test_one_team_per_account(client, fpl):
    assert (await connect(client, fpl, 1234)).status_code == 201
    assert (await start(client, 5678)).status_code == 409


async def test_start_on_own_team_says_connected(client, fpl):
    await connect(client, fpl)
    r = await start(client)
    assert r.status_code == 200 and r.json()["status"] == "connected"


# ── Verifying ────────────────────────────────────────────────────────────────

async def test_verify_connects_and_starts_the_trial(client, session, fpl):
    code = (await start(client)).json()["code"]
    fpl.name = f"fc {code.lower()[:3]} {code.lower()[3:]}"  # case and spacing forgiven
    r = await verify(client)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "connected"
    assert body["team_name"] == ORIGINAL_NAME, "stored name must not contain the code"
    assert body["trial_started"] is True
    assert body["entitlement"]["status"] == "TRIALING"
    assert body["entitlement"]["premium"] is True
    assert fpl.fresh_calls == [1234], "verification must bypass every cache"

    account = await session.scalar(select(FplAccount))
    assert account.user_id == USER_A and account.fpl_entry_id == 1234
    assert (await session.execute(select(FplClaim))).scalars().all() == []
    assert await session.get(TrackedManager, 1234) is not None


async def test_wrong_name_is_rejected_and_the_attempt_counts(client, session, fpl):
    await start(client)
    fpl.name = "Nothing to see"
    r = await verify(client)
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "CODE_NOT_FOUND"
    assert r.json()["detail"]["attempts_remaining"] == MAX_VERIFY_ATTEMPTS - 1
    assert (await start(client)).json()["attempts_remaining"] == MAX_VERIFY_ATTEMPTS - 1
    assert (await session.execute(select(FplAccount))).scalars().all() == []


async def test_attempts_are_capped(client, fpl):
    await start(client)
    fpl.name = "Nope"
    for _ in range(MAX_VERIFY_ATTEMPTS):
        assert (await verify(client)).status_code == 422
    assert (await verify(client)).status_code == 429
    assert len(fpl.fresh_calls) == MAX_VERIFY_ATTEMPTS


async def test_exhausted_code_is_replaced_on_restart(client, fpl):
    await start(client)
    fpl.name = "Nope"
    for _ in range(MAX_VERIFY_ATTEMPTS):
        await verify(client)
    assert (await verify(client)).status_code == 429
    fresh = (await start(client)).json()
    assert fresh["attempts_remaining"] == MAX_VERIFY_ATTEMPTS
    fpl.name = fresh["code"]
    assert (await verify(client)).status_code == 201


async def test_verify_without_a_claim_is_404(client, fpl):
    assert (await verify(client)).status_code == 404


async def test_verify_expired_claim_is_404(client, session, fpl):
    code = (await start(client)).json()["code"]
    claim = await session.scalar(select(FplClaim))
    claim.expires_at = utcnow() - timedelta(seconds=1)
    await session.commit()
    fpl.name = code
    assert (await verify(client)).status_code == 404


async def test_cannot_verify_using_someone_elses_claim(client, fpl):
    code = (await start(client, 1234, USER_A)).json()["code"]
    fpl.name = code
    assert (await verify(client, 1234, USER_B)).status_code == 404


async def test_proving_control_takes_over_from_a_squatter(client, session, fpl):
    await seed_account(session, USER_A, 1234)
    session.add(SquadOverride(fpl_entry_id=1234, gameweek_id=5, player_ids=[1], bank=0,
                              free_transfers=1, transfers_applied=[]))
    session.add(TrackedManager(fpl_entry_id=1234, telegram_chat_id="999", telegram_enabled=True))
    await session.commit()

    assert (await connect(client, fpl, 1234, USER_B)).status_code == 201

    session.expire_all()
    owners = (await session.execute(select(FplAccount.user_id))).scalars().all()
    assert owners == [USER_B]
    assert (await session.execute(select(SquadOverride))).scalars().all() == []
    tracked = await session.get(TrackedManager, 1234)
    assert tracked.telegram_chat_id is None and tracked.telegram_enabled is False


async def test_an_unproven_claim_does_not_block_the_real_owner(client, fpl):
    await start(client, 1234, USER_A)
    assert (await connect(client, fpl, 1234, USER_B)).status_code == 201
    # A's stale claim is gone too, so A cannot verify later with the old code.
    assert (await verify(client, 1234, USER_A)).status_code == 404


async def test_disconnect_then_another_user_can_connect(client, fpl):
    await connect(client, fpl, 1234, USER_A)
    r = await client.delete("/api/v1/me/fpl-accounts/1234", headers=bearer(USER_A))
    assert r.status_code == 204
    assert (await connect(client, fpl, 1234, USER_B)).status_code == 201


async def test_cannot_disconnect_someone_elses_team(client, fpl):
    await connect(client, fpl, 1234, USER_A)
    r = await client.delete("/api/v1/me/fpl-accounts/1234", headers=bearer(USER_B))
    assert r.status_code == 404


# ── Trial eligibility ────────────────────────────────────────────────────────

async def test_one_trial_per_user(client, fpl):
    first = (await connect(client, fpl, 1234)).json()
    await client.delete("/api/v1/me/fpl-accounts/1234", headers=bearer())
    second = (await connect(client, fpl, 5678)).json()
    assert second["trial_started"] is False
    assert second["entitlement"]["trial_ends_at"] == first["entitlement"]["trial_ends_at"]


async def test_one_trial_per_team(client, fpl):
    await connect(client, fpl, 1234, USER_A)
    await client.delete("/api/v1/me/fpl-accounts/1234", headers=bearer(USER_A))
    r = (await connect(client, fpl, 1234, USER_B)).json()
    assert r["trial_started"] is False
    assert r["entitlement"]["status"] == "NONE"
    assert r["entitlement"]["premium"] is False


async def test_trial_from_a_deleted_account_still_counts(session):
    session.add(User(id=USER_B))
    session.add(Trial(fpl_entry_id=1234, user_id=None,
                      started_at=utcnow() - timedelta(days=40), ends_at=utcnow() - timedelta(days=10)))
    await session.commit()
    assert await start_trial_if_eligible(session, USER_B, 1234) is None


async def test_trial_lasts_thirty_days(client, fpl):
    ent = (await connect(client, fpl)).json()["entitlement"]
    from datetime import datetime
    started = datetime.fromisoformat(ent["trial_started_at"])
    ends = datetime.fromisoformat(ent["trial_ends_at"])
    assert ends - started == timedelta(days=TRIAL_DAYS)


# ── Entitlement ──────────────────────────────────────────────────────────────

async def test_entitlement_is_none_before_any_team(client):
    r = await client.get("/api/v1/me/entitlements", headers=bearer())
    assert r.status_code == 200
    assert r.json() == {
        "premium": False, "status": "NONE", "plan": None, "provider": None,
        "trial_started_at": None, "trial_ends_at": None, "subscription_ends_at": None,
    }


async def test_trial_boundary_uses_the_server_clock(session):
    session.add(User(id=USER_A))
    now = utcnow()
    session.add(Trial(fpl_entry_id=1, user_id=USER_A, started_at=now - timedelta(days=30), ends_at=now))
    await session.commit()
    assert (await get_entitlement(session, USER_A, now - timedelta(seconds=1))).status == "TRIALING"
    assert (await get_entitlement(session, USER_A, now)).status == "EXPIRED"
    assert (await get_entitlement(session, USER_A, now + timedelta(days=1))).premium is False


async def expire_trial(session, user=USER_A):
    trial = await session.scalar(select(Trial).where(Trial.user_id == user))
    trial.ends_at = utcnow() - timedelta(minutes=1)
    await session.commit()


# ── Premium gate ─────────────────────────────────────────────────────────────

EXPECTED_PREMIUM_ROUTES = {
    "/api/v1/decisions/{manager_id}",
    "/api/v1/decisions/{manager_id}/lineup",
    "/api/v1/decisions/{manager_id}/captain",
    "/api/v1/decisions/{manager_id}/transfers",
    "/api/v1/planner/{manager_id}",
    "/api/v1/chips/{manager_id}",
    "/api/v1/dream-team",
    "/api/v1/feedback/{manager_id}/accuracy",
    "/api/v1/feedback/{manager_id}/history",
    "/api/v1/feedback/{manager_id}/pending",
    "/api/v1/feedback/{manager_id}/score",
    "/api/v1/feedback/{manager_id}/score-all",
    "/api/v1/news/alerts/{manager_id}",
    "/api/v1/news/alerts/{manager_id}/generate",
    "/api/v1/news/alerts/{manager_id}/read",
    "/api/v1/players",
    "/api/v1/players/{player_id}",
    "/api/v1/projections",
    "/api/v1/projections/player/{player_id}",
    "/api/v1/projections/team-strength",
}


def test_premium_routes_are_exactly_the_advice():
    from app.main import app
    gated = {r.path for r in app.routes if isinstance(r, APIRoute) and Premium in r.dependencies}
    assert gated == EXPECTED_PREMIUM_ROUTES


async def test_trialing_user_reaches_premium(client, fpl):
    await connect(client, fpl)
    assert (await client.get(PREMIUM_ROUTE, headers=bearer())).status_code != 402


async def test_user_without_trial_hits_the_paywall(client):
    r = await client.get(PREMIUM_ROUTE, headers=bearer())
    assert r.status_code == 402
    assert r.json()["detail"]["code"] == "PREMIUM_REQUIRED"
    assert r.json()["detail"]["entitlement"]["status"] == "NONE"


async def test_expired_trial_loses_premium(client, session, fpl):
    await connect(client, fpl)
    await expire_trial(session)
    r = await client.get(PREMIUM_ROUTE, headers=bearer())
    assert r.status_code == 402
    assert r.json()["detail"]["entitlement"]["status"] == "EXPIRED"
    # Free features keep working.
    assert (await client.get("/api/v1/me", headers=bearer())).status_code == 200


async def test_expired_user_is_blocked_on_their_own_team_advice(client, session, fpl):
    await connect(client, fpl)
    await expire_trial(session)
    r = await client.get("/api/v1/decisions/1234/captain", headers=bearer())
    assert r.status_code == 402


async def test_client_cannot_claim_premium(client, session, fpl):
    await connect(client, fpl)
    await expire_trial(session)
    forged = make_token(
        app_metadata={"premium": True, "subscription_status": "ACTIVE"},
        user_metadata={"premium": True, "plan": "ANNUAL"},
        premium=True,
    )
    r = await client.get(
        f"{PREMIUM_ROUTE}?premium=true",
        headers={**bearer(forged), "X-Premium": "true", "X-Subscription-Status": "ACTIVE"},
    )
    assert r.status_code == 402


async def test_client_clock_cannot_extend_the_trial(client, session, fpl):
    await connect(client, fpl)
    await expire_trial(session)
    past = format_datetime(utcnow() - timedelta(days=20), usegmt=True)
    r = await client.get(PREMIUM_ROUTE, headers={**bearer(), "Date": past})
    assert r.status_code == 402


async def test_anonymous_premium_only_while_auth_optional(client, monkeypatch):
    assert (await client.get(PREMIUM_ROUTE)).status_code != 402
    monkeypatch.setattr(settings, "auth_required", True)
    assert (await client.get(PREMIUM_ROUTE)).status_code == 401
