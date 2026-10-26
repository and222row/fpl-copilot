"""The fixture planner: runs rated from the team-strength model, doubles and blanks counted."""
import pytest

from app.models.projections import TeamStrength
from app.services.fixture_planner import attack_difficulty
from app.services.team_strength import MODEL_VERSION as FDR_VERSION
from tests.conftest import make_fixture, make_gameweek, make_team


@pytest.fixture
async def world(session):
    session.add_all([make_team(1, "ARS"), make_team(2, "BUR"), make_team(3, "CHE")])
    session.add_all([make_gameweek(g) for g in range(1, 5)])  # GW1 has started; 2-4 are ahead
    await session.flush()
    fixtures = [
        make_fixture(10, gameweek_id=1, team_h=1, team_a=2),  # already played: not in the window
        make_fixture(20, gameweek_id=2, team_h=1, team_a=2),
        make_fixture(30, gameweek_id=3, team_h=3, team_a=1),  # ARS double in GW3
        make_fixture(31, gameweek_id=3, team_h=2, team_a=1),
        make_fixture(40, gameweek_id=4, team_h=2, team_a=3),  # ARS blank in GW4
    ]
    fixtures[1].team_h_difficulty, fixtures[1].team_a_difficulty = 2, 5
    session.add_all(fixtures)
    await session.commit()


async def get(client, query=""):
    r = await client.get(f"/api/v1/projections/fixture-planner{query}")
    assert r.status_code == 200, r.text
    return r.json()


async def test_doubles_blanks_and_the_window(client, world):
    body = await get(client)
    assert body["gameweeks"] == [2, 3, 4]
    ars = next(t for t in body["teams"] if t["team"] == "ARS")
    assert ars["doubles"] == [3] and ars["blanks"] == [4]
    gw2, gw3, gw4 = ars["fixtures"]
    assert gw2["matches"][0]["opponent"] == "BUR" and gw2["matches"][0]["home"] is True
    assert [m["opponent"] for m in gw3["matches"]] == ["CHE", "BUR"]
    assert gw4["matches"] == []


async def test_before_ratings_exist_fpls_difficulty_stands_in(client, world):
    body = await get(client)
    assert body["source"] == "fpl"
    ars = next(t for t in body["teams"] if t["team"] == "ARS")
    assert ars["fixtures"][0]["matches"][0] == {"opponent": "BUR", "home": True, "fpl": 2, "overall": 2.0, "attack": 2.0, "defence": 2.0}
    # Ease: (6-2) for GW2, two 3s in GW3 (default difficulty), nothing in GW4.
    assert ars["ease"]["overall"] == 4 + 3 + 3
    assert body["teams"][0]["team"] == "ARS"  # the double puts them top


async def test_model_ratings_split_attack_from_defence(client, session, world):
    # ARS score freely and BUR leak goals: an easy fixture to attack.
    session.add_all([
        TeamStrength(team_id=1, model_version=FDR_VERSION, attack_home=2.4, attack_away=2.0, defence_home=0.8, defence_away=1.0),
        TeamStrength(team_id=2, model_version=FDR_VERSION, attack_home=0.9, attack_away=0.7, defence_home=2.0, defence_away=2.4),
        TeamStrength(team_id=3, model_version=FDR_VERSION),
    ])
    await session.commit()
    body = await get(client, "?gameweeks=1")
    assert body["source"] == "model" and body["gameweeks"] == [2]
    ars = next(t for t in body["teams"] if t["team"] == "ARS")["fixtures"][0]["matches"][0]
    bur = next(t for t in body["teams"] if t["team"] == "BUR")["fixtures"][0]["matches"][0]
    assert ars["attack"] < 2 and ars["defence"] < 2
    assert bur["attack"] > 4 and bur["defence"] > 4
    assert ars["overall"] == round((ars["attack"] + ars["defence"]) / 2, 2)


def test_more_expected_goals_is_an_easier_fixture_to_attack():
    assert attack_difficulty(2.4) == 1.0 and attack_difficulty(0.7) == 5.0
    assert attack_difficulty(1.0) > attack_difficulty(1.8)


async def test_window_is_bounded(client, world):
    r = await client.get("/api/v1/projections/fixture-planner?gameweeks=11")
    assert r.status_code == 422
