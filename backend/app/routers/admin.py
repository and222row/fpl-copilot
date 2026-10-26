"""
The admin dashboard's API. Every route needs an admin account that has
verified a second factor (auth.require_admin); every action takes a written
reason and is recorded in admin_audit in the same transaction.
"""
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import Admin, AuthUser, require_admin
from app.database import get_db
from app.models.accounts import FplAccount, FplClaim
from app.models.admin import AdminAudit
from app.models.notifications import Device
from app.rate_limit import UPSTREAM, limiter
from app.services import admin as svc
from app.services import push
from app.services.accounts import delete_account_data, release_team
from app.services.revenuecat import RevenueCatUnavailable, delete_subscriber, refresh_subscription
from app.services.supabase_admin import AuthAdminUnavailable, delete_auth_user

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Admin])
logger = logging.getLogger("fpl_copilot.admin")

STATUSES = "^(TRIALING|ACTIVE|PAST_DUE|CANCELED|EXPIRED|NONE|GRANTED)$"


class Reason(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=3, max_length=500)


class Grant(Reason):
    days: int = Field(ge=1, le=365)


def _unavailable() -> HTTPException:
    return HTTPException(503, "Supabase's admin API is unavailable. Check SUPABASE_SERVICE_KEY.")


async def _exists(db: AsyncSession, user_id: uuid.UUID) -> dict:
    try:
        detail = await svc.user_detail(db, user_id)
    except AuthAdminUnavailable:
        raise _unavailable()
    if detail is None:
        raise HTTPException(404, "No such user")
    return detail


@router.get("/overview")
@limiter.limit(UPSTREAM)
async def overview(request: Request, db: AsyncSession = Depends(get_db)):
    """Users, subscribers, sign-ups, trial conversion, notifications and job health."""
    try:
        return await svc.overview(db)
    except AuthAdminUnavailable:
        raise _unavailable()


@router.get("/users")
@limiter.limit(UPSTREAM)
async def users(
    request: Request,
    q: str = Query("", max_length=120, description="Email, team name, Team ID or user id"),
    status: str | None = Query(None, pattern=STATUSES),
    page: int = Query(1, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    """Search users; emails are masked in the list and shown in full on a user's page."""
    try:
        return await svc.list_users(db, q, status, page)
    except AuthAdminUnavailable:
        raise _unavailable()


@router.get("/users/{user_id}")
@limiter.limit(UPSTREAM)
async def user(request: Request, user_id: uuid.UUID, admin: AuthUser = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """One user in full: account, team, access, billing, devices, notifications, pushes, audit."""
    detail = await _exists(db, user_id)
    # Looking someone up is recorded too: support access to personal data is.
    svc.record(db, admin.id, "view_user", user_id, "viewed in the admin dashboard")
    await db.commit()
    return detail


@router.get("/audit")
@limiter.limit(UPSTREAM)
async def audit(request: Request, limit: int = Query(100, ge=1, le=500), db: AsyncSession = Depends(get_db)):
    """The most recent admin actions, newest first."""
    rows = (await db.execute(select(AdminAudit).order_by(AdminAudit.created_at.desc()).limit(limit))).scalars().all()
    return {"entries": [svc.audit_dict(r) for r in rows]}


@router.post("/users/{user_id}/grant")
@limiter.limit(UPSTREAM)
async def grant(request: Request, user_id: uuid.UUID, body: Grant, admin: AuthUser = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """Free access for some days, on top of any free access already running."""
    await _exists(db, user_id)
    try:
        until = await svc.grant_access(db, user_id, body.days)
    except svc.ActionRefused as e:
        raise HTTPException(409, str(e))
    svc.record(db, admin.id, "grant_access", user_id, body.reason, {"days": body.days, "until": until.isoformat()})
    await db.commit()
    return {"until": until}


@router.post("/users/{user_id}/end-grant")
@limiter.limit(UPSTREAM)
async def end_grant(request: Request, user_id: uuid.UUID, body: Reason, admin: AuthUser = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """End free access granted from the dashboard."""
    await _exists(db, user_id)
    try:
        await svc.end_grant(db, user_id)
    except svc.ActionRefused as e:
        raise HTTPException(409, str(e))
    svc.record(db, admin.id, "end_grant", user_id, body.reason)
    await db.commit()
    return {"ok": True}


@router.post("/users/{user_id}/release-team")
@limiter.limit(UPSTREAM)
async def release(request: Request, user_id: uuid.UUID, body: Reason, admin: AuthUser = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """
    Disconnect the user's team so its rightful owner can connect it, for an
    ownership dispute. The team's private state goes with it, as on any
    takeover. Their trial record stays, so the team cannot get a second one.
    """
    await _exists(db, user_id)
    teams = (await db.execute(select(FplAccount.fpl_entry_id).where(FplAccount.user_id == user_id))).scalars().all()
    if not teams:
        raise HTTPException(409, "This user has no team connected.")
    for entry in teams:
        await release_team(db, entry)
    await db.execute(delete(FplAccount).where(FplAccount.user_id == user_id))
    await db.execute(delete(FplClaim).where(FplClaim.user_id == user_id))
    svc.record(db, admin.id, "release_team", user_id, body.reason, {"teams": list(teams)})
    await db.commit()
    return {"released": list(teams)}


@router.post("/users/{user_id}/sync-billing")
@limiter.limit(UPSTREAM)
async def sync_billing(request: Request, user_id: uuid.UUID, body: Reason, admin: AuthUser = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """Re-read the user's subscription from RevenueCat, when the app and the store disagree."""
    await _exists(db, user_id)
    try:
        row = await refresh_subscription(db, user_id)
    except RevenueCatUnavailable:
        raise HTTPException(503, "RevenueCat is unavailable right now.")
    svc.record(db, admin.id, "sync_billing", user_id, body.reason, {"status": row.status if row else None})
    await db.commit()
    return {"status": row.status if row else None, "provider": row.provider if row else None}


@router.post("/users/{user_id}/test-push")
@limiter.limit(UPSTREAM)
async def test_push(request: Request, user_id: uuid.UUID, body: Reason, admin: AuthUser = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """Send a test notification to the user's phones, to check delivery."""
    await _exists(db, user_id)
    tokens = (await db.execute(select(Device.token).where(Device.user_id == user_id))).scalars().all()
    if not tokens:
        raise HTTPException(409, "This user has no phone registered for notifications.")
    try:
        tickets = await push.send([push.Message(t, "FPL Copilot", "A test notification from support. Nothing needed from you.") for t in tokens])
    except push.PushUnavailable:
        raise HTTPException(503, "Expo's push service is unavailable right now.")
    sent = sum(1 for t in tickets if t.get("status") == "ok")
    svc.record(db, admin.id, "test_push", user_id, body.reason, {"devices": len(tokens), "sent": sent})
    await db.commit()
    return {"devices": len(tokens), "sent": sent}


@router.delete("/users/{user_id}")
@limiter.limit(UPSTREAM)
async def delete_user(request: Request, user_id: uuid.UUID, body: Reason, admin: AuthUser = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """
    Delete an account at the user's request, exactly as deleting it in the app
    does. The audit row is kept: it records the deletion, not the person.
    """
    if user_id == admin.id:
        raise HTTPException(409, "Delete your own account from the app, not the dashboard.")
    await _exists(db, user_id)
    await delete_account_data(db, user_id)
    svc.record(db, admin.id, "delete_account", user_id, body.reason)
    try:
        await delete_auth_user(user_id)
    except AuthAdminUnavailable:
        raise HTTPException(503, "Could not delete the sign-in account right now. Nothing was removed.")
    await db.commit()
    svc.clear_cache()
    try:
        await delete_subscriber(str(user_id))
    except RevenueCatUnavailable:
        logger.warning("RevenueCat customer not deleted", extra={"user_id": str(user_id)})
    return Response(status_code=204)
