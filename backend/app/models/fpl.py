from datetime import datetime, timezone
from typing import Any
from sqlalchemy import (
    Integer, String, Float, Boolean, DateTime,
    ForeignKey, SmallInteger, Text, JSON, UniqueConstraint
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


def utcnow() -> datetime:
    """Timezone-aware UTC now. FPL timestamps are UTC, so we stay aware throughout."""
    return datetime.now(timezone.utc)


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # FPL team ID
    name: Mapped[str] = mapped_column(String(100))
    short_name: Mapped[str] = mapped_column(String(10))
    strength: Mapped[int] = mapped_column(SmallInteger, default=0)
    strength_overall_home: Mapped[int] = mapped_column(SmallInteger, default=0)
    strength_overall_away: Mapped[int] = mapped_column(SmallInteger, default=0)
    strength_attack_home: Mapped[int] = mapped_column(SmallInteger, default=0)
    strength_attack_away: Mapped[int] = mapped_column(SmallInteger, default=0)
    strength_defence_home: Mapped[int] = mapped_column(SmallInteger, default=0)
    strength_defence_away: Mapped[int] = mapped_column(SmallInteger, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    players: Mapped[list["Player"]] = relationship("Player", back_populates="team")


class Player(Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # FPL element ID
    team_id: Mapped[int] = mapped_column(Integer, ForeignKey("teams.id"), index=True)
    first_name: Mapped[str] = mapped_column(String(100))
    second_name: Mapped[str] = mapped_column(String(100))
    web_name: Mapped[str] = mapped_column(String(100), index=True)
    # FPL's own image ID. Photos live at
    # resources.premierleague.com/premierleague/photos/players/110x140/p{code}.png
    code: Mapped[int] = mapped_column(Integer, default=0)
    # position: 1=GK 2=DEF 3=MID 4=FWD  (FPL calls this element_type)
    position: Mapped[int] = mapped_column(SmallInteger, index=True)
    now_cost: Mapped[int] = mapped_column(Integer)          # tenths of £ (65 = £6.5m)
    total_points: Mapped[int] = mapped_column(Integer, default=0)
    form: Mapped[float] = mapped_column(Float, default=0.0)
    selected_by_percent: Mapped[float] = mapped_column(Float, default=0.0)
    # status: a=available d=doubtful i=injured s=suspended u=unavailable n=not in squad
    status: Mapped[str] = mapped_column(String(1), default="a", index=True)
    chance_of_playing_this_round: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    chance_of_playing_next_round: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    news: Mapped[str] = mapped_column(Text, default="")
    ep_this: Mapped[float] = mapped_column(Float, default=0.0)   # FPL's own expected pts
    ep_next: Mapped[float] = mapped_column(Float, default=0.0)
    minutes: Mapped[int] = mapped_column(Integer, default=0)
    starts: Mapped[int] = mapped_column(Integer, default=0)
    goals_scored: Mapped[int] = mapped_column(Integer, default=0)
    assists: Mapped[int] = mapped_column(Integer, default=0)
    clean_sheets: Mapped[int] = mapped_column(Integer, default=0)
    goals_conceded: Mapped[int] = mapped_column(Integer, default=0)
    yellow_cards: Mapped[int] = mapped_column(Integer, default=0)
    red_cards: Mapped[int] = mapped_column(Integer, default=0)
    saves: Mapped[int] = mapped_column(Integer, default=0)
    bonus: Mapped[int] = mapped_column(Integer, default=0)
    bps: Mapped[int] = mapped_column(Integer, default=0)
    influence: Mapped[float] = mapped_column(Float, default=0.0)
    creativity: Mapped[float] = mapped_column(Float, default=0.0)
    threat: Mapped[float] = mapped_column(Float, default=0.0)
    ict_index: Mapped[float] = mapped_column(Float, default=0.0)
    own_goals: Mapped[int] = mapped_column(Integer, default=0)
    penalties_saved: Mapped[int] = mapped_column(Integer, default=0)
    penalties_missed: Mapped[int] = mapped_column(Integer, default=0)
    expected_goals: Mapped[float] = mapped_column(Float, default=0.0)
    expected_assists: Mapped[float] = mapped_column(Float, default=0.0)
    expected_goal_involvements: Mapped[float] = mapped_column(Float, default=0.0)
    expected_goals_conceded: Mapped[float] = mapped_column(Float, default=0.0)
    transfers_in_event: Mapped[int] = mapped_column(Integer, default=0)
    transfers_out_event: Mapped[int] = mapped_column(Integer, default=0)

    # ── Defensive contribution (2025/26+ scoring) ────────────────────────────
    # `defensive_contribution` is the RAW stat count (CBIT for DEF,
    # CBIRT for MID/FWD), not the points awarded.
    clearances_blocks_interceptions: Mapped[int] = mapped_column(Integer, default=0)
    recoveries: Mapped[int] = mapped_column(Integer, default=0)
    tackles: Mapped[int] = mapped_column(Integer, default=0)
    defensive_contribution: Mapped[int] = mapped_column(Integer, default=0)

    # ── Per-90 rates (FPL-computed; the projection model's main inputs) ──────
    starts_per_90: Mapped[float] = mapped_column(Float, default=0.0)
    expected_goals_per_90: Mapped[float] = mapped_column(Float, default=0.0)
    expected_assists_per_90: Mapped[float] = mapped_column(Float, default=0.0)
    expected_goals_conceded_per_90: Mapped[float] = mapped_column(Float, default=0.0)
    goals_conceded_per_90: Mapped[float] = mapped_column(Float, default=0.0)
    clean_sheets_per_90: Mapped[float] = mapped_column(Float, default=0.0)
    saves_per_90: Mapped[float] = mapped_column(Float, default=0.0)
    defensive_contribution_per_90: Mapped[float] = mapped_column(Float, default=0.0)
    points_per_game: Mapped[float] = mapped_column(Float, default=0.0)

    # ── Set-piece roles (v1.1 blueprint signal; 1 = first choice) ───────────
    penalties_order: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    corners_freekicks_order: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    direct_freekicks_order: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    # ── Price change (deterministic — FPL publishes its own projections) ────
    price_change_percent: Mapped[float] = mapped_column(Float, default=0.0)
    price_change_hourly_rate: Mapped[int] = mapped_column(Integer, default=0)
    price_change_projections: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    price_change_locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cost_change_event: Mapped[int] = mapped_column(Integer, default=0)
    cost_change_start: Mapped[int] = mapped_column(Integer, default=0)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    team: Mapped["Team"] = relationship("Team", back_populates="players")

    @property
    def is_penalty_taker(self) -> bool:
        return self.penalties_order == 1

    @property
    def net_transfers(self) -> int:
        return self.transfers_in_event - self.transfers_out_event


class Gameweek(Base):
    __tablename__ = "gameweeks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)   # GW number
    name: Mapped[str] = mapped_column(String(50))
    deadline_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished: Mapped[bool] = mapped_column(Boolean, default=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_next: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_previous: Mapped[bool] = mapped_column(Boolean, default=False)
    average_entry_score: Mapped[int] = mapped_column(Integer, default=0)
    highest_score: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    fixtures: Mapped[list["Fixture"]] = relationship("Fixture", back_populates="gameweek")


class Fixture(Base):
    __tablename__ = "fixtures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)   # FPL fixture ID
    gameweek_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("gameweeks.id"), nullable=True, index=True
    )
    kickoff_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    team_h: Mapped[int] = mapped_column(Integer, ForeignKey("teams.id"), index=True)
    team_a: Mapped[int] = mapped_column(Integer, ForeignKey("teams.id"), index=True)
    team_h_score: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    team_a_score: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    team_h_difficulty: Mapped[int] = mapped_column(SmallInteger, default=3)
    team_a_difficulty: Mapped[int] = mapped_column(SmallInteger, default=3)

    # FPL has three distinct states and they are easy to confuse:
    #   started              = kick-off has happened
    #   finished_provisional = match over, bonus points not yet confirmed
    #   finished             = FPL has verified the data (can lag by days)
    # Anything reading "has this match been played?" must use
    # `finished_provisional`, not `finished`.
    finished: Mapped[bool] = mapped_column(Boolean, default=False)
    finished_provisional: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    started: Mapped[bool] = mapped_column(Boolean, default=False)
    minutes: Mapped[int] = mapped_column(SmallInteger, default=0)

    gameweek: Mapped["Gameweek | None"] = relationship("Gameweek", back_populates="fixtures")

    @property
    def is_played(self) -> bool:
        """True once the match has actually been played, bonus pending or not."""
        return bool(
            (self.finished or self.finished_provisional)
            and self.team_h_score is not None
            and self.team_a_score is not None
        )


class PlayerGameweekStat(Base):
    """
    Per-player, per-gameweek actual results, from /element-summary/{id}/.

    This is the ground truth the backtest harness scores projections against.
    """
    __tablename__ = "player_gameweek_stats"
    __table_args__ = (
        UniqueConstraint("player_id", "gameweek_id", "fixture_id", name="uq_pgs_player_gw_fixture"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(Integer, ForeignKey("players.id"), index=True)
    gameweek_id: Mapped[int] = mapped_column(Integer, ForeignKey("gameweeks.id"), index=True)
    fixture_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    opponent_team: Mapped[int | None] = mapped_column(Integer, nullable=True)
    was_home: Mapped[bool] = mapped_column(Boolean, default=False)

    total_points: Mapped[int] = mapped_column(Integer, default=0)
    minutes: Mapped[int] = mapped_column(Integer, default=0)
    starts: Mapped[int] = mapped_column(Integer, default=0)
    goals_scored: Mapped[int] = mapped_column(Integer, default=0)
    assists: Mapped[int] = mapped_column(Integer, default=0)
    clean_sheets: Mapped[int] = mapped_column(Integer, default=0)
    goals_conceded: Mapped[int] = mapped_column(Integer, default=0)
    own_goals: Mapped[int] = mapped_column(Integer, default=0)
    penalties_saved: Mapped[int] = mapped_column(Integer, default=0)
    penalties_missed: Mapped[int] = mapped_column(Integer, default=0)
    yellow_cards: Mapped[int] = mapped_column(Integer, default=0)
    red_cards: Mapped[int] = mapped_column(Integer, default=0)
    saves: Mapped[int] = mapped_column(Integer, default=0)
    bonus: Mapped[int] = mapped_column(Integer, default=0)
    bps: Mapped[int] = mapped_column(Integer, default=0)
    defensive_contribution: Mapped[int] = mapped_column(Integer, default=0)
    expected_goals: Mapped[float] = mapped_column(Float, default=0.0)
    expected_assists: Mapped[float] = mapped_column(Float, default=0.0)
    expected_goals_conceded: Mapped[float] = mapped_column(Float, default=0.0)
    value: Mapped[int] = mapped_column(Integer, default=0)   # price at the time
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
