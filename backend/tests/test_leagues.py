"""
Mini-leagues: which leagues, the table and gaps, threats and differentials,
and head to head. FPL is faked; the shapes match what the live API returned
for a real eleven-manager private league.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest

from app.models.fpl import Gameweek
from app.models.projections import Projection
from app.services import leagues
from app.services.projection import MODEL_VERSION
from tests.conftest import make_player, make_team

YOU = 6727534
PRIVATE = 911741
NOW = datetime.now(timezone.utc)


def entry_info():
    return {"leagues": {"classic": [
        {"id": 314, "name": "Overall", "league_type": "s", "rank_count": 10_833_601, "entry_rank": 1_576_239, "entry_last_rank": 2_402_034},
        {"id": PRIVATE, "name": "Hossam Hassan Ball", "league_type": "x", "rank_count": 11, "entry_rank": 3, "entry_last_rank": 5},
    ]}}


def standings():
    rows = [
        (1, 2, 4276486, "Poehlerboyz", 358, 57),
        (2, 1, 1055545, "PhantomX", 348, 43),
        (3, 5, YOU, "Andrew's Team", 335, 60),
        (4, 4, 5876978, "Mangester Titi", 326, 49),
    ]
    return {
        "league": {"id": PRIVATE, "name": "Hossam Hassan Ball"},
        "standings": {"has_next": False, "page": 1, "results": [
            {"rank": r, "last_rank": lr, "rank_sort": r, "entry": e, "entry_name": n, "player_name": f"Manager {r}",
             "total": t, "event_total": ev}
            for r, lr, e, n, t, ev in rows
        ]},
    }


# Rivals all own 10 and 11; two of three own 12; nobody else owns your 1-3.
RIVAL_SQUADS = {
    4276486: [10, 11, 12, 1],
    1055545: [10, 11, 12],
    5876978: [10, 11, 13],
}
YOUR_SQUAD = [1, 2, 3, 13]


def picks(ids, captain):
    return {"picks": [{"element": i, "is_captain": i == captain} for i in ids]}


@pytest.fixture
async def world(session, monkeypatch):
    session.add_all([make_team(1, "AAA"), make_team(2, "BBB")])
    session.add_all([
        Gameweek(id=5, name="Gameweek 5", deadline_time=NOW - timedelta(days=3)),
        Gameweek(id=6, name="Gameweek 6", deadline_time=NOW + timedelta(days=2)),
    ])
    await session.flush()
    for pid in (1, 2, 3, 10, 11, 12, 13):
        session.add(make_player(pid, team_id=1 if pid < 10 else 2, web_name=f"P{pid}"))
    await session.flush()
    for pid, x in {1: 6.0, 2: 3.0, 3: 2.0, 10: 7.5, 11: 5.0, 12: 4.0, 13: 3.5}.items():
        session.add(Projection(player_id=pid, gameweek_id=6, model_version=MODEL_VERSION, xpts=x))
    await session.commit()

    async def info(manager_id):
        return entry_info()

    async def table(league_id, page=1):
        return standings()

    async def squad_picks(manager_id, gameweek):
        if manager_id == YOU:
            return picks(YOUR_SQUAD, captain=1)
        return picks(RIVAL_SQUADS[manager_id], captain=10)

    async def resolved(db, manager_id, target_gw, picks_gw):
        return SimpleNamespace(player_ids=YOUR_SQUAD)

    monkeypatch.setattr(leagues, "fetch_manager_info", info)
    monkeypatch.setattr(leagues, "fetch_league_standings", table)
    monkeypatch.setattr(leagues, "fetch_manager_picks", squad_picks)
    monkeypatch.setattr(leagues, "resolve_squad", resolved)


async def test_your_own_leagues_come_first(client, world):
    body = (await client.get(f"/api/v1/leagues/{YOU}")).json()
    assert [l["name"] for l in body["leagues"]] == ["Hossam Hassan Ball", "Overall"]
    assert body["leagues"][0] == {"id": PRIVATE, "name": "Hossam Hassan Ball", "private": True, "rank": 3, "last_rank": 5, "size": 11}


async def test_league_table_gaps_threats_and_differentials(client, world):
    body = (await client.get(f"/api/v1/leagues/{YOU}/{PRIVATE}")).json()
    assert body["your_rank"] == 3
    assert body["gaps"] == {"to_leader": 23, "to_next": 13}
    assert [r["is_you"] for r in body["standings"]] == [False, False, True, False]
    assert body["rivals_sampled"] == 3

    threats = {p["name"]: p["owned_by"] for p in body["threats"]}
    assert threats == {"P10": 3, "P11": 3, "P12": 2}  # 13 is yours; 1 is owned by one rival only
    assert list(threats)[0] == "P10"  # most owned, then highest projection

    assert [p["name"] for p in body["differentials"]] == ["P2", "P3"]  # 1 and 13 are owned by a third
    assert body["most_captained"][0]["name"] == "P10"


async def test_head_to_head(client, world):
    body = (await client.get(f"/api/v1/leagues/{YOU}/{PRIVATE}/rivals/4276486")).json()
    assert body["rival"]["team_name"] == "Poehlerboyz"
    assert body["points_gap"] == 23
    assert [p["name"] for p in body["shared"]] == ["P1"]
    assert [p["name"] for p in body["only_yours"]] == ["P13", "P2", "P3"]
    assert [p["name"] for p in body["only_theirs"]] == ["P10", "P11", "P12"]
    assert body["edge_next_gameweek"] == round((3.5 + 3.0 + 2.0) - (7.5 + 5.0 + 4.0), 1)
    assert (body["you"]["captain"], body["rival"]["captain"]) == ("P1", "P10")


async def test_a_league_you_are_not_in_is_404(client, world):
    assert (await client.get(f"/api/v1/leagues/{YOU}/999")).status_code == 404


async def test_a_rival_outside_the_league_is_404(client, world):
    assert (await client.get(f"/api/v1/leagues/{YOU}/{PRIVATE}/rivals/123")).status_code == 404


async def test_yourself_is_not_a_rival(client, world):
    assert (await client.get(f"/api/v1/leagues/{YOU}/{PRIVATE}/rivals/{YOU}")).status_code == 404


async def test_fpl_down_is_503(client, world, monkeypatch):
    async def down(manager_id):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(leagues, "fetch_manager_info", down)
    assert (await client.get(f"/api/v1/leagues/{YOU}")).status_code == 503


async def test_a_rival_without_picks_is_left_out_not_fatal(client, world, monkeypatch):
    original = leagues.fetch_manager_picks

    async def flaky(manager_id, gameweek):
        if manager_id == 1055545:
            raise httpx.HTTPStatusError("404", request=None, response=None)
        return await original(manager_id, gameweek)

    monkeypatch.setattr(leagues, "fetch_manager_picks", flaky)
    body = (await client.get(f"/api/v1/leagues/{YOU}/{PRIVATE}")).json()
    assert body["rivals_sampled"] == 2
