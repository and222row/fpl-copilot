"""
Deleting an account: everything personal goes, nothing is half-deleted, and
the deleted account cannot come back through a token issued before deletion.
"""
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import func, select

from app.config import settings
from app.models.accounts import DeletedUser, FplAccount, FplClaim, Trial, User
from app.models.billing import BillingEvent, Subscription
from app.models.feedback import RecommendationSnapshot, SquadOverride
from app.models.fpl import utcnow
from app.models.news import Alert, TrackedManager
from app.models.notifications import Device, NotificationPreference, PushDelivery
from app.services.revenuecat import RevenueCatUnavailable
from app.services.supabase_admin import AuthAdminUnavailable, delete_auth_user
from tests.auth_helpers import USER_A, USER_B, bearer, configure_auth

TOKEN = "ExponentPushToken[aaaaaaaaaaaaaaaaaaaaaa]"


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    configure_auth(monkeypatch)


class FakeExternal:
    def __init__(self):
        self.auth_deleted, self.rc_deleted = [], []
        self.auth_down = self.rc_down = False

    async def delete_auth(self, user_id):
        if self.auth_down:
            raise AuthAdminUnavailable("down")
        self.auth_deleted.append(user_id)

    async def delete_rc(self, app_user_id):
        if self.rc_down:
            raise RevenueCatUnavailable("down")
        self.rc_deleted.append(app_user_id)


@pytest.fixture
def ext(monkeypatch):
    fake = FakeExternal()
    monkeypatch.setattr("app.routers.me.delete_auth_user", fake.delete_auth)
    monkeypatch.setattr("app.routers.me.delete_subscriber", fake.delete_rc)
    return fake


@pytest.fixture
async def populated(session):
    now = utcnow()
    session.add_all([User(id=USER_A), User(id=USER_B)])
    await session.flush()
    session.add_all([
        FplAccount(user_id=USER_A, fpl_entry_id=1234, team_name="A FC"),
        FplAccount(user_id=USER_B, fpl_entry_id=5678, team_name="B FC"),
        FplClaim(user_id=USER_A, fpl_entry_id=999, code="ABCDEF", expires_at=now + timedelta(minutes=5)),
        SquadOverride(fpl_entry_id=1234, gameweek_id=5, player_ids=[1], bank=0, free_transfers=1, transfers_applied=[]),
        TrackedManager(fpl_entry_id=1234, team_name="A FC", telegram_chat_id="42", telegram_enabled=True),
        TrackedManager(fpl_entry_id=5678, team_name="B FC"),
        Alert(fpl_entry_id=1234, title="a", severity="warning"),
        Alert(fpl_entry_id=5678, title="b", severity="warning"),
        RecommendationSnapshot(fpl_entry_id=1234, gameweek_id=5, kind="captain", model_version="v", payload={}, predicted_value=1),
        Trial(fpl_entry_id=1234, user_id=USER_A, started_at=now, ends_at=now + timedelta(days=30)),
        Subscription(user_id=USER_A, provider="APPLE", status="ACTIVE", plan="MONTHLY", product_id="m",
                     expires_at=now + timedelta(days=10)),
        BillingEvent(event_id="e1", event_type="INITIAL_PURCHASE", app_user_id=str(USER_A),
                     payload={"event": {"subscriber_attributes": {"$email": "a@example.com"}}}),
        Device(user_id=USER_A, token=TOKEN, platform="ios"),
        NotificationPreference(user_id=USER_A, price=False),
        PushDelivery(user_id=USER_A, kind="deadline", dedupe_key="gw:5"),
    ])
    await session.commit()
    return session


async def count(session, model, *where):
    return await session.scalar(select(func.count()).select_from(model).where(*where))


async def test_requires_sign_in(client, ext):
    assert (await client.delete("/api/v1/me")).status_code == 401
    assert ext.auth_deleted == []


async def test_deletes_everything_personal(client, populated, ext):
    r = await client.delete("/api/v1/me", headers=bearer(USER_A))
    assert r.status_code == 204
    s = populated
    s.expire_all()
    assert await s.get(User, USER_A) is None
    for model in (FplAccount, FplClaim, Subscription, Device, NotificationPreference, PushDelivery):
        assert await count(s, model, model.user_id == USER_A) == 0, model.__name__
    assert await count(s, SquadOverride, SquadOverride.fpl_entry_id == 1234) == 0
    assert await count(s, Alert, Alert.fpl_entry_id == 1234) == 0
    assert await count(s, RecommendationSnapshot, RecommendationSnapshot.fpl_entry_id == 1234) == 0
    assert await s.get(TrackedManager, 1234) is None
    assert ext.auth_deleted == [USER_A]
    assert ext.rc_deleted == [str(USER_A)]


async def test_leaves_other_users_alone(client, populated, ext):
    await client.delete("/api/v1/me", headers=bearer(USER_A))
    s = populated
    s.expire_all()
    assert await s.get(User, USER_B) is not None
    assert await count(s, FplAccount, FplAccount.user_id == USER_B) == 1
    assert await count(s, Alert, Alert.fpl_entry_id == 5678) == 1
    assert await s.get(TrackedManager, 5678) is not None


async def test_keeps_the_trial_detached_and_the_billing_trail_redacted(client, populated, ext):
    await client.delete("/api/v1/me", headers=bearer(USER_A))
    s = populated
    s.expire_all()
    trial = await s.get(Trial, 1234)
    assert trial is not None and trial.user_id is None
    event = await s.scalar(select(BillingEvent))
    assert event.app_user_id == "deleted"
    assert "a@example.com" not in str(event.payload)


async def test_auth_failure_deletes_nothing(client, populated, ext):
    ext.auth_down = True
    r = await client.delete("/api/v1/me", headers=bearer(USER_A))
    assert r.status_code == 503
    s = populated
    s.expire_all()
    assert await s.get(User, USER_A) is not None
    assert await count(s, FplAccount, FplAccount.user_id == USER_A) == 1
    assert await count(s, Device, Device.user_id == USER_A) == 1
    assert await s.get(DeletedUser, USER_A) is None


async def test_revenuecat_failure_does_not_block_deletion(client, populated, ext):
    ext.rc_down = True
    assert (await client.delete("/api/v1/me", headers=bearer(USER_A))).status_code == 204
    populated.expire_all()
    assert await populated.get(User, USER_A) is None


async def test_an_old_token_cannot_bring_the_account_back(client, populated, ext, monkeypatch):
    await client.delete("/api/v1/me", headers=bearer(USER_A))
    assert (await client.get("/api/v1/me", headers=bearer(USER_A))).status_code == 401
    r = await client.post("/api/v1/me/fpl-accounts", json={"fpl_entry_id": 1234}, headers=bearer(USER_A))
    assert r.status_code == 401
    populated.expire_all()
    assert await populated.get(User, USER_A) is None


async def test_the_released_team_does_not_get_a_second_trial(client, populated, ext, monkeypatch):
    from app.services.entitlements import start_trial_if_eligible
    await client.delete("/api/v1/me", headers=bearer(USER_A))
    populated.expire_all()
    assert await start_trial_if_eligible(populated, USER_B, 1234) is None


# ── Supabase admin call ──────────────────────────────────────────────────────

def _client_returning(status: int, seen: list):
    def handler(request: httpx.Request):
        seen.append(request)
        return httpx.Response(status)

    real = httpx.AsyncClient
    return lambda **kw: real(**{**kw, "transport": httpx.MockTransport(handler)})


@pytest.mark.parametrize("status", [200, 204, 404])
async def test_admin_delete_treats_gone_as_done(monkeypatch, status):
    seen = []
    monkeypatch.setattr(settings, "supabase_service_key", "sb_secret_abc")
    monkeypatch.setattr("app.services.supabase_admin.httpx.AsyncClient", _client_returning(status, seen))
    await delete_auth_user(USER_A)
    req = seen[0]
    assert req.method == "DELETE"
    assert str(req.url) == f"https://testproj.supabase.co/auth/v1/admin/users/{USER_A}"
    assert req.headers["apikey"] == "sb_secret_abc"
    assert "authorization" not in req.headers, "new secret keys are not JWTs"


async def test_admin_delete_sends_bearer_for_legacy_jwt_keys(monkeypatch):
    seen = []
    monkeypatch.setattr(settings, "supabase_service_key", "eyJhbGciOiJIUzI1NiJ9.x.y")
    monkeypatch.setattr("app.services.supabase_admin.httpx.AsyncClient", _client_returning(200, seen))
    await delete_auth_user(USER_A)
    assert seen[0].headers["authorization"] == "Bearer eyJhbGciOiJIUzI1NiJ9.x.y"


@pytest.mark.parametrize("status", [401, 500])
async def test_admin_delete_failure_raises(monkeypatch, status):
    monkeypatch.setattr(settings, "supabase_service_key", "sb_secret_abc")
    monkeypatch.setattr("app.services.supabase_admin.httpx.AsyncClient", _client_returning(status, []))
    with pytest.raises(AuthAdminUnavailable):
        await delete_auth_user(USER_A)


async def test_admin_delete_unconfigured_raises(monkeypatch):
    monkeypatch.setattr(settings, "supabase_service_key", "")
    with pytest.raises(AuthAdminUnavailable):
        await delete_auth_user(USER_A)
