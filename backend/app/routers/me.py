import logging
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
from app.models.fpl import utcnow
from app.models.notifications import Device, NotificationPreference
from app.rate_limit import UPSTREAM, limiter
from app.services.accounts import delete_account_data, release_team
from app.services.entitlements import get_entitlement, start_trial_if_eligible
from app.services.fpl_client import fetch_manager_info, fetch_manager_info_fresh
from app.services.jobs import register_manager
from app.services.push import KINDS as PUSH_KINDS, TOKEN_PATTERN
from app.services.revenuecat import RevenueCatUnavailable, delete_subscriber
from app.services.supabase_admin import AuthAdminUnavailable, delete_auth_user

router = APIRouter(prefix="/me", tags=["me"])
logger = logging.getLogger("fpl_copilot.accounts")

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
        await release_team(db, fpl_entry_id)
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
    await release_team(db, fpl_entry_id)
    return Response(status_code=204)


# ── Push devices and preferences ─────────────────────────────────────────────

MAX_DEVICES_PER_USER = 10


class RegisterDevice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=20, max_length=200)
    platform: str = Field(pattern="^(ios|android)$")


class NotificationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    availability: bool | None = None
    price: bool | None = None
    deadline: bool | None = None


def _prefs_dict(p: NotificationPreference | None) -> dict:
    return {k: (True if p is None else getattr(p, k)) for k in PUSH_KINDS}


@router.put("/devices", status_code=204)
async def register_device(
    body: RegisterDevice,
    user: AuthUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Register this install for push. A token already registered to someone else
    moves to the caller: the token identifies the phone, and its newest
    signed-in user is who should get its notifications.
    """
    if not TOKEN_PATTERN.match(body.token):
        raise HTTPException(422, "Not an Expo push token")
    now = utcnow()
    device = await db.scalar(select(Device).where(Device.token == body.token))
    if device is None:
        db.add(Device(user_id=user.id, token=body.token, platform=body.platform, created_at=now, last_seen_at=now))
    else:
        device.user_id = user.id
        device.platform = body.platform
        device.last_seen_at = now
    await db.flush()

    # Bound how many installs one account can attach.
    stale = (await db.execute(
        select(Device.id).where(Device.user_id == user.id)
        .order_by(Device.last_seen_at.desc()).offset(MAX_DEVICES_PER_USER)
    )).scalars().all()
    if stale:
        await db.execute(delete(Device).where(Device.id.in_(stale)))
    return Response(status_code=204)


@router.delete("/devices/{token}", status_code=204)
async def unregister_device(
    token: str,
    user: AuthUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """Stop pushes to this install, called on sign-out. Only your own devices."""
    result = await db.execute(delete(Device).where(Device.token == token, Device.user_id == user.id))
    if result.rowcount == 0:
        raise HTTPException(404, "Device not registered to this account")
    return Response(status_code=204)


@router.get("/notifications")
async def get_notification_settings(user: AuthUser = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return _prefs_dict(await db.get(NotificationPreference, user.id))


@router.put("/notifications")
async def update_notification_settings(
    body: NotificationSettings,
    user: AuthUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    prefs = await db.get(NotificationPreference, user.id)
    if prefs is None:
        prefs = NotificationPreference(user_id=user.id)
        db.add(prefs)
    for kind, value in body.model_dump(exclude_none=True).items():
        setattr(prefs, kind, value)
    prefs.updated_at = utcnow()
    await db.flush()
    return _prefs_dict(prefs)


@router.delete("", status_code=204)
@limiter.limit(UPSTREAM)
async def delete_account(
    request: Request,
    user: AuthUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Permanently delete the account and the data held about it.

    Local deletions are staged first and committed only once Supabase has
    deleted the sign-in identity, so a failure leaves the account intact
    rather than half-deleted. A store subscription is not cancelled by this:
    only the user can cancel it in the store, and the app says so first.
    """
    await delete_account_data(db, user.id)
    try:
        await delete_auth_user(user.id)
    except AuthAdminUnavailable:
        logger.warning("account deletion aborted: auth admin unavailable")
        raise HTTPException(503, "Could not delete your account right now. Nothing was removed; please try again.")
    await db.commit()

    try:
        await delete_subscriber(str(user.id))
    except RevenueCatUnavailable:
        # The account is gone and RevenueCat holds only an unguessable id that
        # nobody can sign in as; logged for follow-up rather than failing.
        logger.warning("RevenueCat customer not deleted", extra={"user_id": str(user.id)})
    logger.info("account deleted", extra={"user_id": str(user.id)})
    return Response(status_code=204)
