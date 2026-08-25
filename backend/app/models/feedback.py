from datetime import datetime
from typing import Any
from sqlalchemy import (
    Integer, String, Float, Boolean, DateTime, ForeignKey, JSON, Text,
    UniqueConstraint, Index,
)
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base
from app.models.fpl import utcnow


class RecommendationSnapshot(Base):
    """
    What we advised, frozen at the moment we advised it.

    Recommendations are computed on demand, so without a snapshot there is
    nothing to score afterwards — by the time a gameweek finishes, the inputs
    have moved and the model would "remember" advice it never actually gave.
    Blueprint §29: every recommendation must be reproducible from stored
    inputs and a model version.
    """
    __tablename__ = "recommendation_snapshots"
    __table_args__ = (
        UniqueConstraint("fpl_entry_id", "gameweek_id", "kind", "model_version",
                         name="uq_rec_snapshot"),
        Index("ix_rec_snapshot_entry_gw", "fpl_entry_id", "gameweek_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fpl_entry_id: Mapped[int] = mapped_column(Integer, index=True)
    gameweek_id: Mapped[int] = mapped_column(Integer, ForeignKey("gameweeks.id"), index=True)

    # captain | lineup | transfer
    kind: Mapped[str] = mapped_column(String(20), index=True)
    model_version: Mapped[str] = mapped_column(String(20))

    # The advice itself, in the shape the scorer expects for this kind.
    payload: Mapped[Any] = mapped_column(JSON)

    # What we predicted it was worth, and how sure we were.
    predicted_value: Mapped[float] = mapped_column(Float, default=0.0)
    confidence: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class RecommendationOutcome(Base):
    """
    How a recommendation actually turned out.

    Scored once the gameweek's results are in. `followed` records whether the
    manager acted on it — the override signal the blueprint calls for, and the
    input to any later risk-tolerance calibration.
    """
    __tablename__ = "recommendation_outcomes"
    __table_args__ = (
        UniqueConstraint("snapshot_id", name="uq_outcome_snapshot"),
        Index("ix_outcome_entry_gw", "fpl_entry_id", "gameweek_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("recommendation_snapshots.id"), index=True
    )
    fpl_entry_id: Mapped[int] = mapped_column(Integer, index=True)
    gameweek_id: Mapped[int] = mapped_column(Integer, ForeignKey("gameweeks.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20), index=True)
    model_version: Mapped[str] = mapped_column(String(20))

    # Did the manager act on it?
    followed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # Was it the right call, judged against what was actually available?
    # For captain this is "did we name the highest scorer in the XI".
    correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    predicted_value: Mapped[float] = mapped_column(Float, default=0.0)
    actual_value: Mapped[float] = mapped_column(Float, default=0.0)
    # actual - predicted; negative means we over-projected.
    error: Mapped[float] = mapped_column(Float, default=0.0)

    # Points forgone versus the best choice available at the time. Zero when
    # the recommendation was optimal.
    regret: Mapped[float] = mapped_column(Float, default=0.0)

    # Points the manager gained or lost by ignoring us. Null if they followed.
    override_delta: Mapped[float | None] = mapped_column(Float, nullable=True)

    detail: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")

    scored_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class SquadOverride(Base):
    """
    A manager-supplied correction to the squad we read from FPL.

    FPL's public API cannot show transfers made for a gameweek that has not
    started: `/entry/{id}/event/{gw}/picks/` 404s until the deadline passes,
    `/transfers/` omits pending moves, and `/my-team/` requires the manager's
    own login. So the newest squad we can see is the one locked at the last
    deadline — which is wrong the moment a transfer is made.

    Rather than silently advising on a stale squad, the manager can tell us what
    changed. The override applies only to its gameweek and is discarded once
    that gameweek starts, because FPL then becomes authoritative again.
    """
    __tablename__ = "squad_overrides"
    __table_args__ = (
        UniqueConstraint("fpl_entry_id", "gameweek_id", name="uq_squad_override"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fpl_entry_id: Mapped[int] = mapped_column(Integer, index=True)
    gameweek_id: Mapped[int] = mapped_column(Integer, ForeignKey("gameweeks.id"), index=True)

    # The 15 player IDs the manager actually holds now.
    player_ids: Mapped[Any] = mapped_column(JSON)

    # Bank and free transfers after the changes, in FPL tenths.
    bank: Mapped[int] = mapped_column(Integer, default=0)
    free_transfers: Mapped[int] = mapped_column(Integer, default=1)

    # What changed relative to the squad FPL reports, for display.
    transfers_applied: Mapped[Any | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
