"""
Store billing: RevenueCat's webhook and the app's post-purchase sync.

Neither trusts what it is told. The webhook is authenticated, then used only
as a cue to re-read the customer from RevenueCat; the sync takes no input at
all beyond the caller's verified identity.
"""
import hashlib
import hmac
import logging
import secrets
import time
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthUser, current_user
from app.config import settings
from app.database import get_db
from app.models.accounts import User
from app.models.billing import BillingEvent
from app.models.fpl import utcnow
from app.rate_limit import UPSTREAM, limiter
from app.services.entitlements import get_entitlement
from app.services.revenuecat import RevenueCatUnavailable, refresh_subscription

logger = logging.getLogger("fpl_copilot.billing")

router = APIRouter(prefix="/billing", tags=["billing"])

MAX_BODY_BYTES = 64 * 1024
# A signed delivery older than this is refused, so a captured one cannot be
# replayed later. RevenueCat signs each attempt, retries included.
SIGNATURE_TOLERANCE_SECONDS = 300


class _Event(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    type: str
    app_user_id: str | None = None
    original_app_user_id: str | None = None
    aliases: list[str] = []
    transferred_from: list[str] = []
    transferred_to: list[str] = []
    environment: str = ""


class _Envelope(BaseModel):
    model_config = ConfigDict(extra="allow")
    event: _Event


def _verify_signature(header: str | None, raw: bytes, now: float) -> bool:
    if not header:
        return False
    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    try:
        timestamp = int(parts["t"])
        signature = parts["v1"]
    except (KeyError, ValueError):
        return False
    if abs(now - timestamp) > SIGNATURE_TOLERANCE_SECONDS:
        return False
    expected = hmac.new(
        settings.revenuecat_webhook_signing_secret.encode(),
        f"{timestamp}.".encode() + raw,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def _affected_ids(event: _Event) -> set[uuid.UUID]:
    """Our user ids touched by an event. Anonymous RevenueCat ids are skipped."""
    raw = (
        [*event.transferred_from, *event.transferred_to]
        if event.type == "TRANSFER"
        else [event.app_user_id, event.original_app_user_id, *event.aliases]
    )
    ids = set()
    for value in raw:
        try:
            ids.add(uuid.UUID(str(value)))
        except ValueError:
            continue
    return ids


@router.post("/revenuecat/webhook", include_in_schema=False)
async def revenuecat_webhook(
    request: Request,
    authorization: str | None = Header(None),
    x_revenuecat_webhook_signature: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
):
    if not settings.revenuecat_webhook_auth:
        raise HTTPException(503, "Billing webhook is not configured")
    if not authorization or not secrets.compare_digest(authorization, settings.revenuecat_webhook_auth):
        raise HTTPException(401, "Invalid webhook authorization")

    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        raise HTTPException(413, "Payload too large")
    if settings.revenuecat_webhook_signing_secret and not _verify_signature(
        x_revenuecat_webhook_signature, raw, time.time()
    ):
        raise HTTPException(401, "Invalid webhook signature")

    try:
        envelope = _Envelope.model_validate_json(raw)
    except ValidationError:
        raise HTTPException(400, "Malformed webhook payload")
    event = envelope.event

    record = await db.scalar(select(BillingEvent).where(BillingEvent.event_id == event.id))
    if record is not None and record.processed_at is not None:
        return {"status": "duplicate"}
    if record is None:
        record = BillingEvent(
            event_id=event.id,
            event_type=event.type,
            app_user_id=(event.app_user_id or "")[:120],
            environment=event.environment[:20],
            payload=envelope.model_dump(mode="json"),
        )
        db.add(record)
        try:
            await db.flush()
        except IntegrityError:
            # A concurrent delivery of the same event got there first.
            await db.rollback()
            return {"status": "duplicate"}

    known = set((await db.execute(
        select(User.id).where(User.id.in_(_affected_ids(event)))
    )).scalars())

    try:
        for user_id in known:
            await refresh_subscription(db, user_id)
    except RevenueCatUnavailable as e:
        record.error = str(e)[:2000]
        await db.commit()
        logger.warning("webhook refresh failed; RevenueCat will retry", extra={"event_type": event.type})
        # Not 200, so RevenueCat retries with backoff.
        raise HTTPException(502, "Could not confirm the subscription with RevenueCat")

    record.processed_at = utcnow()
    record.error = None
    return {"status": "processed", "users_refreshed": len(known)}


@router.post("/sync")
@limiter.limit(UPSTREAM)
async def sync_after_purchase(
    request: Request,
    user: AuthUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Called by the app right after a purchase or restore, so access does not
    wait for the webhook. Reads the caller's own state from RevenueCat; the
    app cannot say what it bought or for whom.
    """
    try:
        await refresh_subscription(db, user.id)
    except RevenueCatUnavailable:
        raise HTTPException(503, "Could not reach the store right now. Your purchase is safe; try again shortly.")
    await db.flush()
    return (await get_entitlement(db, user.id)).as_dict()
