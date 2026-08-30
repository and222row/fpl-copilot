"""
Shared test fixtures.

Most of the suite is pure-function unit tests that need no database — that is
deliberate, because the model, optimiser and parser logic is where the bugs
live and fast tests get run. API tests use an in-memory SQLite database via
dependency override so they need no external service.
"""
import os
import pytest
import pytest_asyncio

# Point settings at throwaway values before app modules import them.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("SECRET_KEY", "test-only-not-a-real-secret")
os.environ.setdefault("ENVIRONMENT", "test")

# Force these rather than setdefault: pydantic-settings reads backend/.env, so a
# developer enabling the scheduler locally would otherwise change test outcomes.
# A test suite that depends on local config is not a test suite.
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ["JOB_TOKEN"] = ""

# Off by default too. With it on, whether a test saw a cached response would
# depend on whether the developer happened to have Redis running locally —
# passing on one machine and failing on another. test_cache.py turns it back on
# explicitly and supplies its own Redis double.
os.environ["CACHE_ENABLED"] = "false"

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.models.fpl import Team, Player, Gameweek, Fixture  # noqa: E402
from app.models.projections import Projection, ScoringRules, TeamStrength  # noqa: E402
from datetime import datetime, timezone, timedelta  # noqa: E402


# ── Database ──────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def engine():
    """Fresh in-memory database per test."""
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine) -> AsyncSession:
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s


@pytest_asyncio.fixture
async def client(engine):
    """
    HTTP client against the real app, with the DB swapped for SQLite.

    Imported lazily so the env vars above are already in place.
    """
    from httpx import AsyncClient, ASGITransport
    from app.main import app

    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with maker() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


# ── Builders ──────────────────────────────────────────────────────────────────

def make_player(
    player_id: int = 1,
    *,
    team_id: int = 1,
    position: int = 3,
    now_cost: int = 55,
    web_name: str = "Test",
    status: str = "a",
    minutes: int = 900,
    starts: int = 10,
    news: str = "",
    chance: int | None = None,
    xg90: float = 0.2,
    xa90: float = 0.15,
    dc90: float = 4.0,
    saves90: float = 0.0,
    bonus: int = 3,
    yellow: int = 1,
    penalties_order: int | None = None,
) -> Player:
    """A player with sane defaults; override only what the test cares about."""
    return Player(
        id=player_id,
        team_id=team_id,
        first_name="Test",
        second_name=web_name,
        web_name=web_name,
        position=position,
        now_cost=now_cost,
        status=status,
        minutes=minutes,
        starts=starts,
        news=news,
        chance_of_playing_this_round=chance,
        expected_goals_per_90=xg90,
        expected_assists_per_90=xa90,
        defensive_contribution_per_90=dc90,
        saves_per_90=saves90,
        bonus=bonus,
        yellow_cards=yellow,
        penalties_order=penalties_order,
        total_points=50,
        form=3.0,
        selected_by_percent=10.0,
    )


def make_fixture(
    fixture_id: int = 1,
    *,
    gameweek_id: int = 1,
    team_h: int = 1,
    team_a: int = 2,
    finished: bool = False,
    finished_provisional: bool = False,
    h_score: int | None = None,
    a_score: int | None = None,
) -> Fixture:
    return Fixture(
        id=fixture_id,
        gameweek_id=gameweek_id,
        team_h=team_h,
        team_a=team_a,
        team_h_score=h_score,
        team_a_score=a_score,
        finished=finished,
        finished_provisional=finished_provisional,
        started=finished or finished_provisional,
        kickoff_time=datetime(2026, 8, 21, 19, 0, tzinfo=timezone.utc),
    )


def make_team(team_id: int = 1, short: str = "TST", strength: int = 1150) -> Team:
    return Team(
        id=team_id,
        name=f"Team {team_id}",
        short_name=short,
        strength=3,
        strength_attack_home=strength,
        strength_attack_away=strength,
        strength_defence_home=strength,
        strength_defence_away=strength,
    )


# GW1's deadline sits this far behind now, putting GW2's a few days ahead.
GW1_DEADLINE_DAYS_AGO = 3


def make_gameweek(gw_id: int = 1, *, is_current: bool = False,
                  is_next: bool = False, finished: bool = False) -> Gameweek:
    """
    Seed a gameweek whose deadline is positioned relative to now.

    The deadlines used to be pinned to real dates — GW1 on 21 Aug 2026, GW2 a
    week later. That held until 28 Aug actually arrived, at which point every
    seeded deadline was in the past, `get_next_open_gameweek` fell back to the
    active gameweek, and `test_gameweek_returns_the_next_open_deadline` began
    failing on a nightly run days after anyone had touched the code.

    What those tests mean is relative — "GW1 is locked, GW2 is the one to
    target" — so the data has to be relative too, or the suite has an expiry
    date. `kickoff_time` is left absolute deliberately: nothing compares it to
    the clock, it only orders fixtures.
    """
    return Gameweek(
        id=gw_id,
        name=f"Gameweek {gw_id}",
        deadline_time=datetime.now(timezone.utc)
        - timedelta(days=GW1_DEADLINE_DAYS_AGO)
        + timedelta(days=7 * (gw_id - 1)),
        finished=finished,
        is_current=is_current,
        is_next=is_next,
    )


def make_projection(
    player_id: int,
    gameweek_id: int = 1,
    *,
    xpts: float = 4.0,
    p_start: float = 1.0,
    expected_minutes: float = 82.0,
    variance: float = 2.0,
    model_version: str = "proj-v1",
) -> Projection:
    return Projection(
        player_id=player_id,
        gameweek_id=gameweek_id,
        model_version=model_version,
        xpts=xpts,
        variance=variance,
        expected_minutes=expected_minutes,
        p_start=p_start,
        p_appear=min(1.0, p_start + 0.1),
        p_60_plus=p_start * 0.88,
        availability_multiplier=1.0,
        updated_at=datetime.now(timezone.utc),
    )
