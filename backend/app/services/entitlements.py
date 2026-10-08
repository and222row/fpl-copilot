"""
The single answer to "may this user use premium features right now?".

Everything gated goes through `get_entitlement`; nothing asks a payment
provider directly. Only trials exist so far. Paid subscriptions (Apple, Google,
Stripe) will feed the same function once the payment architecture is approved.

Time is always the server's clock. The client's clock never enters into it.
"""
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.accounts import Trial
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

    def as_dict(self) -> dict:
        return {
            "premium": self.premium,
            "status": self.status,
            "plan": self.plan,
            "provider": self.provider,
            "trial_started_at": self.trial_started_at,
            "trial_ends_at": self.trial_ends_at,
            "subscription_ends_at": self.subscription_ends_at,
        }


def _aware(dt: datetime) -> datetime:
    # SQLite hands back naive datetimes; everything stored is UTC.
    return dt if dt.tzinfo else dt.replace(tzinfo=utcnow().tzinfo)


async def get_entitlement(
    db: AsyncSession, user_id: uuid.UUID, now: datetime | None = None
) -> Entitlement:
    now = now or utcnow()
    trial = await db.scalar(select(Trial).where(Trial.user_id == user_id))
    if trial is None:
        return Entitlement(premium=False, status=STATUS_NONE)

    started, ends = _aware(trial.started_at), _aware(trial.ends_at)
    if now < ends:
        return Entitlement(
            premium=True, status=STATUS_TRIALING, provider="TRIAL",
            trial_started_at=started, trial_ends_at=ends,
        )
    return Entitlement(
        premium=False, status=STATUS_EXPIRED,
        trial_started_at=started, trial_ends_at=ends,
    )


async def start_trial_if_eligible(
    db: AsyncSession, user_id: uuid.UUID, fpl_entry_id: int, now: datetime | None = None
) -> Trial | None:
    """
    Start the trial when a user first proves a team, unless this user or this
    team has ever had one. Returns the new trial, or None if not eligible.
    """
    used = await db.scalar(
        select(Trial.fpl_entry_id).where(
            or_(Trial.user_id == user_id, Trial.fpl_entry_id == fpl_entry_id)
        )
    )
    if used is not None:
        return None
    now = now or utcnow()
    trial = Trial(
        fpl_entry_id=fpl_entry_id, user_id=user_id,
        started_at=now, ends_at=now + timedelta(days=TRIAL_DAYS),
    )
    db.add(trial)
    return trial
