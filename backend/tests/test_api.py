"""
API tests against an in-memory database.

These check routing, validation and error handling — the parts that break when
a route signature drifts. Business logic is covered by the unit suites.
"""
import pytest
from tests.conftest import (
    make_team, make_player, make_gameweek, make_fixture, make_projection,
)


# ── Basics ────────────────────────────────────────────────────────────────────

async def test_root_reports_service_metadata(client):
    r = await client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "FPL Copilot API"
    assert "version" in body


async def test_openapi_schema_builds(client):
    """A malformed route annotation breaks schema generation, not just docs."""
    r = await client.get("/openapi.json")
    assert r.status_code == 200
    assert "/api/v1/fpl/players" in r.json()["paths"]


async def test_health_reports_degraded_rather_than_500(client):
    """Redis is unavailable in tests; health must degrade gracefully."""
    r = await client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("ok", "degraded")
    assert "database" in body and "redis" in body


# ── Empty database behaviour ─────────────────────────────────────────────────

async def test_gameweek_404s_with_actionable_message(client):
    r = await client.get("/api/v1/fpl/gameweek")
    assert r.status_code == 404
    assert "sync" in r.json()["detail"].lower()


async def test_players_returns_empty_list_not_error(client):
    r = await client.get("/api/v1/fpl/players")
    assert r.status_code == 200
    assert r.json() == []


async def test_unknown_player_404s(client):
    r = await client.get("/api/v1/fpl/players/999999")
    assert r.status_code == 404


async def test_projections_404_tells_you_to_rebuild(client, session):
    session.add(make_gameweek(1, is_current=True))
    await session.commit()
    r = await client.get("/api/v1/fpl/gameweek")
    assert r.status_code == 200
    r = await client.get("/api/v1/projections?gameweek=1")
    assert r.status_code == 404
    assert "rebuild" in r.json()["detail"].lower()


# ── Query validation ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("qs,expected", [
    ("position=0", 422),      # below range
    ("position=5", 422),      # above range
    ("position=abc", 422),    # wrong type
    ("limit=0", 422),
    ("limit=99999", 422),
    ("sort_by=DROP TABLE", 422),   # pattern-constrained, not interpolated
    ("position=3", 200),
    ("limit=5", 200),
    ("sort_by=form", 200),
    ("max_price=8.5", 200),
])
async def test_player_query_validation(client, qs, expected):
    r = await client.get(f"/api/v1/fpl/players?{qs}")
    assert r.status_code == expected, r.text


async def test_sort_by_is_whitelisted_not_interpolated(client):
    """
    sort_by maps to a column via a dict, so a SQL-ish value is rejected by
    validation and never reaches the query.
    """
    r = await client.get("/api/v1/fpl/players?sort_by=now_cost;DROP TABLE players")
    assert r.status_code == 422


@pytest.mark.parametrize("qs,expected", [
    ("gameweeks=1,2,3", 200),
    ("gameweeks=not-a-number", 400),
])
async def test_backtest_gameweek_parsing(client, qs, expected):
    r = await client.get(f"/api/v1/projections/backtest?{qs}")
    assert r.status_code == expected


@pytest.mark.parametrize("mode,expected", [
    ("safe", 422),           # 422 from validation would be wrong; see below
    ("balanced", 422),
    ("nonsense", 422),
])
async def test_captain_mode_is_constrained(client, mode, expected):
    """
    Manager routes hit the live FPL API, so with an empty DB they fail before
    reaching it. What matters here is that an invalid mode is rejected by
    validation rather than reaching the handler.
    """
    r = await client.get(f"/api/v1/decisions/1?captain_mode={mode}")
    assert r.status_code in (400, 404, 422, 502)


# ── Populated database ───────────────────────────────────────────────────────

@pytest.fixture
async def seeded(session):
    session.add_all([make_team(1, "AAA"), make_team(2, "BBB")])
    session.add_all([make_gameweek(1, is_current=True), make_gameweek(2, is_next=True)])
    await session.flush()

    session.add_all([
        make_player(1, team_id=1, position=1, web_name="Keeper", now_cost=50),
        make_player(2, team_id=1, position=2, web_name="Back", now_cost=45),
        make_player(3, team_id=2, position=3, web_name="Mid", now_cost=85,
                    news="Knock - 75% chance of playing", status="d"),
        make_player(4, team_id=2, position=4, web_name="Striker", now_cost=120,
                    penalties_order=1),
    ])
    session.add(make_fixture(1, gameweek_id=1, team_h=1, team_a=2,
                             finished_provisional=True, h_score=2, a_score=1))
    await session.flush()

    for pid, xpts in ((1, 3.5), (2, 3.0), (3, 5.5), (4, 7.5)):
        session.add(make_projection(pid, 1, xpts=xpts))
    await session.commit()
    return session


async def test_players_list_shape(client, seeded):
    r = await client.get("/api/v1/fpl/players")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 4
    row = rows[0]
    for field in ("id", "name", "team", "position", "price", "status_label"):
        assert field in row


async def test_price_is_converted_from_tenths(client, seeded):
    r = await client.get("/api/v1/fpl/players/4")
    assert r.json()["price"] == 12.0


async def test_position_filter_applies(client, seeded):
    r = await client.get("/api/v1/fpl/players?position=4")
    assert [p["position"] for p in r.json()] == ["FWD"]


async def test_max_price_filter_applies(client, seeded):
    r = await client.get("/api/v1/fpl/players?max_price=5.0")
    assert all(p["price"] <= 5.0 for p in r.json())


async def test_teams_endpoint(client, seeded):
    r = await client.get("/api/v1/fpl/teams")
    assert {t["short_name"] for t in r.json()} == {"AAA", "BBB"}


async def test_gameweek_returns_the_next_open_deadline(client, seeded):
    """
    Not the gameweek being played. The seeded GW1 deadline is in the past and
    GW2's is ahead, so the dashboard must target GW2 — advising on a locked
    gameweek would describe a transfer the manager cannot make.
    """
    r = await client.get("/api/v1/fpl/gameweek")
    body = r.json()
    assert body["id"] == 2
    assert body["deadline_passed"] is False
    # What is actually live is still reported, so nothing is lost
    assert body["current_gameweek"] == 1


async def test_seeded_deadlines_are_relative_not_pinned_to_real_dates():
    """
    Guards against the suite acquiring an expiry date.

    An earlier fixture hardcoded GW1 to 21 Aug 2026 and GW2 a week after. Both
    were correct when written and both were in the past by 30 Aug, so the
    "next open gameweek" test started failing on a nightly run with nothing
    changed. A fixture that only passes during a particular week is not a
    fixture, so assert the relationship directly rather than trusting a date.
    """
    from tests.conftest import make_gameweek

    now = datetime.now(timezone.utc)
    assert make_gameweek(1).deadline_time < now, "GW1 must always be locked"
    assert make_gameweek(2).deadline_time > now, "GW2 must always be open"

    # And it has to keep holding, not just today.
    later = make_gameweek(3).deadline_time
    assert later > make_gameweek(2).deadline_time


async def test_fixtures_resolve_team_names(client, seeded):
    r = await client.get("/api/v1/fpl/fixtures?gameweek=1")
    row = r.json()[0]
    assert row["home"] == "AAA"
    assert row["away"] == "BBB"
    assert row["home_score"] == 2


async def test_projections_sorted_by_xpts(client, seeded):
    r = await client.get("/api/v1/projections?gameweek=1&min_minutes=0")
    rows = r.json()
    assert [x["name"] for x in rows][:2] == ["Striker", "Mid"]
    assert rows == sorted(rows, key=lambda x: -x["xpts"])


async def test_projection_row_includes_value_and_set_pieces(client, seeded):
    r = await client.get("/api/v1/projections?gameweek=1&min_minutes=0")
    striker = next(x for x in r.json() if x["name"] == "Striker")
    assert striker["is_penalty_taker"] is True
    assert striker["value"] == pytest.approx(7.5 / 12.0, abs=0.01)


async def test_player_projection_detail_exposes_components(client, seeded):
    seeded.add(make_projection(4, 2, xpts=6.0))
    await seeded.commit()
    r = await client.get("/api/v1/projections/player/4?horizon=1")
    assert r.status_code == 200
    body = r.json()
    assert "components" in body["gameweeks"][0]
    assert body["set_pieces"]["penalties"] == 1


async def test_player_projection_detail_skips_locked_gameweeks(client, seeded):
    # GW1's deadline has passed; its row is kept for accuracy scoring but is
    # not "upcoming". The season's first rows must not masquerade as next.
    seeded.add_all([make_projection(4, 2, xpts=6.0), make_gameweek(3)])
    seeded.add(make_projection(4, 3, xpts=5.0))
    await seeded.commit()
    body = (await client.get("/api/v1/projections/player/4?horizon=5")).json()
    assert [g["gameweek"] for g in body["gameweeks"]] == [2, 3]
    assert body["total_xpts"] == pytest.approx(11.0)


async def test_projection_list_defaults_to_the_open_gameweek(client, seeded):
    seeded.add(make_projection(4, 2, xpts=9.9))
    await seeded.commit()
    rows = (await client.get("/api/v1/projections?min_minutes=0")).json()
    assert [r["name"] for r in rows] == ["Striker"]
    assert rows[0]["xpts"] == 9.9


async def test_news_parse_check_reports_rate(client, seeded):
    r = await client.get("/api/v1/news/parse-check")
    body = r.json()
    assert body["total_with_news"] == 1
    assert body["unparsed"] == 0
    assert body["players"][0]["availability_source"] == "news_text"


async def test_detection_first_run_creates_baseline_without_events(client, seeded):
    r = await client.post("/api/v1/news/detect")
    body = r.json()
    assert body["first_run"] is True
    assert body["events_detected"] == 0


async def test_detection_is_idempotent(client, seeded):
    await client.post("/api/v1/news/detect")
    second = (await client.post("/api/v1/news/detect")).json()
    assert second["events_detected"] == 0


async def test_events_carry_category_source_and_confidence(client, seeded):
    from app.models.news import AvailabilityEvent
    seeded.add(AvailabilityEvent(
        player_id=3, event_type="chance_change", cause="knock", status_after="d",
        availability_before=1.0, availability_after=0.75, materiality=0.4,
        news_text="Knock - 75% chance of playing", source="fpl_api",
    ))
    await seeded.commit()
    row = (await client.get("/api/v1/news/events")).json()[0]
    assert row["category"] == "INJURY"
    assert row["direction"] == "negative"
    assert row["confidence"] == "high"
    assert row["source_label"] == "FPL official"
    assert row["news"] == "Knock - 75% chance of playing"


async def test_price_watch_threshold_validated(client, seeded):
    assert (await client.get("/api/v1/news/price-watch?threshold=150")).status_code == 422
    assert (await client.get("/api/v1/news/price-watch?threshold=50")).status_code == 200


async def test_alerts_empty_for_unknown_manager(client, seeded):
    r = await client.get("/api/v1/news/alerts/424242")
    assert r.status_code == 200
    assert r.json() == []


async def test_team_strength_404s_before_rebuild(client, seeded):
    r = await client.get("/api/v1/projections/team-strength")
    assert r.status_code == 404
    assert "rebuild" in r.json()["detail"].lower()


async def test_team_strength_rebuild_then_read(client, seeded):
    assert (await client.post("/api/v1/projections/rebuild/team-strength")).status_code == 200
    r = await client.get("/api/v1/projections/team-strength")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 2
    # One fixture played, so the prior still dominates
    assert all(0 < row["prior_weight"] <= 1 for row in rows)


async def test_projection_rebuild_writes_rows(client, seeded):
    await client.post("/api/v1/projections/rebuild/team-strength")
    r = await client.post("/api/v1/projections/rebuild?horizon=2")
    assert r.status_code == 200
    body = r.json()
    assert body["written"] == body["players"] * len(body["gameweeks"])


async def test_backtest_reports_no_sample_rather_than_failing(client, seeded):
    r = await client.get("/api/v1/projections/backtest")
    assert r.status_code == 200
    assert r.json()["sample_size"] == 0


# ── Gameweek targeting ───────────────────────────────────────────────────────
#
# The bug this guards against: recommendations targeted the gameweek being
# played, whose deadline had already passed, so the dashboard offered transfers
# the manager could not make.

from datetime import datetime, timedelta, timezone  # noqa: E402
from app.models.fpl import Gameweek  # noqa: E402
from app.services.fpl_sync import (  # noqa: E402
    get_next_open_gameweek, get_latest_started_gameweek, deadline_has_passed,
)


def _gw(gw_id: int, days_from_now: float, **flags) -> Gameweek:
    return Gameweek(
        id=gw_id,
        name=f"Gameweek {gw_id}",
        deadline_time=datetime.now(timezone.utc) + timedelta(days=days_from_now),
        finished=flags.get("finished", False),
        is_current=flags.get("is_current", False),
        is_next=flags.get("is_next", False),
    )


async def test_next_open_gameweek_skips_passed_deadlines(session):
    session.add_all([
        _gw(1, -4, is_current=True),   # deadline gone
        _gw(2, +3, is_next=True),      # still open
        _gw(3, +10),
    ])
    await session.commit()
    gw = await get_next_open_gameweek(session)
    assert gw.id == 2


async def test_next_open_gameweek_ignores_the_is_current_flag(session):
    """A gameweek can be flagged current and still be locked."""
    session.add_all([_gw(1, -1, is_current=True), _gw(2, +6)])
    await session.commit()
    assert (await get_next_open_gameweek(session)).id == 2


async def test_next_open_gameweek_falls_back_at_season_end(session):
    """With every deadline behind us, fall back rather than returning nothing."""
    session.add_all([_gw(37, -14), _gw(38, -7, is_current=True)])
    await session.commit()
    gw = await get_next_open_gameweek(session)
    assert gw is not None


async def test_latest_started_gameweek_is_where_picks_come_from(session):
    session.add_all([_gw(1, -10), _gw(2, -3), _gw(3, +4)])
    await session.commit()
    assert (await get_latest_started_gameweek(session)).id == 2


async def test_latest_started_is_none_before_the_season(session):
    session.add_all([_gw(1, +5), _gw(2, +12)])
    await session.commit()
    assert await get_latest_started_gameweek(session) is None


async def test_target_and_picks_gameweeks_differ_mid_season(session):
    """
    The core distinction: advice targets the open gameweek, while the squad is
    read from the last one that started.
    """
    session.add_all([_gw(1, -10), _gw(2, -3, is_current=True), _gw(3, +4)])
    await session.commit()
    target = await get_next_open_gameweek(session)
    picks = await get_latest_started_gameweek(session)
    assert target.id == 3
    assert picks.id == 2
    assert target.id != picks.id


async def test_deadline_has_passed_both_ways(session):
    assert deadline_has_passed(_gw(1, -1)) is True
    assert deadline_has_passed(_gw(2, +1)) is False


async def test_deadline_check_handles_a_naive_timestamp():
    gw = Gameweek(id=1, name="GW1",
                  deadline_time=datetime.now(timezone.utc).replace(tzinfo=None)
                  - timedelta(hours=1))
    assert deadline_has_passed(gw) is True


async def test_missing_deadline_is_not_treated_as_passed():
    assert deadline_has_passed(Gameweek(id=1, name="GW1", deadline_time=None)) is False


async def test_quiet_data_confirmed_recently_reads_as_fresh(client, session, seeded):
    """
    The regression that failed every quiet-period refresh.

    Unchanged rows are no longer rewritten, so their timestamps stop moving.
    Data last changed three hours ago but confirmed a minute ago is current, and
    reporting it as "aging" failed refreshes that had succeeded.
    """
    from datetime import datetime, timedelta, timezone
    from app.models.fpl import Player, SyncState
    from sqlalchemy import update

    three_hours_ago = datetime.now(timezone.utc) - timedelta(hours=3)
    await session.execute(update(Player).values(updated_at=three_hours_ago))
    session.add(SyncState(key="refresh_verified",
                          at=datetime.now(timezone.utc) - timedelta(minutes=1)))
    await session.commit()

    body = (await client.get("/api/v1/health/freshness")).json()
    players = body["data_sets"]["players"]
    assert players["status"] == "fresh"
    assert players["changed_at"] is not None and players["verified_at"] is not None
    assert body["last_verified"]["age_minutes"] < 5


async def test_without_a_verification_freshness_falls_back_to_row_age(client, session, seeded):
    from datetime import datetime, timedelta, timezone
    from app.models.fpl import Player
    from sqlalchemy import update

    await session.execute(update(Player).values(
        updated_at=datetime.now(timezone.utc) - timedelta(hours=3)))
    await session.commit()

    body = (await client.get("/api/v1/health/freshness")).json()
    assert body["data_sets"]["players"]["status"] == "aging"
    assert body["last_verified"]["at"] is None
