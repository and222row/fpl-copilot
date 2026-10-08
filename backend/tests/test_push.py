"""Push devices, preferences, and what the refresh sends."""
import json
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import func, select

from app.config import settings
from app.models.accounts import FplAccount, User
from app.models.fpl import Gameweek, utcnow
from app.models.news import Alert
from app.models.notifications import Device, NotificationPreference, PushDelivery
from app.services import push
from tests.auth_helpers import USER_A, USER_B, bearer, configure_auth

TOKEN_A = "ExponentPushToken[aaaaaaaaaaaaaaaaaaaaaa]"
TOKEN_A2 = "ExponentPushToken[a2a2a2a2a2a2a2a2a2a2a2]"
TOKEN_B = "ExponentPushToken[bbbbbbbbbbbbbbbbbbbbbb]"


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    configure_auth(monkeypatch)


# ── Devices ──────────────────────────────────────────────────────────────────

async def register(client, token, user=USER_A, platform="ios"):
    return await client.put("/api/v1/me/devices", json={"token": token, "platform": platform}, headers=bearer(user))


async def test_register_requires_sign_in(client):
    r = await client.put("/api/v1/me/devices", json={"token": TOKEN_A, "platform": "ios"})
    assert r.status_code == 401


@pytest.mark.parametrize("body", [
    {"token": "not-a-push-token-at-all", "platform": "ios"},
    {"token": TOKEN_A, "platform": "windows"},
    {"token": TOKEN_A, "platform": "ios", "user_id": str(USER_B)},
])
async def test_register_rejects_bad_input(client, body):
    r = await client.put("/api/v1/me/devices", json=body, headers=bearer())
    assert r.status_code == 422


async def test_register_and_reregister(client, session):
    assert (await register(client, TOKEN_A)).status_code == 204
    assert (await register(client, TOKEN_A)).status_code == 204
    assert await session.scalar(select(func.count()).select_from(Device)) == 1


async def test_a_token_moves_to_whoever_signed_in_last(client, session):
    await register(client, TOKEN_A, USER_A)
    await register(client, TOKEN_A, USER_B)
    session.expire_all()
    device = await session.scalar(select(Device))
    assert device.user_id == USER_B


async def test_devices_per_account_are_capped(client, session):
    for i in range(12):
        await register(client, f"ExponentPushToken[{i:022d}]")
    assert await session.scalar(select(func.count()).select_from(Device)) == 10


async def test_unregister_only_your_own(client, session):
    await register(client, TOKEN_A, USER_A)
    assert (await client.delete(f"/api/v1/me/devices/{TOKEN_A}", headers=bearer(USER_B))).status_code == 404
    assert (await client.delete(f"/api/v1/me/devices/{TOKEN_A}", headers=bearer(USER_A))).status_code == 204
    assert await session.scalar(select(func.count()).select_from(Device)) == 0


# ── Preferences ──────────────────────────────────────────────────────────────

async def test_preferences_default_on_and_update_partially(client):
    assert (await client.get("/api/v1/me/notifications", headers=bearer())).json() == {
        "availability": True, "price": True, "deadline": True,
    }
    r = await client.put("/api/v1/me/notifications", json={"price": False}, headers=bearer())
    assert r.json() == {"availability": True, "price": False, "deadline": True}
    assert (await client.get("/api/v1/me/notifications", headers=bearer())).json()["price"] is False


async def test_preferences_reject_unknown_kinds(client):
    r = await client.put("/api/v1/me/notifications", json={"lineup": True}, headers=bearer())
    assert r.status_code == 422


# ── Sending ──────────────────────────────────────────────────────────────────

class FakeExpo:
    def __init__(self):
        self.sent: list[push.Message] = []
        self.down = False
        self.unregistered: set[str] = set()

    async def send(self, messages):
        if self.down:
            raise push.PushUnavailable("expo down")
        self.sent.extend(messages)
        return [
            {"status": "error", "details": {"error": "DeviceNotRegistered"}}
            if m.token in self.unregistered else {"status": "ok", "id": "x"}
            for m in messages
        ]


@pytest.fixture
def expo(monkeypatch):
    fake = FakeExpo()
    monkeypatch.setattr(push, "send", fake.send)
    return fake


@pytest.fixture
async def world(session):
    session.add_all([User(id=USER_A), User(id=USER_B)])
    await session.flush()
    session.add_all([
        FplAccount(user_id=USER_A, fpl_entry_id=1234),
        FplAccount(user_id=USER_B, fpl_entry_id=5678),
        Device(user_id=USER_A, token=TOKEN_A, platform="ios"),
        Device(user_id=USER_A, token=TOKEN_A2, platform="android"),
        Device(user_id=USER_B, token=TOKEN_B, platform="ios"),
        # Far-off deadline unless a test moves it.
        Gameweek(id=9, name="Gameweek 9", deadline_time=utcnow() + timedelta(days=3)),
    ])
    await session.commit()
    return session


def alert(entry, *, severity="warning", event_type="status_change", age=timedelta(minutes=5), title="Saka is a doubt"):
    return Alert(fpl_entry_id=entry, severity=severity, title=title, body="Knock - 75% chance of playing",
                 payload={"event_type": event_type}, player_id=7, created_at=utcnow() - age)


async def test_squad_alert_goes_to_every_device_of_the_owner(world, expo):
    world.add(alert(1234))
    await world.commit()
    result = await push.send_due(world)
    assert result["sent"] == 2
    assert {m.token for m in expo.sent} == {TOKEN_A, TOKEN_A2}
    assert expo.sent[0].title == "Saka is a doubt"
    assert expo.sent[0].data == {"type": "alert", "player_id": 7}


async def test_nothing_is_sent_twice(world, expo):
    world.add(alert(1234))
    await world.commit()
    await push.send_due(world)
    await world.commit()
    await push.send_due(world)
    assert len(expo.sent) == 2


async def test_preferences_are_respected(world, expo):
    world.add_all([
        NotificationPreference(user_id=USER_A, price=False),
        alert(1234, event_type="price_imminent", title="Price rise likely"),
        alert(1234, title="Doubt"),
    ])
    await world.commit()
    await push.send_due(world)
    assert {m.title for m in expo.sent} == {"Doubt"}


async def test_old_and_minor_alerts_are_not_pushed(world, expo):
    world.add_all([alert(1234, age=timedelta(hours=5)), alert(1234, severity="info")])
    await world.commit()
    await push.send_due(world)
    assert expo.sent == []


async def test_alerts_for_teams_nobody_owns_are_ignored(world, expo):
    world.add(alert(424242))
    await world.commit()
    await push.send_due(world)
    assert expo.sent == []


async def test_deadline_reminder_inside_two_hours_once(world, expo):
    gw = await world.get(Gameweek, 9)
    gw.deadline_time = utcnow() + timedelta(minutes=95)
    await world.commit()
    await push.send_due(world)
    titles = [m.title for m in expo.sent]
    assert len(titles) == 3  # two devices for A, one for B
    assert titles[0].startswith("Gameweek 9 deadline in 1h 3")
    await world.commit()
    await push.send_due(world)
    assert len(expo.sent) == 3


async def test_no_deadline_reminder_outside_the_window(world, expo):
    await push.send_due(world)
    assert expo.sent == []


async def test_dead_tokens_are_pruned(world, expo):
    expo.unregistered = {TOKEN_A2}
    world.add(alert(1234))
    await world.commit()
    result = await push.send_due(world)
    assert result["pruned"] == 1
    assert await world.scalar(select(Device).where(Device.token == TOKEN_A2)) is None


async def test_an_outage_leaves_pushes_unsent_for_next_time(world, expo):
    world.add(alert(1234))
    await world.commit()
    expo.down = True
    with pytest.raises(push.PushUnavailable):
        await push.send_due(world)
    await world.commit()
    assert await world.scalar(select(func.count()).select_from(PushDelivery)) == 0
    expo.down = False
    await push.send_due(world)
    assert len(expo.sent) == 2


# ── Transport ────────────────────────────────────────────────────────────────

async def test_send_batches_and_authenticates(monkeypatch):
    requests = []

    def handler(request):
        batch = json.loads(request.content)
        requests.append((request, batch))
        return httpx.Response(200, json={"data": [{"status": "ok", "id": str(i)} for i in range(len(batch))]})

    real = httpx.AsyncClient
    monkeypatch.setattr(push.httpx, "AsyncClient", lambda **kw: real(**{**kw, "transport": httpx.MockTransport(handler)}))
    monkeypatch.setattr(settings, "expo_access_token", "expo-secret")
    messages = [push.Message(f"ExponentPushToken[{i:022d}]", "t", "b") for i in range(150)]
    tickets = await push.send(messages)
    assert len(tickets) == 150
    assert [len(b) for _, b in requests] == [100, 50]
    assert requests[0][0].headers["authorization"] == "Bearer expo-secret"
    assert requests[0][1][0]["channelId"] == "alerts"


async def test_send_raises_on_http_failure(monkeypatch):
    real = httpx.AsyncClient
    handler = lambda request: httpx.Response(503)  # noqa: E731
    monkeypatch.setattr(push.httpx, "AsyncClient", lambda **kw: real(**{**kw, "transport": httpx.MockTransport(handler)}))
    with pytest.raises(push.PushUnavailable):
        await push.send([push.Message("ExponentPushToken[0000000000000000000000]", "t", "b")])
