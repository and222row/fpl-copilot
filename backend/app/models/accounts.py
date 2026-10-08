import uuid
from datetime import datetime
from sqlalchemy import Integer, String, DateTime, ForeignKey, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base
from app.models.fpl import utcnow


class User(Base):
    """
    An authenticated person, keyed by the Supabase Auth user id (`sub`).

    Email and phone deliberately live only in Supabase's `auth.users`: copying
    them here would double the PII we have to protect and delete.
    """
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FplAccount(Base):
    """
    An FPL team a user has connected.

    `fpl_entry_id` is unique: squad overrides and alerts are stored per team,
    so two users sharing one team would see and overwrite each other's pending
    transfers.
    """
    __tablename__ = "fpl_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    fpl_entry_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    team_name: Mapped[str] = mapped_column(String(120), default="")
    manager_name: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
