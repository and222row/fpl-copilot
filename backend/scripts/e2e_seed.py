"""
Put the staging environment into the known state the Maestro flows expect.

Run before every E2E run. It creates (or resets) one Supabase user per
persona, each with a known password, and writes their FPL team, trial and
subscription rows directly:

    e2e-new@fplcopilot.test         signed up, no team         -> onboarding
    e2e-trial@fplcopilot.test       team + trial, 20 days left -> the app
    e2e-expired@fplcopilot.test     team, trial ended          -> paywall
    e2e-subscriber@fplcopilot.test  team + annual subscription -> the app
    e2e-delete@fplcopilot.test      team + trial               -> deleted by a flow

Refuses to run unless ENVIRONMENT is staging/development and E2E_ALLOW_SEED=1:
it rewrites these users' data and must never touch production.

Needs, from the environment: DATABASE_URL, SUPABASE_URL, SUPABASE_SERVICE_KEY
for the STAGING project; E2E_PASSWORD; E2E_FPL_TEAM_IDS, four real public FPL
team ids (comma separated) for the personas with a team.

    E2E_ALLOW_SEED=1 python scripts/e2e_seed.py
"""
import asyncio
import os
import sys
import uuid
from datetime import timedelta
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import AsyncSessionLocal  # noqa: E402
from app.models.accounts import DeletedUser, FplAccount, FplClaim, Trial, User  # noqa: E402
from app.models.billing import Subscription  # noqa: E402
from app.models.feedback import SquadOverride  # noqa: E402
from app.models.fpl import utcnow  # noqa: E402
from app.models.notifications import Device, NotificationPreference, PushDelivery  # noqa: E402
from app.services.jobs import register_manager  # noqa: E402

DOMAIN = "fplcopilot.test"
# persona -> index into E2E_FPL_TEAM_IDS, or None for "no team"
PERSONAS = {"new": None, "trial": 0, "expired": 1, "subscriber": 2, "delete": 3}


def _guard() -> tuple[str, list[int]]:
    if settings.environment not in ("staging", "development") or os.environ.get("E2E_ALLOW_SEED") != "1":
        sys.exit("Refusing: set ENVIRONMENT=staging (or development) and E2E_ALLOW_SEED=1.")
    password = os.environ.get("E2E_PASSWORD", "")
    if len(password) < 12:
        sys.exit("E2E_PASSWORD must be set (12+ characters).")
    teams = [int(t) for t in os.environ.get("E2E_FPL_TEAM_IDS", "").split(",") if t.strip()]
    if len(teams) < 4:
        sys.exit("E2E_FPL_TEAM_IDS must list four FPL team ids.")
    if not settings.supabase_url or not settings.supabase_service_key:
        sys.exit("SUPABASE_URL and SUPABASE_SERVICE_KEY (staging) are required.")
    return password, teams


def _headers() -> dict:
    key = settings.supabase_service_key
    headers = {"apikey": key, "Content-Type": "application/json"}
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    return headers


async def _ensure_auth_user(client: httpx.AsyncClient, email: str, password: str) -> uuid.UUID:
    base = f"{settings.supabase_url.rstrip('/')}/auth/v1/admin/users"
    listing = (await client.get(base, params={"per_page": 1000}, headers=_headers())).raise_for_status().json()
    existing = next((u for u in listing.get("users", []) if u.get("email") == email), None)
    if existing:
        await client.put(f"{base}/{existing['id']}", json={"password": password}, headers=_headers())
        return uuid.UUID(existing["id"])
    created = (await client.post(
        base, json={"email": email, "password": password, "email_confirm": True}, headers=_headers()
    )).raise_for_status().json()
    return uuid.UUID(created["id"])


async def _reset(db, user_id: uuid.UUID, team: int | None) -> None:
    for model in (FplClaim, FplAccount, Subscription, Device, NotificationPreference, PushDelivery):
        await db.execute(delete(model).where(model.user_id == user_id))
    await db.execute(delete(Trial).where(Trial.user_id == user_id))
    await db.execute(delete(DeletedUser).where(DeletedUser.id == user_id))
    if team is not None:
        # A previous run's deleted persona leaves its team's trial detached.
        await db.execute(delete(Trial).where(Trial.fpl_entry_id == team))
        await db.execute(delete(FplAccount).where(FplAccount.fpl_entry_id == team))
        await db.execute(delete(SquadOverride).where(SquadOverride.fpl_entry_id == team))
    if await db.get(User, user_id) is None:
        db.add(User(id=user_id))
    await db.flush()


async def main() -> None:
    password, teams = _guard()
    now = utcnow()
    async with httpx.AsyncClient(timeout=20.0) as client, AsyncSessionLocal() as db:
        for persona, team_index in PERSONAS.items():
            email = f"e2e-{persona}@{DOMAIN}"
            user_id = await _ensure_auth_user(client, email, password)
            team = teams[team_index] if team_index is not None else None
            await _reset(db, user_id, team)

            if team is not None:
                db.add(FplAccount(user_id=user_id, fpl_entry_id=team, team_name=f"E2E {persona}"))
                await register_manager(db, team, f"E2E {persona}")
            if persona in ("trial", "delete"):
                db.add(Trial(fpl_entry_id=team, user_id=user_id, started_at=now - timedelta(days=10),
                             ends_at=now + timedelta(days=20)))
            elif persona == "expired":
                db.add(Trial(fpl_entry_id=team, user_id=user_id, started_at=now - timedelta(days=31),
                             ends_at=now - timedelta(days=1)))
            elif persona == "subscriber":
                db.add(Subscription(user_id=user_id, provider="PROMOTIONAL", status="ACTIVE", plan="ANNUAL",
                                    product_id="fplc_pro_annual", expires_at=now + timedelta(days=300)))
            print(f"  {persona:<11} {email:<34} team={team}")
        await db.commit()
    print("Seeded.")


if __name__ == "__main__":
    asyncio.run(main())
