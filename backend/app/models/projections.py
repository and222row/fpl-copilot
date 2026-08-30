from datetime import datetime
from typing import Any
from sqlalchemy import (
    Integer, String, Float, DateTime, ForeignKey, SmallInteger, JSON,
    UniqueConstraint, Boolean,
)
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base
from app.models.fpl import utcnow


class ScoringRules(Base):
    """
    FPL scoring rules, synced from bootstrap-static `game_config.scoring`.

    Blueprint requirement: season scoring rules must be data, not hardcoded
    constants, so a rules change is a sync rather than a deployment.
    Only one row is active at a time (`is_active`).
    """
    __tablename__ = "scoring_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    season: Mapped[str] = mapped_column(String(20), index=True)   # e.g. "2026_27"
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    # The raw `game_config.scoring` object, verbatim.
    rules: Mapped[Any] = mapped_column(JSON)

    # Thresholds FPL does NOT publish. Defaults below match the published
    # 2025/26+ rules; override here if FPL changes them.
    dc_threshold_def: Mapped[int] = mapped_column(SmallInteger, default=10)
    dc_threshold_mid_fwd: Mapped[int] = mapped_column(SmallInteger, default=12)
    saves_per_point: Mapped[int] = mapped_column(SmallInteger, default=3)
    goals_conceded_per_penalty: Mapped[int] = mapped_column(SmallInteger, default=2)
    long_play_minutes: Mapped[int] = mapped_column(SmallInteger, default=60)

    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class TeamStrength(Base):
    """
    Custom Fixture Difficulty Rating inputs (v1.1 blueprint enhancement).

    FPL's own FDR is a coarse 1-5 integer. We derive continuous attack and
    defence ratings by shrinking observed season performance toward FPL's
    strength priors, weighted by how many matches have been played.
    """
    __tablename__ = "team_strength"
    __table_args__ = (UniqueConstraint("team_id", "model_version", name="uq_team_strength"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    team_id: Mapped[int] = mapped_column(Integer, ForeignKey("teams.id"), index=True)
    model_version: Mapped[str] = mapped_column(String(20), index=True)

    matches_played: Mapped[int] = mapped_column(SmallInteger, default=0)

    # Expected goals scored / conceded per match, split by venue.
    attack_home: Mapped[float] = mapped_column(Float, default=1.4)
    attack_away: Mapped[float] = mapped_column(Float, default=1.1)
    defence_home: Mapped[float] = mapped_column(Float, default=1.1)
    defence_away: Mapped[float] = mapped_column(Float, default=1.4)

    # Diagnostics: what the blend was built from
    observed_scored_per_match: Mapped[float] = mapped_column(Float, default=0.0)
    observed_conceded_per_match: Mapped[float] = mapped_column(Float, default=0.0)
    prior_weight: Mapped[float] = mapped_column(Float, default=1.0)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Projection(Base):
    """
    Expected FPL points for one player in one gameweek.

    Every row carries `model_version` so projections stay reproducible and
    comparable across model releases (blueprint §11).
    """
    __tablename__ = "projections"
    __table_args__ = (
        UniqueConstraint("player_id", "gameweek_id", "model_version", name="uq_projection"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(Integer, ForeignKey("players.id"), index=True)
    gameweek_id: Mapped[int] = mapped_column(Integer, ForeignKey("gameweeks.id"), index=True)
    model_version: Mapped[str] = mapped_column(String(20), index=True)

    # ── Headline ─────────────────────────────────────────────────────────────
    xpts: Mapped[float] = mapped_column(Float, default=0.0)
    variance: Mapped[float] = mapped_column(Float, default=0.0)

    # ── Minutes ──────────────────────────────────────────────────────────────
    expected_minutes: Mapped[float] = mapped_column(Float, default=0.0)
    p_start: Mapped[float] = mapped_column(Float, default=0.0)
    p_appear: Mapped[float] = mapped_column(Float, default=0.0)
    p_60_plus: Mapped[float] = mapped_column(Float, default=0.0)
    availability_multiplier: Mapped[float] = mapped_column(Float, default=1.0)

    # ── Component breakdown (so the UI can explain the number) ───────────────
    xpts_appearance: Mapped[float] = mapped_column(Float, default=0.0)
    xpts_goals: Mapped[float] = mapped_column(Float, default=0.0)
    xpts_assists: Mapped[float] = mapped_column(Float, default=0.0)
    xpts_clean_sheet: Mapped[float] = mapped_column(Float, default=0.0)
    xpts_goals_conceded: Mapped[float] = mapped_column(Float, default=0.0)
    xpts_saves: Mapped[float] = mapped_column(Float, default=0.0)
    xpts_defensive_contribution: Mapped[float] = mapped_column(Float, default=0.0)
    xpts_bonus: Mapped[float] = mapped_column(Float, default=0.0)
    xpts_cards: Mapped[float] = mapped_column(Float, default=0.0)
    xpts_penalties: Mapped[float] = mapped_column(Float, default=0.0)

    # ── Fixture context ──────────────────────────────────────────────────────
    # A player can have 0 fixtures (blank GW) or 2+ (double GW); these
    # aggregate across all of them.
    fixture_count: Mapped[int] = mapped_column(SmallInteger, default=1)
    expected_team_goals: Mapped[float] = mapped_column(Float, default=0.0)
    expected_team_conceded: Mapped[float] = mapped_column(Float, default=0.0)
    custom_fdr: Mapped[float] = mapped_column(Float, default=3.0)
    opponents: Mapped[Any | None] = mapped_column(JSON, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ChipWindow(Base):
    """
    When each chip may be played, straight from FPL's bootstrap.

    Chips come in two sets — one for the first half of the season and one for
    the second — and an unused chip is simply lost when its window closes. That
    expiry is the whole reason chip advice is a timing problem rather than a
    scoring one: the question is never "is this a good week" but "is this good
    enough, given how many chances remain".

    Synced rather than hardcoded, for the same reason the scoring rules are:
    FPL has changed the chip structure between seasons before, and a constant
    in our code would quietly describe last season.
    """
    __tablename__ = "chip_windows"
    __table_args__ = (
        UniqueConstraint("name", "start_event", name="uq_chip_window"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(20), index=True)   # wildcard | freehit | bboost | 3xc
    chip_type: Mapped[str] = mapped_column(String(20), default="")   # transfer | team
    start_event: Mapped[int] = mapped_column(Integer)
    stop_event: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
