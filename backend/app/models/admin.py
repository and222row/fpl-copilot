import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.fpl import utcnow


class AdminAudit(Base):
    """
    One row per admin action: who did what to whom, when and why. Written in
    the same transaction as the action, never updated or deleted by the app,
    and kept when the target account is deleted (the user id is not a foreign
    key, so the record of the deletion outlives the user).
    """
    __tablename__ = "admin_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    admin_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    action: Mapped[str] = mapped_column(String(40))
    target_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    reason: Mapped[str] = mapped_column(Text)
    detail: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
