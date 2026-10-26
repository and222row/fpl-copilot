"""
The admin dashboard API: only an admin with a verified second factor gets
in; every action needs a reason and is audited; store subscriptions are never
touched; free access survives the store sync.
"""
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.models.accounts import FplAccount, Trial, User
from app.models.admin import AdminAudit
from app.models.billing import Subscription
from app.models.notifications import Device
from app.models.fpl import utcnow
from app.routers import admin as admin_router
from app.services import admin as svc
from app.services import push, revenuecat, supabase_admin
from app.services.entitlements import get_entitlement
from tests.auth_helpers import USER_A, USER_B, bearer, configure_auth, make_token

ADMIN = uuid.UUID("99999999-9999-4999-8999-999999999999")


def admin_headers(**claims) -> dict:
    return bearer(make_token(ADMIN, app_metadata={"role": "admin", **claims.pop("meta", {})}, aal=claims.pop("aal", "aal2"), **claims))


@pytest.fixture(autouse=True)
async def world(session, monkeypatch):
    configure_auth(monkeypatch)
    svc.clear_cache()
    now = utcnow()
    accounts = [
        {"id": str(ADMIN), "email": "boss@example.com", "created_at": (now - timedelta(days=90)).isoformat(),
         "app_metadata": {"providers": ["google"], "role": "admin"}},
        {"id": str(USER_A), "email": "andrew@example.com", "created_at": (now - timedelta(days=3)).isoformat(),
         "last_sign_in_at": now.isoformat(), "app_metadata": {"providers": ["apple"]}},
        {"id": str(USER_B), "email": "sam@example.com", "created_at": (now - timedelta(days=20)).isoformat(),
         "app_metadata": {"providers": ["google"]}},
    ]

    async def list_users():
        return accounts

    async def get_user(user_id):
        return next((a for a in accounts if a["id"] == str(user_id)), None)

    deleted = []

    async def delete_auth(user_id):
        deleted.append(user_id)

    monkeypatch.setattr(supabase_admin, "list_auth_users", list_users)
    monkeypatch.setattr(supabase_admin, "get_auth_user", get_user)
    monkeypatch.setattr(admin_router, "delete_auth_user", delete_auth)

    async def no_rc(user_id):
        return None

    monkeypatch.setattr(admin_router, "delete_subscriber", no_rc)

    session.add_all([User(id=USER_A), User(id=USER_B)])
    await session.flush()
    session.add_all([
        FplAccount(user_id=USER_A, fpl_entry_id=1001, team_name="Gold FC", verified_at=now),
        FplAccount(user_id=USER_B, fpl_entry_id=1002, team_name="Blue Army", verified_at=now),
        Trial(fpl_entry_id=1001, user_id=USER_A, started_at=now - timedelta(days=3), ends_at=now + timedelta(days=27)),
        Subscription(user_id=USER_B, provider="APPLE", status="ACTIVE", plan="ANNUAL", product_id="fplc_pro_annual",
                     expires_at=now + timedelta(days=300)),
        Device(user_id=USER_A, token="ExponentPushToken[aaaaaaaaaaaaaaaaaaaaaa]", platform="ios"),
    ])
    await session.commit()
    return deleted


async def audit_actions(session) -> list[str]:
    return [a for a in (await session.execute(select(AdminAudit.action).order_by(AdminAudit.id))).scalars()]


# ── Who gets in ──────────────────────────────────────────────────────────────

async def test_signed_out_is_401(client):
    assert (await client.get("/api/v1/admin/overview")).status_code == 401


async def test_a_normal_user_is_403(client):
    assert (await client.get("/api/v1/admin/overview", headers=bearer(USER_A))).status_code == 403


async def test_a_role_the_user_wrote_themselves_counts_for_nothing(client):
    # user_metadata is writable by the user; only app_metadata is trusted.
    token = make_token(USER_A, user_metadata={"role": "admin"}, aal="aal2")
    assert (await client.get("/api/v1/admin/overview", headers=bearer(token))).status_code == 403


async def test_an_admin_without_a_second_factor_is_asked_for_one(client):
    r = await client.get("/api/v1/admin/overview", headers=admin_headers(aal="aal1"))
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "MFA_REQUIRED"


# ── Reading ──────────────────────────────────────────────────────────────────

async def test_overview(client):
    r = await client.get("/api/v1/admin/overview", headers=admin_headers())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["users"] == 3 and body["teams_connected"] == 2
    assert body["statuses"] == {"NONE": 1, "TRIALING": 1, "ACTIVE": 1}
    assert body["subscribers"] == {"MONTHLY": 0, "ANNUAL": 1}
    assert body["signups"] == {"7d": 1, "30d": 2}
    assert body["push_devices"] == 1


async def test_user_search_masks_emails(client):
    body = (await client.get("/api/v1/admin/users", headers=admin_headers())).json()
    assert body["total"] == 3
    emails = {u["email"] for u in body["users"]}
    assert emails == {"bo***@example.com", "an***@example.com", "sa***@example.com"}
    assert "andrew@example.com" not in str(body)

    for q in ("andrew", "gold", "1001", str(USER_A)[:8]):
        found = (await client.get("/api/v1/admin/users", params={"q": q}, headers=admin_headers())).json()["users"]
        assert [u["id"] for u in found] == [str(USER_A)], q

    paying = (await client.get("/api/v1/admin/users", params={"status": "ACTIVE"}, headers=admin_headers())).json()["users"]
    assert [u["team"]["team_name"] for u in paying] == ["Blue Army"]


async def test_a_users_page_shows_everything_and_is_audited(client, session):
    r = await client.get(f"/api/v1/admin/users/{USER_A}", headers=admin_headers())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == "andrew@example.com" and body["status"] == "TRIALING"
    assert body["teams"][0]["team_name"] == "Gold FC" and body["trial"]["fpl_entry_id"] == 1001
    assert body["devices"] == [{"platform": "ios", "last_seen_at": body["devices"][0]["last_seen_at"]}]
    assert body["notifications"] == {"availability": True, "price": True, "deadline": True, "live": True}
    assert await audit_actions(session) == ["view_user"]


async def test_unknown_user_is_404(client):
    assert (await client.get(f"/api/v1/admin/users/{uuid.uuid4()}", headers=admin_headers())).status_code == 404


# ── Free access ──────────────────────────────────────────────────────────────

async def test_granting_free_access(client, session):
    r = await client.post(f"/api/v1/admin/users/{USER_A}/grant", json={"days": 30, "reason": "beta tester"}, headers=admin_headers())
    assert r.status_code == 200, r.text
    e = await get_entitlement(session, USER_A, now=utcnow() + timedelta(days=28))  # trial over (27 days), grant not
    assert e.premium and e.provider == "PROMOTIONAL"

    # A second grant adds to the first.
    await client.post(f"/api/v1/admin/users/{USER_A}/grant", json={"days": 10, "reason": "more"}, headers=admin_headers())
    session.expire_all()
    sub = await session.scalar(select(Subscription).where(Subscription.user_id == USER_A))
    assert sub.product_id == "admin_grant"
    assert timedelta(days=39) < sub.expires_at.replace(tzinfo=utcnow().tzinfo) - utcnow() <= timedelta(days=40)

    listed = (await client.get("/api/v1/admin/users", params={"status": "GRANTED"}, headers=admin_headers())).json()["users"]
    assert [u["id"] for u in listed] == [str(USER_A)]
    assert await audit_actions(session) == ["grant_access", "grant_access"]


async def test_the_store_sync_leaves_a_grant_alone(client, session, monkeypatch):
    await client.post(f"/api/v1/admin/users/{USER_A}/grant", json={"days": 30, "reason": "goodwill"}, headers=admin_headers())

    async def nothing_in_revenuecat(app_user_id):
        return {"subscriber": {"entitlements": {}}}

    monkeypatch.setattr(revenuecat, "fetch_subscriber", nothing_in_revenuecat)
    row = await revenuecat.refresh_subscription(session, USER_A)
    assert row.status == "ACTIVE" and row.product_id == "admin_grant"


async def test_a_store_subscriber_is_not_granted(client, session):
    r = await client.post(f"/api/v1/admin/users/{USER_B}/grant", json={"days": 30, "reason": "oops"}, headers=admin_headers())
    assert r.status_code == 409
    sub = await session.scalar(select(Subscription).where(Subscription.user_id == USER_B))
    assert sub.provider == "APPLE"
    assert await audit_actions(session) == []


async def test_ending_a_grant(client, session):
    await client.post(f"/api/v1/admin/users/{USER_A}/grant", json={"days": 30, "reason": "x x"}, headers=admin_headers())
    r = await client.post(f"/api/v1/admin/users/{USER_A}/end-grant", json={"reason": "tester left"}, headers=admin_headers())
    assert r.status_code == 200
    assert (await client.post(f"/api/v1/admin/users/{USER_B}/end-grant", json={"reason": "nothing to end"},
                              headers=admin_headers())).status_code == 409


@pytest.mark.parametrize("body", [{"days": 30}, {"days": 30, "reason": "x"}, {"days": 0, "reason": "valid"},
                                  {"days": 400, "reason": "valid"}, {"days": 30, "reason": "ok ok", "until": "2099"}])
async def test_actions_need_a_reason_and_sane_input(client, body):
    r = await client.post(f"/api/v1/admin/users/{USER_A}/grant", json=body, headers=admin_headers())
    assert r.status_code == 422


# ── Other actions ────────────────────────────────────────────────────────────

async def test_releasing_a_disputed_team(client, session):
    r = await client.post(f"/api/v1/admin/users/{USER_A}/release-team", json={"reason": "owner proved it by email"},
                          headers=admin_headers())
    assert r.json() == {"released": [1001]}
    assert await session.scalar(select(func.count()).select_from(FplAccount).where(FplAccount.user_id == USER_A)) == 0
    # The trial stays with the team, so it cannot be claimed again.
    assert await session.scalar(select(func.count()).select_from(Trial).where(Trial.fpl_entry_id == 1001)) == 1
    assert (await client.post(f"/api/v1/admin/users/{USER_A}/release-team", json={"reason": "again"},
                              headers=admin_headers())).status_code == 409


async def test_a_test_push(client, session, monkeypatch):
    sent = []

    async def fake_send(messages):
        sent.extend(messages)
        return [{"status": "ok"} for _ in messages]

    monkeypatch.setattr(push, "send", fake_send)
    r = await client.post(f"/api/v1/admin/users/{USER_A}/test-push", json={"reason": "user says no alerts"}, headers=admin_headers())
    assert r.json() == {"devices": 1, "sent": 1}
    assert "test notification" in sent[0].body
    assert (await client.post(f"/api/v1/admin/users/{USER_B}/test-push", json={"reason": "no phone"},
                              headers=admin_headers())).status_code == 409


async def test_deleting_an_account_on_request(client, session, world):
    r = await client.request("DELETE", f"/api/v1/admin/users/{USER_A}", json={"reason": "asked by email"}, headers=admin_headers())
    assert r.status_code == 204
    assert world == [USER_A]
    assert await session.get(User, USER_A) is None
    assert await audit_actions(session) == ["delete_account"], "the record of the deletion outlives the user"


async def test_an_admin_cannot_delete_themselves_here(client):
    r = await client.request("DELETE", f"/api/v1/admin/users/{ADMIN}", json={"reason": "whoops"}, headers=admin_headers())
    assert r.status_code == 409


async def test_the_audit_log(client):
    await client.post(f"/api/v1/admin/users/{USER_A}/grant", json={"days": 7, "reason": "first week"}, headers=admin_headers())
    entries = (await client.get("/api/v1/admin/audit", headers=admin_headers())).json()["entries"]
    assert entries[0]["action"] == "grant_access" and entries[0]["reason"] == "first week"
    assert entries[0]["admin_user_id"] == str(ADMIN) and entries[0]["target_user_id"] == str(USER_A)
