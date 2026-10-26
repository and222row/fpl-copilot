"""
The guest preview: public, no sign-in; FPL's public data and a teaser of the
advice without the names; never the owner's recorded transfers; nothing saved.
"""
import httpx
import pytest
from sqlalchemy import func, select

from app.models.feedback import RecommendationSnapshot, SquadOverride
from app.models.fpl import SyncState, utcnow
from app.services import advice, preview
from app.services.projection import PROJECTIONS_BUILT_KEY
from app.services.squad_state import ResolvedSquad
from tests.conftest import make_gameweek, make_player, make_projection, make_team

TEAM = 1003
POSITIONS = {**{i: 1 for i in (1, 2)}, **{i: 2 for i in range(3, 8)}, **{i: 3 for i in range(8, 13)}, **{i: 4 for i in (13, 14, 15)}}


@pytest.fixture
async def world(session, monkeypatch):
    session.add_all([make_team(t, f"T{t:02d}") for t in range(1, 21)])
    session.add_all([make_gameweek(g) for g in range(1, 7)])
    await session.flush()
    for pid, pos in POSITIONS.items():
        session.add(make_player(pid, team_id=pid, position=pos, now_cost=50, web_name=f"P{pid}",
                                status="d" if pid == 9 else "a", news="Knock - 75% chance of playing" if pid == 9 else ""))
    session.add(make_player(101, team_id=16, position=3, now_cost=50, web_name="Star"))
    await session.flush()
    for gw in range(2, 7):
        for pid in POSITIONS:
            session.add(make_projection(pid, gw, xpts=3.0))
        session.add(make_projection(101, gw, xpts=7.0))
    session.add(SyncState(key=PROJECTIONS_BUILT_KEY, at=utcnow()))
    await session.commit()

    seen = {}

    async def resolved(db, manager_id, target_gw, picks_gw, use_override=True):
        seen["use_override"] = use_override
        return ResolvedSquad(player_ids=list(POSITIONS), bank=5, free_transfers=1, source="fpl_api", picks_gameweek=picks_gw)

    async def info(entry):
        if entry == 404:
            raise httpx.HTTPStatusError("404", request=httpx.Request("GET", "x"), response=httpx.Response(404))
        return {"name": "Beg", "player_first_name": "Oliver", "player_last_name": "K", "summary_overall_rank": 878_268,
                "summary_overall_points": 530, "summary_event_points": 62}

    monkeypatch.setattr(advice, "resolve_squad", resolved)
    monkeypatch.setattr(preview, "fetch_manager_info", info)
    return seen


async def test_preview_needs_no_sign_in_and_hides_the_names(client, session, world):
    r = await client.get(f"/api/v1/preview/{TEAM}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["team"] == {"id": TEAM, "name": "Beg", "manager": "Oliver K", "overall_rank": 878_268,
                            "total_points": 530, "last_gameweek_points": 62}
    assert len(body["squad"]) == 15
    assert body["flagged"] == [{"name": "P9", "reason": "Doubtful", "news": "Knock - 75% chance of playing"}]
    teaser = body["teaser"]
    assert teaser["transfers"] >= 1 and teaser["gain"] > 0 and teaser["horizon"] == 5
    assert "Star" not in r.text, "the advice's players are what signing up unlocks"

    assert world["use_override"] is False, "never someone's recorded transfers"
    assert await session.scalar(select(func.count()).select_from(RecommendationSnapshot)) == 0


async def test_a_recorded_override_does_not_leak(client, session, world):
    session.add(SquadOverride(fpl_entry_id=TEAM, gameweek_id=2, player_ids=[101], bank=0, free_transfers=0, transfers_applied=[]))
    await session.commit()
    body = (await client.get(f"/api/v1/preview/{TEAM}")).json()
    assert "Star" not in str(body["squad"])


async def test_unknown_team_is_404(client, world):
    r = await client.get("/api/v1/preview/404")
    assert r.status_code == 404 and r.json()["detail"] == "No FPL team has that ID."


@pytest.mark.parametrize("team", ["0", "-1", "100000001", "abc"])
async def test_bad_ids_are_422(client, world, team):
    assert (await client.get(f"/api/v1/preview/{team}")).status_code == 422
