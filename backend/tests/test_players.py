"""Player explorer, player detail, and the reasons attached to transfers."""
from datetime import timedelta

import httpx
import pytest

from app.models.fpl import utcnow
from app.models.news import AvailabilityEvent
from app.routers.players import fold
from app.services.transfer_reasons import (
    _pair_by_position, _Profile, _reasons, explain_plans,
)
from tests.conftest import make_gameweek, make_player, make_projection, make_team

API = "/api/v1/players"


def proj(pid, gw, xpts, *, fdr=3.0, p_start=0.9, minutes=80.0, opponents=None, **components):
    p = make_projection(pid, gw, xpts=xpts, p_start=p_start, expected_minutes=minutes)
    p.custom_fdr = fdr
    p.opponents = opponents or []
    for k, v in components.items():
        setattr(p, f"xpts_{k}", v)
    return p


@pytest.fixture
async def pool(session):
    session.add_all([make_team(1, "ARS"), make_team(2, "LIV")])
    # GW1 locked, GW2 open, GW3 after.
    session.add_all([make_gameweek(1), make_gameweek(2), make_gameweek(3)])
    await session.flush()
    session.add_all([
        make_player(1, team_id=1, position=3, web_name="Ødegaard", now_cost=85),
        make_player(2, team_id=2, position=3, web_name="Salah", now_cost=130),
        make_player(3, team_id=2, position=2, web_name="Robertson", now_cost=60,
                    status="d", news="Knock - 75% chance of playing"),
        make_player(4, team_id=1, position=4, web_name="Gyökeres", now_cost=90),
        make_player(5, team_id=1, position=1, web_name="Raya", now_cost=55, status="i",
                    news="Hamstring injury - Expected back 1 Nov"),
        make_player(6, team_id=2, position=4, web_name="Unprojected", now_cost=45),
    ])
    await session.flush()
    session.add_all([
        proj(1, 1, 99.0),  # locked gameweek: must be ignored
        proj(1, 2, 6.5, fdr=2.1),
        proj(2, 2, 8.0, fdr=3.4),
        proj(3, 2, 4.0, fdr=3.4, p_start=0.55),
        proj(4, 2, 5.5, fdr=2.1, opponents=[{"opponent": 2, "is_home": True, "fdr": 2.1}]),
        proj(5, 2, 0.4, fdr=2.1, p_start=0.05),
        proj(4, 3, 4.5, fdr=3.0),
    ])
    session.add_all([
        make_player(7, team_id=1, position=3, web_name="Saka", now_cost=100),
    ])
    await session.flush()
    session.add(proj(7, 2, 6.5, fdr=2.1))
    await session.commit()
    return session


async def names(client, **params):
    r = await client.get(API, params=params)
    assert r.status_code == 200, r.text
    return [i["name"] for i in r.json()["items"]]


# ── Search folding ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("typed,actual", [
    ("odegaard", "Ødegaard"), ("gyokeres", "Gyökeres"), ("SALAH", "Salah"), ("muller", "Müller"),
])
def test_fold_matches_unaccented_typing(typed, actual):
    assert fold(typed) in fold(actual)


# ── Explorer ─────────────────────────────────────────────────────────────────

async def test_projections_come_from_the_open_gameweek(client, pool):
    # Ødegaard's 99 xPts is for the locked GW1 and must not count.
    body = (await client.get(API)).json()
    assert body["gameweek"] == 2
    assert body["items"][0]["name"] == "Salah"
    odegaard = next(i for i in body["items"] if i["player_id"] == 1)
    assert odegaard["xpts"] == 6.5


async def test_ties_break_by_id_so_order_is_stable(client, pool):
    assert (await names(client))[:3] == ["Salah", "Ødegaard", "Saka"]


async def test_unprojected_players_sort_last(client, pool):
    assert (await names(client))[-1] == "Unprojected"
    assert (await names(client, order="asc"))[-1] == "Unprojected"


async def test_search_ignores_accents(client, pool):
    assert await names(client, q="odeg") == ["Ødegaard"]
    assert await names(client, q="gyok") == ["Gyökeres"]


async def test_search_matches_full_name(client, pool):
    # make_player sets first_name "Test" for everyone
    assert len(await names(client, q="test sal")) == 1


async def test_search_wildcards_are_literal(client, pool):
    assert await names(client, q="%") == []
    assert await names(client, q="_") == []


@pytest.mark.parametrize("params,expected", [
    ({"position": 4}, {"Gyökeres", "Unprojected"}),
    ({"team_id": 2}, {"Salah", "Robertson", "Unprojected"}),
    ({"max_price": 6.0}, {"Robertson", "Raya", "Unprojected"}),
    ({"min_price": 10.0}, {"Salah", "Saka"}),
    ({"max_fdr": 2.5}, {"Ødegaard", "Gyökeres", "Raya", "Saka"}),
    ({"min_p_start": 0.6}, {"Ødegaard", "Salah", "Gyökeres", "Saka"}),
    ({"availability": "doubtful"}, {"Robertson"}),
    ({"availability": "out"}, {"Raya"}),
])
async def test_filters(client, pool, params, expected):
    assert set(await names(client, **params)) == expected


async def test_value_sort_divides_by_price(client, pool):
    top = await names(client, sort="value")
    assert top[0] == "Ødegaard"  # 6.5 / 8.5 beats 8.0 / 13.0


async def test_pagination_is_complete_and_disjoint(client, pool):
    seen = []
    for offset in range(0, 7, 2):
        body = (await client.get(API, params={"offset": offset, "limit": 2})).json()
        assert body["total"] == 7
        seen += [i["player_id"] for i in body["items"]]
    assert sorted(seen) == [1, 2, 3, 4, 5, 6, 7]


async def test_search_total_counts_matches_not_page(client, pool):
    body = (await client.get(API, params={"q": "a", "limit": 1})).json()
    assert body["total"] > 1 and len(body["items"]) == 1


async def test_row_shape(client, pool):
    row = (await client.get(API, params={"q": "robertson"})).json()["items"][0]
    assert row["price"] == 6.0
    assert row["status"] == "d"
    assert row["xpts"] == 4.0 and row["p_start"] == 0.55 and row["fdr"] == 3.4
    assert row["news"].startswith("Knock")


@pytest.mark.parametrize("params", [
    {"q": "x" * 41}, {"sort": "price; drop table players"}, {"limit": 101},
    {"order": "sideways"}, {"availability": "maybe"}, {"min_p_start": 2},
])
async def test_rejects_bad_parameters(client, pool, params):
    assert (await client.get(API, params=params)).status_code == 422


# ── Detail ───────────────────────────────────────────────────────────────────

@pytest.fixture
def element_summary(monkeypatch):
    calls = []

    async def fake(player_id):
        calls.append(player_id)
        return {"history": [
            {"round": r, "opponent_team": 2, "was_home": r % 2 == 0, "minutes": 90,
             "total_points": r, "goals_scored": 0, "assists": 0, "bonus": 0}
            for r in range(1, 8)
        ]}

    monkeypatch.setattr("app.routers.players.fetch_player_detail_cached", fake)
    return calls


async def test_detail_bundles_projection_fixtures_recent_and_news(client, pool, element_summary):
    pool.add(AvailabilityEvent(
        player_id=4, event_type="status_change", status_after="d", availability_after=0.75,
        cause="knock", news_text="Knock - 75% chance of playing", source="fpl_api",
        detected_at=utcnow() - timedelta(hours=2),
    ))
    await pool.commit()

    r = await client.get(f"{API}/4")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Gyökeres" and body["team_full"] == "Team 1"
    assert [g["gameweek"] for g in body["projection"]["gameweeks"]] == [2, 3]
    assert body["projection"]["total_xpts"] == 10.0
    assert body["projection"]["gameweeks"][0]["fixtures"] == [
        {"opponent": "LIV", "is_home": True, "fdr": 2.1}
    ]
    assert [m["gameweek"] for m in body["recent"]] == [7, 6, 5, 4, 3], "newest first, last five"
    assert body["recent"][0]["opponent"] == "LIV"
    assert body["news"][0]["source"] == "fpl_api"
    assert body["news"][0]["text"].startswith("Knock")


async def test_detail_survives_fpl_outage(client, pool, monkeypatch):
    async def down(player_id):
        raise httpx.ConnectTimeout("slow")

    monkeypatch.setattr("app.routers.players.fetch_player_detail_cached", down)
    r = await client.get(f"{API}/4")
    assert r.status_code == 200
    assert r.json()["recent"] is None


async def test_detail_unknown_player_is_404(client, pool, element_summary):
    assert (await client.get(f"{API}/9999")).status_code == 404


# ── Transfer reasons ─────────────────────────────────────────────────────────

def profile(name="X", *, status="a", news="", minutes=80.0, fdr=3.0, attack=2.0, defence=1.0):
    return _Profile(name, status, news, 5, minutes, fdr, attack, defence)


def test_reasons_cite_each_material_difference():
    out = profile("Out", status="d", news="Knock - 50% chance of playing",
                  minutes=55, fdr=3.8, attack=2.0, defence=0.5)
    inc = profile("In", minutes=82, fdr=2.4, attack=4.1, defence=1.6)
    reasons = _reasons(out, inc, out_price=9.0, in_price=7.5)
    assert reasons == [
        "Out is a doubt: Knock - 50% chance of playing",
        "More secure minutes: 82 expected per gameweek vs 55",
        "Higher attacking projection: +2.1 pts from goals and assists",
        "Stronger defensive projection: +1.1 pts from clean sheets and defending",
        "Easier fixtures: average difficulty 2.4 vs 3.8 (1 is easiest)",
        "Frees £1.5m",
    ]


def test_reasons_ignore_noise():
    out = profile(minutes=80, fdr=3.0, attack=2.0, defence=1.0)
    inc = profile(minutes=85, fdr=2.8, attack=2.5, defence=1.4)
    assert _reasons(out, inc, 8.0, 7.8) == []


def test_injured_player_is_named():
    out = profile("Raya", status="i", news="Hamstring injury - Expected back 1 Nov")
    assert _reasons(out, profile(), 5.5, 5.5)[0] == "Raya is injured: Hamstring injury - Expected back 1 Nov"


def test_pairs_like_for_like_positions():
    outs = [{"player_id": 1, "position": "DEF"}, {"player_id": 2, "position": "FWD"}]
    ins = [{"player_id": 3, "position": "FWD"}, {"player_id": 4, "position": "DEF"}]
    pairs = _pair_by_position(outs, ins)
    assert [(o["player_id"], i["player_id"]) for o, i in pairs] == [(1, 4), (2, 3)]


async def test_explain_plans_reads_the_projections(pool):
    plan = {
        "out": [{"player_id": 5, "position": "GKP", "price": 5.5, "horizon_xpts": 0.4}],
        "in": [{"player_id": 1, "position": "MID", "price": 8.5, "horizon_xpts": 6.5}],
    }
    hold = {"out": [], "in": []}
    await explain_plans(pool, [plan, hold], [2])
    move = plan["moves"][0]
    assert move["xpts_gain"] == 6.1
    assert move["reasons"][0].startswith("Raya is injured")
    assert hold["moves"] == []


async def test_reasons_fall_back_to_the_gain(pool):
    plan = {
        "out": [{"player_id": 7, "position": "MID", "price": 10.0, "horizon_xpts": 6.5}],
        "in": [{"player_id": 1, "position": "MID", "price": 8.5, "horizon_xpts": 6.5}],
    }
    await explain_plans(pool, [plan], [2])
    assert plan["moves"][0]["reasons"] == ["Frees £1.5m"]
