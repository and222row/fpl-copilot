"""
Store billing through RevenueCat.

The rules under test: a webhook is authenticated before anything is read, its
body is never trusted for state, each event is processed once, a failure is
retried, and access ends at expiry by the server clock whatever was stored.
"""
import hashlib
import hmac
import json
import time
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.config import settings
from app.models.accounts import Trial, User
from app.models.billing import BillingEvent, Subscription
from app.models.fpl import utcnow
from app.services.entitlements import get_entitlement
from app.services.revenuecat import RevenueCatUnavailable, parse_subscriber, plan_for
from tests.auth_helpers import USER_A, USER_B, bearer, configure_auth

URL = "/api/v1/billing/revenuecat/webhook"
AUTH = "Bearer wh-test-secret"
SIGNING = "signing-secret"


@pytest.fixture(autouse=True)
def billing_settings(monkeypatch):
    configure_auth(monkeypatch)
    monkeypatch.setattr(settings, "revenuecat_webhook_auth", AUTH)
    monkeypatch.setattr(settings, "revenuecat_webhook_signing_secret", "")
    monkeypatch.setattr(settings, "revenuecat_secret_key", "sk_test")


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def subscriber(*, expires_in=timedelta(days=20), product="fplc_pro_monthly", store="app_store",
               unsubscribed=False, billing_issue=False, grace_in=None, entitlement=True):
    now = utcnow()
    body = {"subscriber": {"entitlements": {}, "subscriptions": {}, "management_url": "https://apps.apple.com/account/subscriptions"}}
    if entitlement:
        body["subscriber"]["entitlements"]["pro"] = {
            "expires_date": iso(now + expires_in) if expires_in is not None else None,
            "grace_period_expires_date": iso(now + grace_in) if grace_in else None,
            "product_identifier": product,
            "purchase_date": iso(now - timedelta(days=10)),
        }
        body["subscriber"]["subscriptions"][product] = {
            "store": store,
            "expires_date": iso(now + (expires_in or timedelta(0))),
            "unsubscribe_detected_at": iso(now) if unsubscribed else None,
            "billing_issues_detected_at": iso(now) if billing_issue else None,
            "is_sandbox": True,
        }
    return body


class FakeRevenueCat:
    def __init__(self):
        self.calls: list[str] = []
        self.responses: dict[str, dict] = {}
        self.down = False

    async def fetch(self, app_user_id: str) -> dict:
        self.calls.append(app_user_id)
        if self.down:
            raise RevenueCatUnavailable("timeout")
        return self.responses.get(app_user_id, {"subscriber": {"entitlements": {}, "subscriptions": {}}})


@pytest.fixture
def rc(monkeypatch):
    fake = FakeRevenueCat()
    monkeypatch.setattr("app.services.revenuecat.fetch_subscriber", fake.fetch)
    return fake


@pytest.fixture
async def users(session):
    session.add_all([User(id=USER_A), User(id=USER_B)])
    await session.commit()


def payload(event_id="evt-1", type_="INITIAL_PURCHASE", app_user_id=str(USER_A), **extra):
    return {"api_version": "1.0", "event": {"id": event_id, "type": type_, "app_user_id": app_user_id,
                                            "environment": "SANDBOX", **extra}}


async def post(client, body, *, auth=AUTH, signature=None):
    raw = json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if auth:
        headers["Authorization"] = auth
    if signature:
        headers["X-RevenueCat-Webhook-Signature"] = signature
    return await client.post(URL, content=raw, headers=headers)


def sign(body: dict, ts: int | None = None, secret=SIGNING) -> str:
    ts = ts or int(time.time())
    raw = json.dumps(body).encode()
    mac = hmac.new(secret.encode(), f"{ts}.".encode() + raw, hashlib.sha256).hexdigest()
    return f"t={ts},v1={mac}"


# ── Webhook authentication ───────────────────────────────────────────────────

async def test_unconfigured_webhook_refuses_everything(client, monkeypatch, rc):
    monkeypatch.setattr(settings, "revenuecat_webhook_auth", "")
    assert (await post(client, payload())).status_code == 503
    assert rc.calls == []


@pytest.mark.parametrize("auth", [None, "Bearer wrong", "wh-test-secret"])
async def test_wrong_authorization_is_rejected_before_anything_is_read(client, rc, users, session, auth):
    assert (await post(client, payload(), auth=auth)).status_code == 401
    assert rc.calls == []
    assert (await session.execute(select(BillingEvent))).scalars().all() == []


async def test_valid_signature_is_accepted(client, monkeypatch, rc, users):
    monkeypatch.setattr(settings, "revenuecat_webhook_signing_secret", SIGNING)
    body = payload()
    assert (await post(client, body, signature=sign(body))).status_code == 200


@pytest.mark.parametrize("make_sig", [
    lambda body: None,
    lambda body: sign(body, secret="other"),
    lambda body: sign(body, ts=int(time.time()) - 3600),        # replayed an hour later
    lambda body: sign({**body, "event": {**body["event"], "app_user_id": str(USER_B)}}),  # body swapped
    lambda body: "garbage",
])
async def test_bad_signatures_are_rejected(client, monkeypatch, rc, users, make_sig):
    monkeypatch.setattr(settings, "revenuecat_webhook_signing_secret", SIGNING)
    body = payload()
    assert (await post(client, body, signature=make_sig(body))).status_code == 401
    assert rc.calls == []


async def test_malformed_payload_is_400(client, rc):
    r = await client.post(URL, content=b"{not json", headers={"Authorization": AUTH})
    assert r.status_code == 400


async def test_oversized_payload_is_413(client, rc):
    r = await client.post(URL, content=b"x" * 70_000, headers={"Authorization": AUTH})
    assert r.status_code == 413


# ── Webhook processing ───────────────────────────────────────────────────────

async def test_purchase_webhook_stores_state_read_from_revenuecat(client, session, rc, users):
    rc.responses[str(USER_A)] = subscriber()
    r = await post(client, payload())
    assert r.status_code == 200 and r.json()["users_refreshed"] == 1
    sub = await session.scalar(select(Subscription).where(Subscription.user_id == USER_A))
    assert (sub.status, sub.plan, sub.provider) == ("ACTIVE", "MONTHLY", "APPLE")
    assert (await get_entitlement(session, USER_A)).premium is True


async def test_webhook_body_is_never_trusted_for_state(client, session, rc, users):
    # The payload claims a far-future expiry; RevenueCat says it has lapsed.
    rc.responses[str(USER_A)] = subscriber(expires_in=timedelta(days=-1))
    await post(client, payload(expiration_at_ms=4102444800000, entitlement_ids=["pro"]))
    ent = await get_entitlement(session, USER_A)
    assert ent.premium is False and ent.status == "EXPIRED"


async def test_duplicate_delivery_is_processed_once(client, rc, users):
    rc.responses[str(USER_A)] = subscriber()
    assert (await post(client, payload())).json()["status"] == "processed"
    assert (await post(client, payload())).json() == {"status": "duplicate"}
    assert rc.calls == [str(USER_A)]


async def test_revenuecat_outage_returns_non_200_and_is_retried(client, session, rc, users):
    rc.down = True
    assert (await post(client, payload())).status_code == 502
    record = await session.scalar(select(BillingEvent))
    assert record.processed_at is None and "timeout" in record.error

    rc.down = False
    rc.responses[str(USER_A)] = subscriber()
    assert (await post(client, payload())).json()["status"] == "processed"
    session.expire_all()
    assert (await session.scalar(select(BillingEvent))).processed_at is not None


async def test_anonymous_and_unknown_ids_are_ignored(client, rc, users):
    body = payload(app_user_id="$RCAnonymousID:abc", original_app_user_id="00000000-0000-4000-8000-000000000000")
    r = await post(client, body)
    assert r.status_code == 200 and r.json()["users_refreshed"] == 0
    assert rc.calls == []


async def test_aliases_refresh_the_real_account(client, rc, users):
    rc.responses[str(USER_A)] = subscriber()
    body = payload(app_user_id="$RCAnonymousID:abc", aliases=["$RCAnonymousID:abc", str(USER_A)])
    assert (await post(client, body)).json()["users_refreshed"] == 1


async def test_transfer_refreshes_both_sides(client, session, rc, users):
    rc.responses[str(USER_B)] = subscriber()
    session.add(Subscription(user_id=USER_A, provider="APPLE", status="ACTIVE", plan="MONTHLY",
                             product_id="fplc_pro_monthly", expires_at=utcnow() + timedelta(days=5)))
    await session.commit()
    body = payload(type_="TRANSFER", app_user_id=None, transferred_from=[str(USER_A)], transferred_to=[str(USER_B)])
    assert (await post(client, body)).json()["users_refreshed"] == 2
    assert (await get_entitlement(session, USER_A)).premium is False
    assert (await get_entitlement(session, USER_B)).premium is True


async def test_test_event_is_acknowledged(client, rc):
    r = await post(client, payload(type_="TEST", app_user_id="test-user"))
    assert r.status_code == 200


# ── Mapping RevenueCat state ─────────────────────────────────────────────────

@pytest.mark.parametrize("kwargs,status", [
    ({}, "ACTIVE"),
    ({"unsubscribed": True}, "CANCELED"),
    ({"billing_issue": True, "expires_in": timedelta(days=-1), "grace_in": timedelta(days=3)}, "PAST_DUE"),
    ({"expires_in": timedelta(days=-1)}, "EXPIRED"),
    ({"expires_in": None}, "ACTIVE"),  # lifetime
])
def test_status_mapping(kwargs, status):
    assert parse_subscriber(subscriber(**kwargs)).status == status


def test_no_entitlement_means_no_subscription():
    assert parse_subscriber(subscriber(entitlement=False)) is None


@pytest.mark.parametrize("product,plan", [
    ("fplc_pro_monthly", "MONTHLY"), ("fplc_pro_annual", "ANNUAL"), ("pro:yearly", "ANNUAL"), ("pro", None),
])
def test_plan_from_product(product, plan):
    assert plan_for(product) == plan


def test_store_maps_to_provider():
    assert parse_subscriber(subscriber(store="play_store")).provider == "GOOGLE"


# ── Entitlement ──────────────────────────────────────────────────────────────

async def test_paid_subscription_outranks_a_running_trial(session, users):
    now = utcnow()
    session.add(Trial(fpl_entry_id=1, user_id=USER_A, started_at=now, ends_at=now + timedelta(days=30)))
    session.add(Subscription(user_id=USER_A, provider="GOOGLE", status="ACTIVE", plan="ANNUAL",
                             product_id="fplc_pro_annual", expires_at=now + timedelta(days=365)))
    await session.commit()
    ent = await get_entitlement(session, USER_A)
    assert (ent.status, ent.plan, ent.provider) == ("ACTIVE", "ANNUAL", "GOOGLE")


async def test_access_ends_at_expiry_even_if_the_expiry_webhook_never_came(session, users):
    now = utcnow()
    session.add(Subscription(user_id=USER_A, provider="APPLE", status="ACTIVE", plan="MONTHLY",
                             product_id="m", expires_at=now - timedelta(minutes=1)))
    await session.commit()
    ent = await get_entitlement(session, USER_A)
    assert ent.premium is False and ent.status == "EXPIRED" and ent.plan == "MONTHLY"


async def test_grace_period_keeps_access(session, users):
    now = utcnow()
    session.add(Subscription(user_id=USER_A, provider="APPLE", status="PAST_DUE", plan="MONTHLY", product_id="m",
                             expires_at=now - timedelta(days=1), grace_expires_at=now + timedelta(days=2)))
    await session.commit()
    ent = await get_entitlement(session, USER_A)
    assert ent.premium is True and ent.status == "PAST_DUE"


async def test_cancelled_keeps_access_until_the_period_ends(session, users):
    now = utcnow()
    session.add(Subscription(user_id=USER_A, provider="APPLE", status="CANCELED", plan="ANNUAL", product_id="a",
                             expires_at=now + timedelta(days=40)))
    await session.commit()
    assert (await get_entitlement(session, USER_A)).premium is True


async def test_trial_falls_back_when_the_subscription_has_lapsed(session, users):
    now = utcnow()
    session.add(Trial(fpl_entry_id=1, user_id=USER_A, started_at=now, ends_at=now + timedelta(days=10)))
    session.add(Subscription(user_id=USER_A, provider="APPLE", status="EXPIRED", plan="MONTHLY", product_id="m",
                             expires_at=now - timedelta(days=1)))
    await session.commit()
    assert (await get_entitlement(session, USER_A)).status == "TRIALING"


# ── Post-purchase sync ───────────────────────────────────────────────────────

async def test_sync_requires_sign_in(client, rc):
    assert (await client.post("/api/v1/billing/sync")).status_code == 401


async def test_sync_reads_only_the_callers_own_state(client, rc, users):
    rc.responses[str(USER_A)] = subscriber(product="fplc_pro_annual")
    r = await client.post(
        "/api/v1/billing/sync",
        json={"app_user_id": str(USER_B), "premium": True, "plan": "ANNUAL"},
        headers=bearer(USER_A),
    )
    assert r.status_code == 200
    assert r.json()["status"] == "ACTIVE" and r.json()["plan"] == "ANNUAL"
    assert rc.calls == [str(USER_A)], "the body must not pick whose state is read"


async def test_sync_cannot_conjure_premium(client, rc, users):
    r = await client.post("/api/v1/billing/sync", json={"premium": True}, headers=bearer(USER_A))
    assert r.json()["premium"] is False


async def test_sync_when_revenuecat_is_down_is_503(client, rc, users):
    rc.down = True
    assert (await client.post("/api/v1/billing/sync", headers=bearer(USER_A))).status_code == 503


async def test_premium_route_opens_after_a_purchase_and_closes_at_expiry(client, session, rc, users):
    assert (await client.get("/api/v1/projections", headers=bearer(USER_A))).status_code == 402
    rc.responses[str(USER_A)] = subscriber()
    await client.post("/api/v1/billing/sync", headers=bearer(USER_A))
    assert (await client.get("/api/v1/projections", headers=bearer(USER_A))).status_code != 402

    sub = await session.scalar(select(Subscription).where(Subscription.user_id == USER_A))
    sub.expires_at = utcnow() - timedelta(seconds=1)
    await session.commit()
    assert (await client.get("/api/v1/projections", headers=bearer(USER_A))).status_code == 402


# ── Entitlement naming ───────────────────────────────────────────────────────

def renamed(body: dict, name: str) -> dict:
    ents = body["subscriber"]["entitlements"]
    ents[name] = ents.pop("pro")
    return body


async def test_a_differently_named_entitlement_grants_nothing_and_says_why(session, rc, users, caplog):
    """Found in the first real test purchase: the entitlement was `fpl_copilot_pro`."""
    from app.services.revenuecat import refresh_subscription

    rc.responses[str(USER_A)] = renamed(subscriber(), "fpl_copilot_pro")
    with caplog.at_level("ERROR", logger="fpl_copilot.billing"):
        assert await refresh_subscription(session, USER_A) is None
    assert any("REVENUECAT_ENTITLEMENT_ID" in r.getMessage() for r in caplog.records)
    assert caplog.records[-1].found == ["fpl_copilot_pro"]


async def test_the_configured_entitlement_name_is_used(session, rc, users, monkeypatch):
    from app.services.revenuecat import refresh_subscription

    monkeypatch.setattr(settings, "revenuecat_entitlement_id", "fpl_copilot_pro")
    rc.responses[str(USER_A)] = renamed(subscriber(product="fplc_pro_annual", store="test_store"), "fpl_copilot_pro")
    row = await refresh_subscription(session, USER_A)
    await session.commit()
    assert (row.status, row.plan, row.provider, row.is_sandbox) == ("ACTIVE", "ANNUAL", "TEST_STORE", True)
    assert (await get_entitlement(session, USER_A)).premium
