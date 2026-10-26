"""Head-to-head leagues and the cup: shapes as the live FPL API returned them."""
from datetime import timedelta

import httpx
import pytest

from app.models.fpl import Fixture, Gameweek, utcnow
from app.services import h2h, live
from app.services.h2h import match_view

YOU, THEM, NEXT = 1003, 1450796, 2896701
LEAGUE = 608496


def match(event, first, second, p1, p2, result=None, **extra):
    """result is first's: 'W', 'D' or 'L', or None if unplayed."""
    r = {"W": (1, 0, 0), "D": (0, 1, 0), "L": (0, 0, 1)}.get(result, (0, 0, 0))
    o = {"W": (0, 0, 1), "D": (0, 1, 0), "L": (1, 0, 0)}.get(result, (0, 0, 0))
    return {
        "event": event, "entry_1_entry": first, "entry_1_name": f"T{first}", "entry_1_player_name": f"M{first}",
        "entry_1_points": p1, "entry_1_win": r[0], "entry_1_draw": r[1], "entry_1_loss": r[2],
        "entry_2_entry": second, "entry_2_name": f"T{second}", "entry_2_player_name": f"M{second}",
        "entry_2_points": p2, "entry_2_win": o[0], "entry_2_draw": o[1], "entry_2_loss": o[2],
        "is_knockout": False, "is_bye": False, "knockout_name": "", **extra,
    }


def test_a_match_from_your_side_whichever_slot_you_are_in():
    m = match(8, THEM, YOU, 47, 62, result="L")
    assert match_view(m, YOU) == {
        "gameweek": 8, "opponent": {"entry": THEM, "team_name": f"T{THEM}", "manager_name": f"M{THEM}"},
        "your_points": 62, "their_points": 47, "result": "W", "knockout": None,
    }
    assert match_view(match(9, YOU, NEXT, 0, 0), YOU)["result"] is None
    assert match_view(match(6, YOU, THEM, 65, 65, result="D"), YOU)["result"] == "D"
    assert match_view({**match(5, YOU, 0, 50, 0), "is_bye": True}, YOU)["opponent"] is None


@pytest.fixture
async def world(session, monkeypatch):
    session.add_all([
        Gameweek(id=8, name="Gameweek 8", deadline_time=utcnow() - timedelta(days=2)),
        Gameweek(id=9, name="Gameweek 9", deadline_time=utcnow() + timedelta(days=5)),
    ])
    await session.flush()
    session.add(Fixture(id=71, gameweek_id=8, team_h=1, team_a=2, finished_provisional=True, kickoff_time=utcnow() - timedelta(days=1)))
    await session.commit()

    async def info(entry):
        return {"leagues": {
            "h2h": [{"id": LEAGUE, "name": "Rigged", "entry_rank": 2, "entry_last_rank": 3, "rank_count": None}],
            "cup": {"matches": [match(17, YOU, THEM, 70, 55, result="W", knockout_name="Round 1")],
                    "status": {"qualification_state": "QUALIFIED", "qualification_event": 16}},
        }}

    async def standings(league):
        return {"league": {"id": LEAGUE, "name": "Rigged"}, "standings": {"has_next": False, "results": [
            {"rank": 1, "last_rank": 1, "rank_sort": 1, "entry": THEM, "entry_name": "Beef", "player_name": "G",
             "matches_won": 5, "matches_drawn": 1, "matches_lost": 1, "total": 16, "points_for": 496},
            {"rank": 2, "last_rank": 3, "rank_sort": 2, "entry": YOU, "entry_name": "Beg", "player_name": "O",
             "matches_won": 4, "matches_drawn": 2, "matches_lost": 1, "total": 14, "points_for": 470},
        ]}}

    state = {"matches": [match(7, YOU, 32641, 65, 61, result="W"), match(8, THEM, YOU, 47, 62, result="L"), match(9, YOU, NEXT, 0, 0)]}

    async def matches(league, entry):
        return {"results": state["matches"]}

    monkeypatch.setattr(h2h, "fetch_manager_info", info)
    monkeypatch.setattr(h2h, "fetch_h2h_standings", standings)
    monkeypatch.setattr(h2h, "fetch_h2h_matches", matches)
    return state


async def test_your_h2h_leagues_and_cup(client, world):
    body = (await client.get(f"/api/v1/h2h/{YOU}")).json()
    assert body["leagues"] == [{"id": LEAGUE, "name": "Rigged", "rank": 2, "last_rank": 3, "size": None}]
    assert body["cup"]["qualified"] == "QUALIFIED"
    assert body["cup"]["matches"][0]["knockout"] == "Round 1" and body["cup"]["matches"][0]["result"] == "W"


async def test_a_league_this_week_next_week_and_your_record(client, world):
    r = await client.get(f"/api/v1/h2h/{YOU}/{LEAGUE}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["current"]["opponent"]["entry"] == THEM and body["current"]["result"] == "W"
    assert body["current_status"] is None  # settled, so FPL's numbers stand
    assert body["next"]["opponent"]["entry"] == NEXT and body["next"]["gameweek"] == 9
    assert body["record"] == {"W": 2, "D": 0, "L": 0}
    assert [m["gameweek"] for m in body["results"]] == [8, 7]  # newest first
    assert [r["is_you"] for r in body["standings"]] == [False, True]
    assert body["standings"][1]["won"] == 4


async def test_a_match_being_played_is_scored_live(client, session, world, monkeypatch):
    world["matches"][1] = match(8, THEM, YOU, 0, 0)  # unsettled
    fixture = await session.get(Fixture, 71)
    fixture.finished_provisional = False
    await session.commit()

    async def points(db, gameweek, entries):
        return {YOU: 41, THEM: 38}

    async def world_(db, gameweek):
        return {}, [{"id": 71, "team_h": 1, "team_a": 2, "started": True, "finished_provisional": False, "kickoff_time": None}]

    monkeypatch.setattr(h2h, "_live_points", points)
    monkeypatch.setattr(live, "_world", world_)
    body = (await client.get(f"/api/v1/h2h/{YOU}/{LEAGUE}")).json()
    assert (body["current"]["your_points"], body["current"]["their_points"], body["current"]["live"]) == (41, 38, True)
    assert body["current_status"]["in_play"] is True


async def test_a_league_you_are_not_in_is_404(client, world):
    assert (await client.get(f"/api/v1/h2h/{YOU}/999")).status_code == 404


async def test_fpl_down_is_503(client, world, monkeypatch):
    async def down(entry):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(h2h, "fetch_manager_info", down)
    assert (await client.get(f"/api/v1/h2h/{YOU}")).status_code == 503
