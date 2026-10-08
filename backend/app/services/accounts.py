"""Removing a user's data: on disconnecting a team and on deleting the account."""
import uuid

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.accounts import DeletedUser, FplAccount, FplClaim, Trial, User
from app.models.billing import BillingEvent, Subscription
from app.models.feedback import RecommendationOutcome, RecommendationSnapshot, SquadOverride
from app.models.fpl import utcnow
from app.models.news import Alert, TrackedManager
from app.models.notifications import Device, NotificationPreference, PushDelivery


async def release_team(db: AsyncSession, fpl_entry_id: int) -> None:
    """Drop the private state attached to a team so its next owner inherits none."""
    await db.execute(delete(SquadOverride).where(SquadOverride.fpl_entry_id == fpl_entry_id))
    tracked = await db.get(TrackedManager, fpl_entry_id)
    if tracked is not None:
        tracked.alerts_enabled = False
        tracked.telegram_chat_id = None
        tracked.telegram_enabled = False
        tracked.telegram_linked_at = None


async def delete_account_data(db: AsyncSession, user_id: uuid.UUID) -> None:
    """
    Remove everything held about a user, without committing.

    Kept, deliberately: the trial row, with its user detached, so deleting an
    account and signing up again cannot mint a second trial for the same team;
    and the billing audit trail, with payloads redacted, since purchase
    records may have to be retained for accounting.
    """
    entries = list((await db.execute(
        select(FplAccount.fpl_entry_id).where(FplAccount.user_id == user_id)
    )).scalars())

    for entry in entries:
        await release_team(db, entry)
        await db.execute(delete(Alert).where(Alert.fpl_entry_id == entry))
        await db.execute(delete(RecommendationOutcome).where(RecommendationOutcome.fpl_entry_id == entry))
        await db.execute(delete(RecommendationSnapshot).where(RecommendationSnapshot.fpl_entry_id == entry))
        await db.execute(delete(TrackedManager).where(TrackedManager.fpl_entry_id == entry))

    await db.execute(delete(Device).where(Device.user_id == user_id))
    await db.execute(delete(NotificationPreference).where(NotificationPreference.user_id == user_id))
    await db.execute(delete(PushDelivery).where(PushDelivery.user_id == user_id))
    await db.execute(delete(FplAccount).where(FplAccount.user_id == user_id))
    await db.execute(delete(FplClaim).where(FplClaim.user_id == user_id))
    await db.execute(delete(Subscription).where(Subscription.user_id == user_id))
    await db.execute(update(Trial).where(Trial.user_id == user_id).values(user_id=None))
    await db.execute(
        update(BillingEvent)
        .where(BillingEvent.app_user_id == str(user_id))
        .values(app_user_id="deleted", payload={"redacted": True})
    )
    await db.execute(delete(User).where(User.id == user_id))
    # A deleted user's access token stays valid until it expires; the
    # tombstone stops it re-creating the account in that window.
    db.add(DeletedUser(id=user_id, deleted_at=utcnow()))
