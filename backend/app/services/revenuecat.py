"""
Reading subscription state from RevenueCat.

RevenueCat sits in front of the App Store and Google Play and validates their
receipts. This module asks its REST API what a customer is entitled to; that
answer, never a webhook body or anything the app sends, is what reaches the
database.
"""
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.billing import Subscription
from app.models.fpl import utcnow
from app.services.upstreams import monitored

logger = logging.getLogger("fpl_copilot.billing")

STORE_PROVIDERS = {
    "app_store": "APPLE",
    "mac_app_store": "APPLE",
    "play_store": "GOOGLE",
    "stripe": "STRIPE",
    "promotional": "PROMOTIONAL",
}


class RevenueCatUnavailable(Exception):
    """RevenueCat could not be reached or refused the request."""


@dataclass(frozen=True)
class SubscriptionState:
    provider: str
    status: str
    plan: str | None
    product_id: str
    expires_at: datetime | None
    grace_expires_at: datetime | None
    is_sandbox: bool
    management_url: str | None


def _parse_time(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def plan_for(product_id: str) -> str | None:
    """
    MONTHLY or ANNUAL from the product identifier. Store product IDs must
    contain "monthly" or "annual"/"yearly"; anything else is reported as None
    rather than guessed.
    """
    p = product_id.lower()
    if "annual" in p or "yearly" in p:
        return "ANNUAL"
    if "monthly" in p:
        return "MONTHLY"
    return None


def parse_subscriber(body: dict, now: datetime | None = None) -> SubscriptionState | None:
    """
    The premium subscription in a GET /subscribers response, or None if the
    customer has never held the entitlement.
    """
    now = now or utcnow()
    subscriber = body.get("subscriber") or {}
    entitlement = (subscriber.get("entitlements") or {}).get(settings.revenuecat_entitlement_id)
    if not entitlement:
        return None

    product_id = entitlement.get("product_identifier") or ""
    sub = (subscriber.get("subscriptions") or {}).get(product_id) or {}
    expires = _parse_time(entitlement.get("expires_date"))
    grace = _parse_time(entitlement.get("grace_period_expires_date"))
    access_until = max(d for d in (expires, grace) if d) if (expires or grace) else None

    lifetime = expires is None and "expires_date" in entitlement
    if lifetime or (access_until and access_until > now):
        if sub.get("billing_issues_detected_at"):
            status = "PAST_DUE"
        elif sub.get("unsubscribe_detected_at"):
            status = "CANCELED"      # still paid up until it expires
        else:
            status = "ACTIVE"
    else:
        status = "EXPIRED"

    return SubscriptionState(
        provider=STORE_PROVIDERS.get(sub.get("store", ""), (sub.get("store") or "UNKNOWN").upper()),
        status=status,
        plan=plan_for(product_id),
        product_id=product_id,
        expires_at=expires,
        grace_expires_at=grace,
        is_sandbox=bool(sub.get("is_sandbox", False)),
        management_url=subscriber.get("management_url"),
    )


async def fetch_subscriber(app_user_id: str) -> dict:
    """GET /subscribers/{id} with the secret key."""
    if not settings.revenuecat_secret_key:
        raise RevenueCatUnavailable("REVENUECAT_SECRET_KEY is not set")
    url = f"{settings.revenuecat_api_base}/subscribers/{quote(app_user_id, safe='')}"
    try:
        async with httpx.AsyncClient(timeout=10.0, transport=monitored("revenuecat")) as client:
            response = await client.get(
                url, headers={"Authorization": f"Bearer {settings.revenuecat_secret_key}"}
            )
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, ValueError) as e:
        raise RevenueCatUnavailable(str(e)) from e


async def delete_subscriber(app_user_id: str) -> None:
    """Delete a customer's data at RevenueCat. 404 (already gone) counts as done."""
    if not settings.revenuecat_secret_key:
        raise RevenueCatUnavailable("REVENUECAT_SECRET_KEY is not set")
    url = f"{settings.revenuecat_api_base}/subscribers/{quote(app_user_id, safe='')}"
    try:
        async with httpx.AsyncClient(timeout=10.0, transport=monitored("revenuecat")) as client:
            response = await client.delete(
                url, headers={"Authorization": f"Bearer {settings.revenuecat_secret_key}"}
            )
    except httpx.HTTPError as e:
        raise RevenueCatUnavailable(str(e)) from e
    if response.status_code not in (200, 404):
        raise RevenueCatUnavailable(f"RevenueCat returned {response.status_code}")


async def refresh_subscription(db: AsyncSession, user_id: uuid.UUID) -> Subscription | None:
    """Re-read one user's state from RevenueCat and store it."""
    body = await fetch_subscriber(str(user_id))
    state = parse_subscriber(body)
    if state is None:
        others = sorted(((body.get("subscriber") or {}).get("entitlements") or {}).keys())
        if others:
            # A paying customer whose entitlement has another name: the
            # purchase would silently grant nothing. Seen when the RevenueCat
            # entitlement was created as something other than the default.
            logger.error(
                "RevenueCat entitlement not found; check REVENUECAT_ENTITLEMENT_ID",
                extra={"expected": settings.revenuecat_entitlement_id, "found": others},
            )
    row = await db.scalar(select(Subscription).where(Subscription.user_id == user_id))
    if state is None:
        # Never subscribed, or RevenueCat no longer lists the entitlement.
        if row is not None:
            row.status = "EXPIRED"
            row.synced_at = utcnow()
        return row

    if row is None:
        row = Subscription(user_id=user_id)
        db.add(row)
    row.provider = state.provider
    row.status = state.status
    row.plan = state.plan
    row.product_id = state.product_id
    row.expires_at = state.expires_at
    row.grace_expires_at = state.grace_expires_at
    row.is_sandbox = state.is_sandbox
    row.management_url = state.management_url
    row.synced_at = utcnow()
    logger.info(
        "subscription refreshed",
        extra={"user_id": str(user_id), "status": state.status, "provider": state.provider},
    )
    return row
