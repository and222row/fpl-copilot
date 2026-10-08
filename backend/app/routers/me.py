import secrets
from datetime import timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthUser, current_user
from app.database import get_db
from app.models.accounts import FplAccount, FplClaim
from app.models.feedback import SquadOverride
from app.models.fpl import utcnow
from app.models.news import TrackedManager
from app.rate_limit import UPSTREAM, limiter
from app.services.entitlements import get_entitlement, start_trial_if_eligible
from app.services.fpl_client import fetch_manager_info, fetch_manager_info_fresh
from app.services.jobs import register_manager

router = APIRouter(prefix="/me", tags=["me"])

# One team per account keeps onboarding simple.
MAX_FPL_ACCOUNTS = 1
CLAIM_TTL = timedelta(minutes=30)
MAX_VERIFY_ATTEMPTS = 10
# No 0/O or 1/I: the code is read off a phone and typed into the FPL site.
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 6


class ConnectFplAccount(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fpl_entry_id: int = Field(ge=1, le=100_000_000)


def _account_dict(a: FplAccount) -> dict:
    return {
        "fpl_entry_id": a.fpl_entry_id,
        "team_name": a.team_name,
        "manager_name": a.manager_name,
        "connected_at": a.created_at,
    }


def _aware(dt):
    return dt if dt.tzinfo else dt.replace(tzinfo=utcnow().tzinfo)


def _new_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def _claim_dict(c: FplClaim) -> dict:
    return {
        "status": "verification_required",
        "fpl_entry_id": c.fpl_entry_id,
        "team_name": c.team_name,
        "code": c.code,
        "expires_at": c.expires_at,
        "attempts_remaining": MAX_VERIFY_ATTEMPTS - c.attempts,
        "instructions": (
            f"In the FPL app or website, open Team Details and add {c.code} to "
            "your team name (FPL allows 20 characters, so replace part of it if "
            "needed). Save, then tap Verify. You can change the name back as "
            "soon as you are verified."
        ),
    }


async def _fpl_entry(fetch, fpl_entry_id: int) -> dict:
    try:
        return await fetch(fpl_entry_id)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise HTTPException(404, f"No FPL team found with ID {fpl_entry_id}")
        raise HTTPException(502, "FPL returned an error. Please try again shortly.")
    except httpx.HTTPError:
        raise HTTPException(503, "FPL is unreachable right now. Please try again shortly.")


async def _owned(db: AsyncSession, user: AuthUser) -> list[FplAccount]:
    return list((await db.execute(
        select(FplAccount).where(FplAccount.user_id == user.id).order_by(FplAccount.id)
    )).scalars())


async def _release_team(db: AsyncSession, fpl_entry_id: int) -> None:
    """Drop the private state attached to a team so its next owner inherits none."""
    await db.execute(delete(SquadOverride).where(SquadOverride.fpl_entry_id == fpl_entry_id))
    tracked = await db.get(TrackedManager, fpl_entry_id)
    if tracked is not None:
        tracked.alerts_enabled = False
        tracked.telegram_chat_id = None
        tracked.telegram_enabled = False
        tracked.telegram_linked_at = None


@router.get("")
async def me(user: AuthUser = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return {
        "id": str(user.id),
        "email": user.email,
        "phone": user.phone,
        "providers": user.providers,
        "fpl_accounts": [_account_dict(a) for a in await _owned(db, user)],
    }


@router.get("/entitlements")
async def entitlements(user: AuthUser = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Whether the caller has premium access right now. The app must not decide this itself."""
    return (await get_entitlement(db, user.id)).as_dict()


@router.post("/fpl-accounts", status_code=202)
@limiter.limit(UPSTREAM)
async def start_fpl_connection(
    request: Request,
    response: Response,
    body: ConnectFplAccount,
    user: AuthUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Begin connecting a team: confirm it exists, then issue the code that proves
    control of it. Whether someone else has already connected the team is not
    revealed; proving control takes it over either way.
    """
    owned = await _owned(db, user)
    for a in owned:
        if a.fpl_entry_id == body.fpl_entry_id:
            response.status_code = 200
            return {"status": "connected", **_account_dict(a)}
    if len(owned) >= MAX_FPL_ACCOUNTS:
        raise HTTPException(409, "Disconnect your current FPL team before connecting another")

    now = utcnow()
    claim = await db.scalar(
        select(FplClaim).where(
            FplClaim.user_id == user.id, FplClaim.fpl_entry_id == body.fpl_entry_id
        )
    )
    # An exhausted code is replaced rather than reused, or the user would be
    # stuck until it expired. The cap limits FPL calls per code; the route's
    # rate limit bounds the total. Guessing gains nothing either way: the code
    # only counts once it is in the real team name.
    if (
        claim is not None
        and _aware(claim.expires_at) > now
        and claim.attempts < MAX_VERIFY_ATTEMPTS
    ):
        return _claim_dict(claim)

    info = await _fpl_entry(fetch_manager_info, body.fpl_entry_id)
    team_name = str(info.get("name") or "")[:120]
    manager_name = " ".join(
        s for s in (info.get("player_first_name"), info.get("player_last_name")) if s
    )[:120]

    if claim is None:
        claim = FplClaim(user_id=user.id, fpl_entry_id=body.fpl_entry_id)
        db.add(claim)
    claim.code = _new_code()
    claim.team_name = team_name
    claim.manager_name = manager_name
    claim.attempts = 0
    claim.created_at = now
    claim.expires_at = now + CLAIM_TTL
    await db.flush()
    return _claim_dict(claim)


@router.post("/fpl-accounts/{fpl_entry_id}/verify", status_code=201)
@limiter.limit(UPSTREAM)
async def verify_fpl_connection(
    request: Request,
    fpl_entry_id: int,
    user: AuthUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """Check FPL for the code in the team name; on success the team is yours."""
    now = utcnow()
    claim = await db.scalar(
        select(FplClaim).where(FplClaim.user_id == user.id, FplClaim.fpl_entry_id == fpl_entry_id)
    )
    if claim is None or _aware(claim.expires_at) <= now:
        raise HTTPException(404, "No pending connection for this team. Start again to get a new code.")
    if claim.attempts >= MAX_VERIFY_ATTEMPTS:
        raise HTTPException(429, "Too many attempts. Start again to get a new code.")

    # Committed before checking, so a failed attempt still counts: the error
    # response below rolls the session back.
    claim.attempts += 1
    await db.commit()

    info = await _fpl_entry(fetch_manager_info_fresh, fpl_entry_id)
    current_name = str(info.get("name") or "")
    if claim.code not in current_name.upper().replace(" ", ""):
        raise HTTPException(422, {
            "code": "CODE_NOT_FOUND",
            "message": (
                f"{claim.code} isn't in your team name yet (FPL shows "
                f"\"{current_name}\"). Name changes can take a minute to appear."
            ),
            "attempts_remaining": MAX_VERIFY_ATTEMPTS - claim.attempts,
        })

    if len(await _owned(db, user)) >= MAX_FPL_ACCOUNTS:
        raise HTTPException(409, "Disconnect your current FPL team before connecting another")

    # Proving control outranks an earlier connection by someone else.
    previous = await db.scalar(select(FplAccount).where(FplAccount.fpl_entry_id == fpl_entry_id))
    if previous is not None:
        await db.delete(previous)
        await _release_team(db, fpl_entry_id)
        await db.flush()

    account = FplAccount(
        user_id=user.id, fpl_entry_id=fpl_entry_id,
        team_name=claim.team_name, manager_name=claim.manager_name,
    )
    db.add(account)
    await db.execute(delete(FplClaim).where(FplClaim.fpl_entry_id == fpl_entry_id))
    trial = await start_trial_if_eligible(db, user.id, fpl_entry_id, now)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "This team was just connected by another request. Try again.")

    # register_manager commits the whole connection.
    await register_manager(db, fpl_entry_id, account.team_name)
    return {
        "status": "connected",
        **_account_dict(account),
        "trial_started": trial is not None,
        "entitlement": (await get_entitlement(db, user.id)).as_dict(),
    }


@router.delete("/fpl-accounts/{fpl_entry_id}", status_code=204)
async def disconnect_fpl_account(
    fpl_entry_id: int,
    user: AuthUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    account = await db.scalar(
        select(FplAccount).where(
            FplAccount.user_id == user.id, FplAccount.fpl_entry_id == fpl_entry_id
        )
    )
    if account is None:
        raise HTTPException(404, "That FPL team is not connected to your account")
    await db.delete(account)
    await _release_team(db, fpl_entry_id)
    return Response(status_code=204)
