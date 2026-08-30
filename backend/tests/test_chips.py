"""
Chip timing.

Weighted toward the layers that can be trusted. Fixture shape is counting and
is tested exhaustively; the stopping rule is a stated heuristic and is tested
for the behaviour that matters — that it does not let a chip expire unused, and
does not spend one on an ordinary week when the season has barely started.
"""
import pytest
from unittest.mock import AsyncMock, patch

from app.models.projections import ChipWindow
from app.services import chips
from tests.conftest import make_fixture, make_team


async def _teams(session, n=4):
    for i in range(1, n + 1):
        session.add(make_team(i, short=f"T{i}"))
    await session.commit()


# ── Layer 1: fixture shape. Counting, so tested hardest. ─────────────────────

async def test_a_normal_gameweek_has_no_doubles_or_blanks(session):
    await _teams(session, 4)
    session.add(make_fixture(1, gameweek_id=1, team_h=1, team_a=2))
    session.add(make_fixture(2, gameweek_id=1, team_h=3, team_a=4))
    await session.commit()

    shape = await chips.fixture_shape(session)
    assert shape["doubles"] == {} and shape["blanks"] == {}
    assert "appear later in the season" in shape["note"]


async def test_a_double_gameweek_is_detected(session):
    # Five teams and three fixtures is the smallest arrangement where exactly
    # one team plays twice and nobody blanks.
    await _teams(session, 5)
    session.add(make_fixture(1, gameweek_id=5, team_h=1, team_a=2))
    session.add(make_fixture(2, gameweek_id=5, team_h=1, team_a=3))   # T1 twice
    session.add(make_fixture(3, gameweek_id=5, team_h=4, team_a=5))
    await session.commit()

    shape = await chips.fixture_shape(session)
    assert shape["doubles"][5] == ["T1"]
    assert shape["note"] is None


async def test_a_blank_gameweek_is_detected(session):
    await _teams(session, 4)
    session.add(make_fixture(1, gameweek_id=7, team_h=1, team_a=2))   # 3 and 4 idle
    await session.commit()

    shape = await chips.fixture_shape(session)
    assert shape["blanks"][7] == ["T3", "T4"]


async def test_shape_can_ignore_gameweeks_already_played(session):
    await _teams(session, 4)
    session.add(make_fixture(1, gameweek_id=1, team_h=1, team_a=2))
    session.add(make_fixture(2, gameweek_id=1, team_h=1, team_a=3))   # past double
    session.add(make_fixture(3, gameweek_id=9, team_h=1, team_a=2))
    session.add(make_fixture(4, gameweek_id=9, team_h=3, team_a=4))
    await session.commit()

    assert 1 in (await chips.fixture_shape(session, from_gameweek=1))["doubles"]
    assert (await chips.fixture_shape(session, from_gameweek=2))["doubles"] == {}


async def test_squad_fixture_counts_splits_playing_doubling_and_blank(session):
    from tests.conftest import make_player
    await _teams(session, 4)
    session.add(make_player(1, team_id=1))     # doubles
    session.add(make_player(2, team_id=2))     # plays once
    session.add(make_player(3, team_id=3))     # blank
    session.add(make_fixture(1, gameweek_id=5, team_h=1, team_a=2))
    session.add(make_fixture(2, gameweek_id=5, team_h=1, team_a=4))
    await session.commit()

    counts = await chips.squad_fixture_counts(session, [1, 2, 3], 5)
    assert counts == {"playing": 2, "doubling": 1, "blank": 1}


async def test_squad_fixture_counts_handles_an_empty_squad(session):
    assert await chips.squad_fixture_counts(session, [], 1) == {
        "playing": 0, "doubling": 0, "blank": 0
    }


# ── Layer 2: availability. Also fact. ────────────────────────────────────────

async def _windows(session):
    for name, start, stop in [
        ("wildcard", 2, 19), ("wildcard", 20, 38),
        ("bboost", 1, 19), ("bboost", 20, 38),
    ]:
        session.add(ChipWindow(name=name, start_event=start, stop_event=stop))
    await session.commit()


async def test_chip_state_reports_unused_chips(session):
    await _windows(session)
    with patch.object(chips, "fetch_manager_history", AsyncMock(return_value={"chips": []})):
        state = await chips.chip_state(session, 1)
    assert all(c["used_in_gameweek"] is None for c in state)
    assert all(c["history_available"] for c in state)


async def test_a_used_chip_is_attributed_to_the_right_half(session):
    await _windows(session)
    history = {"chips": [{"name": "wildcard", "event": 8}]}
    with patch.object(chips, "fetch_manager_history", AsyncMock(return_value=history)):
        state = await chips.chip_state(session, 1)

    first = next(c for c in state if c["name"] == "wildcard" and c["start_event"] == 2)
    second = next(c for c in state if c["name"] == "wildcard" and c["start_event"] == 20)
    assert first["used_in_gameweek"] == 8
    assert second["used_in_gameweek"] is None, "the second-half chip is untouched"


async def test_unreachable_history_is_flagged_not_assumed(session):
    """
    Recommending a chip already spent is worse than saying nothing, so a failed
    lookup has to be visible rather than silently reading as "all available".
    """
    await _windows(session)
    with patch.object(chips, "fetch_manager_history", AsyncMock(side_effect=OSError("down"))):
        state = await chips.chip_state(session, 1)
    assert all(c["history_available"] is False for c in state)


# ── Layer 4: the stopping rule. ──────────────────────────────────────────────

def test_an_expiring_chip_is_spent_rather_than_lost():
    verdict, _, reasons = chips.decide(
        "bboost", value_now=7.0, best_value=7.0, best_gameweek=19,
        baseline=6.5, weeks_remaining=1, has_double=False,
    )
    assert verdict == "use_now"
    assert any("expires" in r or "run out" in r for r in reasons)


def test_near_expiry_it_still_waits_for_a_clearly_better_week():
    verdict, _, _ = chips.decide(
        "bboost", value_now=7.0, best_value=20.0, best_gameweek=19,
        baseline=8.0, weeks_remaining=2, has_double=True,
    )
    assert verdict == "use_soon", "one better week left is worth waiting for"


def test_an_ordinary_week_early_in_the_season_is_held():
    verdict, _, _ = chips.decide(
        "bboost", value_now=6.4, best_value=6.5, best_gameweek=5,
        baseline=6.4, weeks_remaining=17, has_double=False,
    )
    assert verdict == "hold"


def test_a_clearly_exceptional_week_is_taken():
    verdict, _, reasons = chips.decide(
        "bboost", value_now=26.0, best_value=26.0, best_gameweek=24,
        baseline=6.5, weeks_remaining=10, has_double=True,
    )
    assert verdict == "use_now"
    assert any("double" in r.lower() for r in reasons)


def test_the_absolute_floor_beats_a_flattering_ratio():
    """A quiet week that is double another quiet week is still a quiet week."""
    verdict, _, _ = chips.decide(
        "bboost", value_now=4.0, best_value=4.0, best_gameweek=6,
        baseline=1.5, weeks_remaining=12, has_double=False,
    )
    assert verdict == "hold"


def test_a_missing_projection_says_so_rather_than_guessing():
    verdict, confidence, _ = chips.decide(
        "3xc", None, None, None, None, weeks_remaining=10, has_double=False,
    )
    assert verdict == "unknown" and confidence == "none"


def test_a_closed_window_is_reported_as_expired():
    verdict, _, _ = chips.decide(
        "wildcard", 20.0, 20.0, 19, 10.0, weeks_remaining=0, has_double=False,
    )
    assert verdict == "expired"


def test_without_a_comparison_week_it_holds_and_admits_why():
    """
    The solver-backed chips are priced for one gameweek only. Claiming a
    verdict from a single observation would be inventing a comparison.
    """
    verdict, confidence, reasons = chips.decide(
        "wildcard", value_now=13.8, best_value=13.8, best_gameweek=3,
        baseline=None, weeks_remaining=17, has_double=False,
    )
    assert verdict == "hold" and confidence == "low"
    assert any("no comparison week" in r for r in reasons)


def test_verdicts_never_invent_a_ratio_from_one_observation():
    """
    Guards the bug this shipped with: a mean over a single value equals that
    value, so every ratio was exactly 1.0 and the reasoning came out circular —
    "15.9 is close to a typical 15.9".
    """
    _, _, reasons = chips.decide(
        "freehit", 15.9, 15.9, 3, None, weeks_remaining=17, has_double=False,
    )
    joined = " ".join(reasons)
    assert "15.9 pts is close to an ordinary week (15.9)" not in joined


# ── The shape watcher ────────────────────────────────────────────────────────

async def _tracked(session, manager_id=1):
    from app.models.news import TrackedManager
    session.add(TrackedManager(fpl_entry_id=manager_id))
    await session.commit()


async def test_no_alert_when_every_team_plays_once(session):
    from tests.conftest import make_gameweek
    await _teams(session, 4)
    await _tracked(session)
    session.add(make_gameweek(2, is_next=True))
    session.add(make_fixture(1, gameweek_id=2, team_h=1, team_a=2))
    session.add(make_fixture(2, gameweek_id=2, team_h=3, team_a=4))
    await session.commit()

    r = await chips.alert_on_shape_changes(session)
    assert r["alerts_created"] == 0


async def test_a_new_double_gameweek_raises_one_alert_per_manager(session):
    from tests.conftest import make_gameweek
    from app.models.news import Alert
    from sqlalchemy import select as sel

    await _teams(session, 5)
    await _tracked(session, 1)
    await _tracked(session, 2)
    session.add(make_gameweek(2, is_next=True))
    session.add(make_fixture(1, gameweek_id=6, team_h=1, team_a=2))
    session.add(make_fixture(2, gameweek_id=6, team_h=1, team_a=3))
    session.add(make_fixture(3, gameweek_id=6, team_h=4, team_a=5))
    await session.commit()

    r = await chips.alert_on_shape_changes(session)
    assert r["alerts_created"] == 2

    alerts = (await session.execute(sel(Alert))).scalars().all()
    assert all("GW6" in a.title and "double" in a.title for a in alerts)
    assert all(a.payload["kind"] == "double_gameweek" for a in alerts)


async def test_the_same_double_is_not_announced_every_refresh(session):
    """
    The refresh runs ninety-six times a day. Without dedup a manager would be
    told about the same double gameweek until they muted the channel.
    """
    from tests.conftest import make_gameweek
    await _teams(session, 5)
    await _tracked(session)
    session.add(make_gameweek(2, is_next=True))
    session.add(make_fixture(1, gameweek_id=6, team_h=1, team_a=2))
    session.add(make_fixture(2, gameweek_id=6, team_h=1, team_a=3))
    session.add(make_fixture(3, gameweek_id=6, team_h=4, team_a=5))
    await session.commit()

    assert (await chips.alert_on_shape_changes(session))["alerts_created"] == 1
    for _ in range(3):
        assert (await chips.alert_on_shape_changes(session))["alerts_created"] == 0
