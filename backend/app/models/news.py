from datetime import datetime
from typing import Any
from sqlalchemy import (
    Integer, String, Float, Boolean, DateTime, ForeignKey, SmallInteger,
    JSON, Text, Index,
)
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base
from app.models.fpl import utcnow


class AvailabilityEvent(Base):
    """
    A detected change in a player's availability.

    One row per change, not per sync — the event log is what makes alerts and
    "what changed since I last looked" possible. Every row keeps the raw news
    string as evidence so a recommendation stays auditable (blueprint §10).
    """
    __tablename__ = "availability_events"
    __table_args__ = (
        Index("ix_avail_player_detected", "player_id", "detected_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(Integer, ForeignKey("players.id"), index=True)

    # What changed
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    # status_change | chance_change | news_change | returned | departed | price_change

    status_before: Mapped[str | None] = mapped_column(String(1), nullable=True)
    status_after: Mapped[str | None] = mapped_column(String(1), nullable=True)
    availability_before: Mapped[float | None] = mapped_column(Float, nullable=True)
    availability_after: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Parsed detail
    cause: Mapped[str | None] = mapped_column(String(40), nullable=True)
    expected_return: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Evidence — the exact text this was derived from
    news_text: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(30), default="fpl_api")
    availability_source: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # How much this matters: 0-1, drives whether an alert is raised
    materiality: Mapped[float] = mapped_column(Float, default=0.0)
    requires_review: Mapped[bool] = mapped_column(Boolean, default=False)

    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class PlayerAvailabilitySnapshot(Base):
    """
    Last known availability per player.

    Change detection needs a baseline to diff against. Kept as one row per
    player (updated in place) rather than an append-only log, because the log
    is `availability_events`.
    """
    __tablename__ = "player_availability_snapshots"

    player_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("players.id"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(1), default="a")
    chance_field: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    availability: Mapped[float] = mapped_column(Float, default=1.0)
    news_text: Mapped[str] = mapped_column(Text, default="")
    now_cost: Mapped[int] = mapped_column(Integer, default=0)
    # Progress toward FPL's price-change threshold at the last sync. Needed to
    # fire an alert on the *crossing* rather than every sync while it stays
    # above the line — the percent creeps up continuously.
    price_change_percent: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Alert(Base):
    """
    A material change worth telling a user about.

    Alerts are generated per squad, so the same underlying event produces an
    alert only for managers who actually own the player.
    """
    __tablename__ = "alerts"
    __table_args__ = (
        Index("ix_alerts_manager_created", "fpl_entry_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Keyed by FPL team ID: there is no user account system yet, and this makes
    # alerts work without one.
    fpl_entry_id: Mapped[int] = mapped_column(Integer, index=True)

    event_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("availability_events.id"), nullable=True
    )
    player_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("players.id"), nullable=True
    )

    severity: Mapped[str] = mapped_column(String(10), default="info", index=True)
    # critical | warning | info

    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[Any | None] = mapped_column(JSON, nullable=True)

    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # When this alert was pushed to an external channel. Distinct from
    # `read_at`, which records the user clicking it in the UI — an alert can be
    # delivered and never read, or read without ever having been sent.
    #
    # Without this the refresh would re-send every open alert on every run:
    # ninety-six identical injury notifications a day.
    notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class TrackedManager(Base):
    """
    A team ID the app has seen.

    The scheduler needs to know whose alerts to generate. There is no account
    system, so a manager is registered the first time their squad is loaded and
    refreshed on every visit after that.
    """
    __tablename__ = "tracked_managers"

    fpl_entry_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team_name: Mapped[str] = mapped_column(String(120), default="")
    alerts_enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    # ── Telegram delivery, opt-in per manager ────────────────────────────────
    # Null until the manager completes the link from the dashboard. Storing the
    # chat id here rather than in a separate table keeps "who gets alerts" a
    # single row lookup during the refresh.
    telegram_chat_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True, index=True
    )
    # Separate from having a chat id, so "pause my alerts" does not throw away
    # the link and force the manager through Telegram again to resume.
    telegram_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    telegram_linked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class TelegramLink(Base):
    """
    A short-lived code that ties a Telegram chat to an FPL entry id.

    There is no account system, so the two identities have to be introduced to
    each other somehow. The dashboard mints a code, hands back a
    `t.me/<bot>?start=<code>` deep link, and the bot receives that code when the
    manager presses Start. Resolving it tells us which chat belongs to which
    squad.

    Single use and short lived on purpose: the code travels through a URL, and
    anyone holding it could otherwise point their own Telegram at someone
    else's squad.
    """
    __tablename__ = "telegram_links"

    code: Mapped[str] = mapped_column(String(48), primary_key=True)
    fpl_entry_id: Mapped[int] = mapped_column(Integer, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
