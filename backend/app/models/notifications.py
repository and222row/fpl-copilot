import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.fpl import utcnow


class Device(Base):
    """
    An app install that can receive push notifications.

    A token identifies an install, not a person, so it belongs to whoever
    signed in on that phone most recently.
    """
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    platform: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class NotificationPreference(Base):
    """Which kinds of push a user wants. No row means everything is on."""
    __tablename__ = "notification_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    availability: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    price: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    deadline: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PushDelivery(Base):
    """
    One row per notification sent, unique per user, kind and subject, so a
    refresh every 30 minutes never sends the same alert or deadline twice.
    """
    __tablename__ = "push_deliveries"
    __table_args__ = (UniqueConstraint("user_id", "kind", "dedupe_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(20))
    dedupe_key: Mapped[str] = mapped_column(String(80))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
