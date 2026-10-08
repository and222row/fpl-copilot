import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.fpl import utcnow


class Subscription(Base):
    """
    A user's paid subscription as last confirmed with the store, via RevenueCat.

    Written only from RevenueCat's REST API, never from a webhook body or the
    app. Access is decided from `expires_at` against the server clock at read
    time, so a late or lost expiry webhook cannot extend it.
    """
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    provider: Mapped[str] = mapped_column(String(20))      # APPLE | GOOGLE | STRIPE | PROMOTIONAL
    status: Mapped[str] = mapped_column(String(20))        # ACTIVE | PAST_DUE | CANCELED | EXPIRED
    plan: Mapped[str | None] = mapped_column(String(20), nullable=True)  # MONTHLY | ANNUAL
    product_id: Mapped[str] = mapped_column(String(120), default="")
    # Null means a lifetime entitlement.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    grace_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_sandbox: Mapped[bool] = mapped_column(Boolean, default=False)
    management_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BillingEvent(Base):
    """
    Every webhook delivery, kept as the audit trail and the idempotency key.

    `processed_at` stays null until the user's state has been refreshed, so a
    failed delivery is reprocessed when RevenueCat retries it rather than being
    mistaken for a duplicate.
    """
    __tablename__ = "billing_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    event_type: Mapped[str] = mapped_column(String(60))
    app_user_id: Mapped[str] = mapped_column(String(120), default="")
    environment: Mapped[str] = mapped_column(String(20), default="")
    payload: Mapped[Any] = mapped_column(JSON)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
