"""
The single answer to "may this user use premium features right now?".

Everything gated goes through `get_entitlement`; nothing asks a payment
provider directly. A paid subscription (stored from RevenueCat) takes
precedence over the trial while it lasts.

Time is always the server's clock. The client's clock never enters into it,
and neither does a subscription's stored status alone: access ends at the
stored expiry even if the store's expiry webhook never arrives.
"""
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.accounts import FplAccount, Trial
from app.models.billing import Subscription
from app.models.fpl import utcnow

TRIAL_DAYS = 30

# NONE: signed up but no team proved yet, so the trial has not started.
STATUS_NONE = "NONE"
STATUS_TRIALING = "TRIALING"
STATUS_ACTIVE = "ACTIVE"
STATUS_PAST_DUE = "PAST_DUE"
STATUS_CANCELED = "CANCELED"
STATUS_EXPIRED = "EXPIRED"


@dataclass(frozen=True)
class Entitlement:
    premium: bool
    status: str
    plan: str | None = None
    provider: str | None = None
    trial_started_at: datetime | None = None
    trial_ends_at: datetime | None = None
    subscription_ends_at: datetime | None = None
    # The team that would start a free trial if its owner proved control. Set
    # only when nothing else applies: without it, a user who connected by ID
    # and has never had a trial reads exactly like one whose trial is used up.
    prove_to_start_trial: int | None = None

    def as_dict(self) -> dict:
        return {
            "premium": self.premium,
            "status": self.status,
            "plan": self.plan,
            "provider": self.provider,
            "trial_started_at": self.trial_started_at,
            "trial_ends_at": self.trial_ends_at,
            "subscription_ends_at": self.subscription_ends_at,
            "prove_to_start_trial": self.prove_to_start_trial,
        }


def _aware(dt: datetime) -> datetime:
    # SQLite hands back naive datetimes; everything stored is UTC.
    return dt if dt.tzinfo else dt.replace(tzinfo=utcnow().tzinfo)


def _paid_access(sub: Subscription, now: datetime) -> bool:
    if sub.status == STATUS_EXPIRED:
        return False
    if sub.expires_at is None:
        return True  # lifetime
    until = max(_aware(sub.expires_at), _aware(sub.grace_expires_at or sub.expires_at))
    return now < until


async def get_entitlement(
    db: AsyncSession, user_id: uuid.UUID, now: datetime | None = None
) -> Entitlement:
    now = now or utcnow()
    trial = await db.scalar(select(Trial).where(Trial.user_id == user_id))
    sub = await db.scalar(select(Subscription).where(Subscription.user_id == user_id))
    trial_dates = (
        {"trial_started_at": _aware(trial.started_at), "trial_ends_at": _aware(trial.ends_at)}
        if trial else {}
    )
    paid = (
        {
            "plan": sub.plan,
            "provider": sub.provider,
            "subscription_ends_at": _aware(sub.expires_at) if sub.expires_at else None,
        }
        if sub else {}
    )

    if sub is not None and _paid_access(sub, now):
        return Entitlement(premium=True, status=sub.status, **paid, **trial_dates)
    if trial is not None and now < _aware(trial.ends_at):
        return Entitlement(premium=True, status=STATUS_TRIALING, provider="TRIAL", **trial_dates)
    if sub is not None:
        return Entitlement(premium=False, status=STATUS_EXPIRED, **paid, **trial_dates)
    if trial is not None:
        return Entitlement(premium=False, status=STATUS_EXPIRED, **trial_dates)

    unproven = await db.scalar(
        select(FplAccount.fpl_entry_id).where(
            FplAccount.user_id == user_id, FplAccount.verified_at.is_(None)
        )
    )
    if unproven is not None and await trial_eligible(db, user_id, unproven):
        return Entitlement(premium=False, status=STATUS_NONE, prove_to_start_trial=unproven)
    return Entitlement(premium=False, status=STATUS_NONE)


async def trial_eligible(db: AsyncSession, user_id: uuid.UUID, fpl_entry_id: int) -> bool:
    """Whether proving this team would start a trial: neither has had one."""
    used = await db.scalar(
        select(Trial.fpl_entry_id).where(
            or_(Trial.user_id == user_id, Trial.fpl_entry_id == fpl_entry_id)
        )
    )
    return used is None


async def start_trial_if_eligible(
    db: AsyncSession, user_id: uuid.UUID, fpl_entry_id: int, now: datetime | None = None
) -> Trial | None:
    """
    Start the trial when a user first proves a team, unless this user or this
    team has ever had one. Returns the new trial, or None if not eligible.

    Only ever called once control is proven. Eligibility is once per user *and*
    once per team, so starting it on an unproven connection would let anyone
    use up a stranger's trial by connecting their public team ID first, or
    collect trials with throwaway accounts and random IDs.
    """
    if not await trial_eligible(db, user_id, fpl_entry_id):
        return None
    now = now or utcnow()
    trial = Trial(
        fpl_entry_id=fpl_entry_id, user_id=user_id,
        started_at=now, ends_at=now + timedelta(days=TRIAL_DAYS),
    )
    db.add(trial)
    return trial
