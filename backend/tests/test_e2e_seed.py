"""The E2E seed puts each persona in the state its Maestro flows assume."""
import json
import uuid

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.models.accounts import FplAccount
from app.services.entitlements import get_entitlement


class FakeSupabase:
    def __init__(self):
        self.users: dict[str, str] = {}  # email -> id
        self.passwords: dict[str, str] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"users": [{"id": i, "email": e} for e, i in self.users.items()]})
        body = json.loads(request.content)
        if request.method == "POST":
            uid = str(uuid.uuid4())
            self.users[body["email"]] = uid
            self.passwords[uid] = body["password"]
            return httpx.Response(200, json={"id": uid})
        uid = request.url.path.rsplit("/", 1)[1]
        self.passwords[uid] = body["password"]
        return httpx.Response(200, json={"id": uid})


@pytest.fixture
def seed(monkeypatch, engine):
    import scripts.e2e_seed as module

    fake = FakeSupabase()
    real = httpx.AsyncClient
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(fake.handler), **kw))
    monkeypatch.setattr(module, "AsyncSessionLocal", async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False))
    monkeypatch.setattr(settings, "environment", "staging")
    monkeypatch.setattr(settings, "supabase_url", "https://staging.supabase.co")
    monkeypatch.setattr(settings, "supabase_service_key", "sb_secret_staging")
    monkeypatch.setenv("E2E_ALLOW_SEED", "1")
    monkeypatch.setenv("E2E_PASSWORD", "correct-horse-battery")
    monkeypatch.setenv("E2E_FPL_TEAM_IDS", "101,102,103,104")
    return module, fake


async def statuses(session, fake) -> dict[str, str]:
    out = {}
    for email, uid in fake.users.items():
        out[email.split("@")[0]] = (await get_entitlement(session, uuid.UUID(uid))).status
    return out


async def test_each_persona_lands_in_its_state(seed, session):
    module, fake = seed
    await module.main()
    assert await statuses(session, fake) == {
        "e2e-new": "NONE",
        "e2e-trial": "TRIALING",
        "e2e-expired": "EXPIRED",
        "e2e-subscriber": "ACTIVE",
        "e2e-delete": "TRIALING",
    }
    new_id = uuid.UUID(fake.users["e2e-new@fplcopilot.test"])
    assert await session.scalar(select(func.count()).select_from(FplAccount).where(FplAccount.user_id == new_id)) == 0


async def test_reseeding_is_safe_and_resets_state(seed, session):
    module, fake = seed
    await module.main()
    await module.main()
    assert len(fake.users) == 5, "existing users are reused, not duplicated"
    assert await session.scalar(select(func.count()).select_from(FplAccount)) == 4
    assert (await statuses(session, fake))["e2e-expired"] == "EXPIRED"


async def test_refuses_without_the_flag(seed, monkeypatch):
    module, _ = seed
    monkeypatch.delenv("E2E_ALLOW_SEED")
    with pytest.raises(SystemExit):
        await module.main()


async def test_refuses_in_production(seed, monkeypatch):
    module, _ = seed
    monkeypatch.setattr(settings, "environment", "production")
    with pytest.raises(SystemExit):
        await module.main()
