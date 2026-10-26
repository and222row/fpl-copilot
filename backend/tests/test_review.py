"""The gameweek review: points, ranks, best and worst, the captain, the bench, the advice, the season."""
from datetime import timedelta

import httpx
import pytest

from app.models.feedback import RecommendationOutcome, RecommendationSnapshot
from app.models.fpl import Fixture, Gameweek, utcnow
from app.services import leagues, live, review
from tests.conftest import make_player, make_team

YOU = 6727534
GW = 8
# GKP 1; DEF 2-4; MID 5-8; FWD 9-11; bench 12 (GKP), 13 (DEF), 14 (MID), 15 (FWD).
TYPES = {1: 1, 2: 2, 3: 2, 4: 2, 5: 3, 6: 3, 7: 3, 8: 3, 9: 4, 10: 4, 11: 4, 12: 1, 13: 2, 14: 3, 15: 4}
POINTS = {**{e: 2 for e in TYPES}, 5: 12, 9: 1, 6: -1, 12: 6, 14: 3}


def picks(captain=9, vice=5):
    return {"active_chip": None, "entry_history": {"event": GW, "points": 0, "total_points": 0, "event_transfers_cost": 4},
            "picks": [{"element": e, "position": e, "element_type": TYPES[e], "is_captain": e == captain,
                       "is_vice_captain": e == vice} for e in TYPES]}


@pytest.fixture(autouse=True)
def fresh_memo():
    live.clear_memo()
    yield
    live.clear_memo()


@pytest.fixture
async def world(session, monkeypatch):
    session.add_all([make_team(1, "ARS"), make_team(2, "MCI")])
    session.add_all([
        Gameweek(id=GW - 1, name="Gameweek 7", deadline_time=utcnow() - timedelta(days=9), average_entry_score=59),
        Gameweek(id=GW, name="Gameweek 8", deadline_time=utcnow() - timedelta(days=2), average_entry_score=45, highest_score=120),
        Gameweek(id=GW + 1, name="Gameweek 9", deadline_time=utcnow() + timedelta(days=5)),
    ])
    await session.flush()
    for e, t in TYPES.items():
        session.add(make_player(e, team_id=1 if e % 2 else 2, web_name=f"P{e}", position=t))
    session.add(Fixture(id=71, gameweek_id=GW, team_h=1, team_a=2, finished_provisional=True, kickoff_time=utcnow() - timedelta(days=1)))
    snap = RecommendationSnapshot(fpl_entry_id=YOU, gameweek_id=GW, kind="captain", model_version="proj-v1", payload={}, predicted_value=12)
    session.add(snap)
    await session.flush()
    session.add(RecommendationOutcome(snapshot_id=snap.id, fpl_entry_id=YOU, gameweek_id=GW, kind="captain", model_version="proj-v1",
                                      followed=False, correct=True, predicted_value=12, actual_value=24, error=12, regret=0,
                                      override_delta=-22))
    await session.commit()

    async def fake_live(gw):
        return {"elements": [{"id": e, "stats": {"total_points": POINTS[e], "minutes": 90 if e <= 11 else (90 if e in (12, 14) else 0)}} for e in TYPES]}

    async def fake_fixtures(gw):
        return [{"id": 71, "team_h": 1, "team_a": 2, "started": True, "finished_provisional": True, "finished": False,
                 "kickoff_time": "2026-10-24T14:00:00Z", "stats": [{"identifier": "bonus", "h": [{"element": 1, "value": 3}], "a": []}]}]

    async def fake_picks(entry, gw):
        if entry != YOU:
            raise httpx.HTTPStatusError("404", request=httpx.Request("GET", "x"), response=httpx.Response(404))
        return picks()

    async def history(entry):
        return {"current": [
            {"event": 7, "points": 67, "event_transfers_cost": 0, "rank": 900_000, "overall_rank": 1_500_000},
            {"event": 8, "points": 33, "event_transfers_cost": 4, "rank": 4_000_000, "overall_rank": 1_700_000},
        ]}

    async def info(entry):
        return {"leagues": {"classic": [{"id": 9, "name": "Mates", "league_type": "x", "rank_count": 11, "entry_rank": 4, "entry_last_rank": 2}]}}

    monkeypatch.setattr(live, "fetch_live_points", fake_live)
    monkeypatch.setattr(live, "fetch_event_fixtures", fake_fixtures)
    monkeypatch.setattr(live, "fetch_event_picks", fake_picks)
    monkeypatch.setattr(review, "fetch_manager_history", history)
    monkeypatch.setattr(leagues, "fetch_manager_info", info)


async def get(client, query=""):
    return await client.get(f"/api/v1/review/{YOU}{query}")


async def test_the_review(client, world):
    r = await get(client)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["gameweek"] == {"id": GW, "name": "Gameweek 8", "average": 45, "highest": 120}
    assert body["finished"] is True
    # Starters: 2 each, but 5 scored 12, 9 (captain) 1 x 2, 6 -1; less a 4-point hit.
    assert body["points"] == 2 * 8 + 12 + 1 * 2 - 1 - 4
    assert body["transfer_cost"] == 4
    assert (body["gameweek_rank"], body["previous_overall_rank"], body["overall_rank"]) == (4_000_000, 1_500_000, 1_700_000)

    assert [p["name"] for p in body["best"]][:1] == ["P5"]
    assert body["worst"][0]["name"] == "P6" and body["worst"][0]["contribution"] == -1
    cap = body["captain"]
    assert cap["pick"]["name"] == "P9" and cap["best"]["name"] == "P5"
    assert cap["missed"] == 12 - 1  # the armband on P5 instead
    assert body["bench_points"] == 6 + 3 + 2 + 2  # unused bench
    assert body["advice"] == [{"kind": "captain", "followed": False, "correct": True, "predicted": 12.0,
                               "actual": 24.0, "regret": 0.0, "override_delta": -22.0}]
    assert body["leagues"] == [{"id": 9, "name": "Mates", "rank": 4, "last_rank": 2, "size": 11}]
    assert body["season"] == [
        {"gameweek": 7, "points": 67, "average": 59, "overall_rank": 1_500_000},
        {"gameweek": 8, "points": 29, "average": 45, "overall_rank": 1_700_000},
    ]


async def test_a_gameweek_still_being_played_is_not_the_default(client, session, world):
    session.add(Fixture(id=72, gameweek_id=GW, team_h=2, team_a=1, finished_provisional=False, kickoff_time=utcnow()))
    await session.commit()
    r = await get(client)
    assert r.status_code == 404  # GW7 has no fixtures here, so nothing is finished
    assert (await get(client, f"?gameweek={GW}")).status_code == 200  # asked for explicitly, it still answers


async def test_a_future_gameweek_cannot_be_reviewed(client, world):
    assert (await get(client, f"?gameweek={GW + 1}")).status_code == 404


async def test_no_squad_that_gameweek_is_404(client, world, monkeypatch):
    async def none(entry, gw):
        raise httpx.HTTPStatusError("404", request=httpx.Request("GET", "x"), response=httpx.Response(404))

    monkeypatch.setattr(live, "fetch_event_picks", none)
    r = await get(client)
    assert r.status_code == 404 and "no squad" in r.json()["detail"]
