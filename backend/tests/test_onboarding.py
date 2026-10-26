"""
Connecting an FPL team (proved by a code in the team name), the free trial it
starts, and the premium gate that trial controls.
"""
from datetime import timedelta
from email.utils import format_datetime

import httpx
import pytest
from tests.routes import api_routes
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
    """Connect a team by ID: instant when nobody holds it."""
    return await client.post("/api/v1/me/fpl-accounts", json={"fpl_entry_id": entry}, headers=bearer(user))


async def claim(client, entry=1234, user=USER_A):
    """Ask for the code that takes a team over from another account."""
    return await client.post(f"/api/v1/me/fpl-accounts/{entry}/claim", headers=bearer(user))


async def verify(client, entry=1234, user=USER_A):
    return await client.post(f"/api/v1/me/fpl-accounts/{entry}/verify", headers=bearer(user))


async def connect(client, fpl, entry=1234, user=USER_A):
    """
    How a user ends up with a trial: connect by ID, then prove the team is
    theirs. A failed connect is returned as it is, so tests expecting a 409
    still see it.
    """
    r = await start(client, entry, user)
    if r.status_code != 201:
        return r
    return await prove(client, fpl, entry, user)


async def prove(client, fpl, entry=1234, user=USER_A):
    """The takeover path: claim, put the code in the name, verify."""
    code = (await claim(client, entry, user)).json()["code"]
    fpl.name = f"GT {code}"
    r = await verify(client, entry, user)
    fpl.name = ORIGINAL_NAME
    return r


# ── Connecting ───────────────────────────────────────────────────────────────

async def test_connecting_a_free_team_is_instant_but_starts_no_trial(client, session, fpl):
    r = await start(client)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "connected"
    assert body["team_name"] == ORIGINAL_NAME
    assert body["verified"] is False
    assert body["trial_started"] is False
    assert body["trial_available"] is True, "the client offers proof to start it"
    assert body["entitlement"]["status"] != "TRIALING"
    account = await session.scalar(select(FplAccount))
    assert account.user_id == USER_A and account.fpl_entry_id == 1234
    assert account.verified_at is None
    assert await session.get(TrackedManager, 1234) is not None


# ── The trial waits for proof ────────────────────────────────────────────────

async def test_proving_your_own_team_starts_the_trial_and_keeps_the_account(client, session, fpl):
    await start(client)
    before = await session.scalar(select(FplAccount))
    r = await prove(client, fpl)
    assert r.status_code == 201, r.text
    assert r.json()["trial_started"] is True
    assert r.json()["verified"] is True

    session.expire_all()
    after = (await session.execute(select(FplAccount))).scalars().all()
    assert [a.id for a in after] == [before.id], "proved in place, not recreated"
    assert after[0].verified_at is not None


async def test_a_stranger_connecting_your_team_cannot_spend_its_trial(client, session, fpl):
    """
    The hole this closes. Eligibility is once per team, and a team ID is public.
    If connecting by ID started the trial, anyone could use up yours first.
    """
    assert (await start(client, 1234, USER_B)).status_code == 201
    assert (await session.execute(select(Trial))).scalars().all() == []

    r = await prove(client, fpl, 1234, USER_A)      # the real owner takes it over
    assert r.status_code == 201, r.text
    assert r.json()["trial_started"] is True


async def test_unproven_connections_never_create_trials(client, session, fpl):
    """Without proof, throwaway accounts and random IDs collect nothing."""
    for user, entry in ((USER_A, 1111), (USER_B, 2222)):
        assert (await start(client, entry, user)).status_code == 201
    assert (await session.execute(select(Trial))).scalars().all() == []


async def test_trial_available_is_false_once_this_user_has_had_one(client, fpl):
    await connect(client, fpl, 1234)
    await client.delete("/api/v1/me/fpl-accounts/1234", headers=bearer(USER_A))
    body = (await start(client, 5678)).json()
    assert body["trial_available"] is False


async def test_claiming_a_proven_team_just_says_connected(client, fpl):
    await connect(client, fpl)
    r = await claim(client)
    assert r.status_code == 200
    assert r.json()["status"] == "connected"


async def test_a_team_connected_elsewhere_is_taken(client, session, fpl):
    """One account per team: a second sign-up with the same team is refused."""
    await seed_account(session, USER_A, 1234)
    r = await start(client, 1234, USER_B)
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "TEAM_TAKEN"
    owners = (await session.execute(select(FplAccount.user_id))).scalars().all()
    assert owners == [USER_A]


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


async def test_one_team_per_account(client, fpl):
    assert (await connect(client, fpl, 1234)).status_code == 201
    assert (await start(client, 5678)).status_code == 409
    assert (await claim(client, 5678)).status_code == 409


async def test_start_on_own_team_says_connected(client, fpl):
    await connect(client, fpl)
    r = await start(client)
    assert r.status_code == 200 and r.json()["status"] == "connected"


# ── Taking a team over: claim, code in the name, verify ──────────────────────

async def test_claim_issues_a_code_without_connecting(client, session, fpl):
    r = await claim(client)
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "verification_required"
    assert len(body["code"]) == CODE_LENGTH and set(body["code"]) <= set(CODE_ALPHABET)
    assert body["team_name"] == ORIGINAL_NAME
    assert body["attempts_remaining"] == MAX_VERIFY_ATTEMPTS
    assert "web browser" in body["instructions"] and "Team Details" in body["instructions"]
    assert (await session.execute(select(FplAccount))).scalars().all() == []
    assert (await session.execute(select(Trial))).scalars().all() == []


async def test_reclaiming_reuses_the_live_code(client, fpl):
    first = (await claim(client)).json()["code"]
    assert (await claim(client)).json()["code"] == first
    assert fpl.calls == [1234]


async def test_expired_claim_gets_a_new_code(client, session, fpl):
    await claim(client)
    row = await session.scalar(select(FplClaim))
    row.expires_at = utcnow() - timedelta(minutes=1)
    row.attempts = 4
    await session.commit()
    second = (await claim(client)).json()
    assert second["status"] == "verification_required"
    assert fpl.calls == [1234, 1234]
    assert second["attempts_remaining"] == MAX_VERIFY_ATTEMPTS


async def test_verify_takes_the_team_over_and_keeps_the_stored_name_clean(client, session, fpl):
    await seed_account(session, USER_A, 1234)
    code = (await claim(client, 1234, USER_B)).json()["code"]
    fpl.name = f"fc {code.lower()[:3]} {code.lower()[3:]}"  # case and spacing forgiven
    r = await verify(client, 1234, USER_B)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "connected"
    assert body["team_name"] == ORIGINAL_NAME, "stored name must not contain the code"
    assert fpl.fresh_calls == [1234], "verification must bypass every cache"
    assert (await session.execute(select(FplClaim))).scalars().all() == []


async def test_wrong_name_is_rejected_and_the_attempt_counts(client, session, fpl):
    await claim(client)
    fpl.name = "Nothing to see"
    r = await verify(client)
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "CODE_NOT_FOUND"
    assert r.json()["detail"]["attempts_remaining"] == MAX_VERIFY_ATTEMPTS - 1
    assert (await claim(client)).json()["attempts_remaining"] == MAX_VERIFY_ATTEMPTS - 1
    assert (await session.execute(select(FplAccount))).scalars().all() == []


async def test_attempts_are_capped(client, fpl):
    await claim(client)
    fpl.name = "Nope"
    for _ in range(MAX_VERIFY_ATTEMPTS):
        assert (await verify(client)).status_code == 422
    assert (await verify(client)).status_code == 429
    assert len(fpl.fresh_calls) == MAX_VERIFY_ATTEMPTS


async def test_exhausted_code_is_replaced_on_reclaim(client, fpl):
    await claim(client)
    fpl.name = "Nope"
    for _ in range(MAX_VERIFY_ATTEMPTS):
        await verify(client)
    assert (await verify(client)).status_code == 429
    fresh = (await claim(client)).json()
    assert fresh["attempts_remaining"] == MAX_VERIFY_ATTEMPTS
    fpl.name = fresh["code"]
    assert (await verify(client)).status_code == 201


async def test_verify_without_a_claim_is_404(client, fpl):
    assert (await verify(client)).status_code == 404


async def test_verify_expired_claim_is_404(client, session, fpl):
    code = (await claim(client)).json()["code"]
    row = await session.scalar(select(FplClaim))
    row.expires_at = utcnow() - timedelta(seconds=1)
    await session.commit()
    fpl.name = code
    assert (await verify(client)).status_code == 404


async def test_cannot_verify_using_someone_elses_claim(client, fpl):
    code = (await claim(client, 1234, USER_A)).json()["code"]
    fpl.name = code
    assert (await verify(client, 1234, USER_B)).status_code == 404


async def test_proving_control_takes_over_from_a_squatter(client, session, fpl):
    await seed_account(session, USER_A, 1234)
    session.add(SquadOverride(fpl_entry_id=1234, gameweek_id=5, player_ids=[1], bank=0,
                              free_transfers=1, transfers_applied=[]))
    session.add(TrackedManager(fpl_entry_id=1234, telegram_chat_id="999", telegram_enabled=True))
    await session.commit()

    assert (await prove(client, fpl, 1234, USER_B)).status_code == 201

    session.expire_all()
    owners = (await session.execute(select(FplAccount.user_id))).scalars().all()
    assert owners == [USER_B]
    assert (await session.execute(select(SquadOverride))).scalars().all() == []
    tracked = await session.get(TrackedManager, 1234)
    assert tracked.telegram_chat_id is None and tracked.telegram_enabled is False


async def test_an_old_claim_cannot_take_a_team_back_without_the_code(client, fpl):
    await claim(client, 1234, USER_A)
    # B connects by ID only; proving would clear A's claim and test nothing.
    assert (await start(client, 1234, USER_B)).status_code == 201
    fpl.name = "anything"
    assert (await verify(client, 1234, USER_A)).status_code == 422


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
        "prove_to_start_trial": None,
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
    "/api/v1/leagues/{manager_id}",
    "/api/v1/leagues/{manager_id}/{league_id}",
    "/api/v1/leagues/{manager_id}/{league_id}/rivals/{rival_id}",
    "/api/v1/live/{manager_id}",
    "/api/v1/live/{manager_id}/leagues/{league_id}",
}


def test_premium_routes_are_exactly_the_advice():
    from app.main import app
    gated = {r.path for r in api_routes(app) if Premium in r.dependencies}
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


async def test_an_unproven_team_says_proving_it_would_start_the_trial(client, fpl):
    """
    Without this, someone who connected by ID and never had a trial reads
    exactly like someone whose trial is used up, and the paywall told them so.
    """
    await start(client)
    ent = (await client.get("/api/v1/me/entitlements", headers=bearer(USER_A))).json()
    assert ent["status"] == "NONE"
    assert ent["prove_to_start_trial"] == 1234


async def test_proving_clears_the_offer(client, fpl):
    await connect(client, fpl)
    ent = (await client.get("/api/v1/me/entitlements", headers=bearer(USER_A))).json()
    assert ent["status"] == "TRIALING"
    assert ent["prove_to_start_trial"] is None


async def test_no_offer_when_the_team_has_had_its_trial(client, fpl):
    await connect(client, fpl, 1234, USER_A)
    await client.delete("/api/v1/me/fpl-accounts/1234", headers=bearer(USER_A))
    await start(client, 1234, USER_B)
    ent = (await client.get("/api/v1/me/entitlements", headers=bearer(USER_B))).json()
    assert ent["prove_to_start_trial"] is None
