import uuid
from datetime import datetime
from sqlalchemy import Integer, String, DateTime, ForeignKey, UniqueConstraint, Uuid
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
    An FPL team a user has PROVED they control (see FplClaim).

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


class FplClaim(Base):
    """
    A pending request to connect a team, proved by putting `code` in the FPL
    team name.

    Kept apart from FplAccount so an unproven claim never occupies the team:
    several users may hold claims on one team, and whoever proves control wins.
    """
    __tablename__ = "fpl_claims"
    __table_args__ = (UniqueConstraint("user_id", "fpl_entry_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    fpl_entry_id: Mapped[int] = mapped_column(Integer, index=True)
    code: Mapped[str] = mapped_column(String(12))
    # The name before the user edits it, so the stored name never has the code.
    team_name: Mapped[str] = mapped_column(String(120), default="")
    manager_name: Mapped[str] = mapped_column(String(120), default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DeletedUser(Base):
    """
    Accounts that were deleted. Checked on sign-in so an access token issued
    before deletion cannot quietly re-create the account before it expires.
    """
    __tablename__ = "deleted_users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    deleted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Trial(Base):
    """
    The free trial, at most one per user and one per FPL team, ever.

    Keyed by team and kept when the user is deleted (user_id goes null), so
    deleting an account and signing up again cannot mint a second trial for the
    same team.
    """
    __tablename__ = "trials"

    fpl_entry_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), unique=True, nullable=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
