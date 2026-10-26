"""Transfer trends: the crowd's buys and sells and tonight's price changes, against the projections."""
import pytest

from app.models.projections import Projection
from app.services.projection import MODEL_VERSION
from app.services.trends import price_move
from tests.conftest import make_gameweek, make_player, make_team


def proj(offset, percent, likelihood):
    return {"offset": offset, "projected_percent": str(percent), "likelihood": likelihood}


@pytest.mark.parametrize("projections,expected", [
    ([proj(0, 107.7, 5), proj(1, 154.4, 5)], ("rise", "tonight", 5)),
    ([proj(0, 62.1, 3), proj(1, 91.8, 3), proj(2, 121.6, 5)], ("rise", "in 2 days", 5)),
    ([proj(0, -103, -5)], ("fall", "tonight", 5)),
    ([proj(0, 40, 1), proj(1, 60, 2), proj(2, 80, 2)], None),
    (None, None),
    ([{"offset": 0, "projected_percent": "n/a", "likelihood": 1}], None),
])
def test_price_move_reads_fpls_own_forecast(projections, expected):
    move = price_move(50.0, projections)
    got = (move["direction"], move["when"], move["likelihood"]) if move else None
    assert got == expected


@pytest.fixture
async def world(session):
    session.add_all([make_team(t, f"T{t:02d}") for t in range(1, 6)])
    session.add_all([make_gameweek(g) for g in range(1, 4)])
    await session.flush()
    # Forwards. 1: the crowd's pick, expensive and middling. 2: cheaper and better.
    # 3: better still but dearer than 1. 4: injured, everyone selling.
    players = [
        make_player(1, team_id=1, position=4, now_cost=70, web_name="Hype"),
        make_player(2, team_id=2, position=4, now_cost=60, web_name="Quiet"),
        make_player(3, team_id=3, position=4, now_cost=95, web_name="Star"),
        make_player(4, team_id=4, position=4, now_cost=80, web_name="Crocked", status="i"),
    ]
    players[0].transfers_in_event, players[0].transfers_out_event = 400_000, 5_000
    players[1].transfers_in_event = 1_000
    players[3].transfers_out_event = 250_000
    players[0].price_change_percent = 90.0
    players[0].price_change_projections = [proj(0, 110, 5)]
    players[3].price_change_percent = -80.0
    players[3].price_change_projections = [proj(0, -60, -2), proj(1, -101, -4)]
    session.add_all(players)
    await session.flush()
    for gw in (2, 3):
        for pid, x in {1: 3.0, 2: 4.0, 3: 6.0, 4: 0.0}.items():
            session.add(Projection(player_id=pid, gameweek_id=gw, model_version=MODEL_VERSION, xpts=x))
    await session.commit()


async def test_trends(client, world):
    r = await client.get("/api/v1/projections/transfer-trends")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["gameweek"]["id"] == 2 and body["horizon"] == 2

    hype = body["most_bought"][0]
    assert (hype["name"], hype["transfers_in"], hype["net"], hype["xpts_horizon"]) == ("Hype", 400_000, 395_000, 6.0)
    assert (hype["position_rank"], hype["position_count"]) == (3, 4)
    # Quiet is cheaper and projects 2 more; Star projects more but costs more.
    assert hype["alternative"]["name"] == "Quiet"
    assert hype["price_move"] == {"direction": "rise", "when": "tonight", "offset": 0, "likelihood": 5, "progress": 90.0}

    assert body["most_sold"][0]["name"] == "Crocked"
    assert body["most_sold"][0]["position_rank"] == 4  # the model agrees with selling
    assert [p["name"] for p in body["rising"]] == ["Hype"]
    assert body["falling"][0]["name"] == "Crocked" and body["falling"][0]["price_move"]["when"] == "tomorrow"


async def test_no_alternative_when_nothing_cheaper_is_clearly_better(client, session, world):
    from app.models.fpl import Player
    quiet = await session.get(Player, 2)
    quiet.status = "d"  # doubtful: not offered
    await session.commit()
    body = (await client.get("/api/v1/projections/transfer-trends")).json()
    assert body["most_bought"][0]["alternative"] is None
