"""The article behind a squad warning or alert, written from data we hold."""
from datetime import timedelta

import pytest

from app.models.feedback import AdviceCache
from app.models.fpl import Player, utcnow
from app.models.news import Alert, AvailabilityEvent
from app.services import story
from app.services.squad_state import ResolvedSquad
from tests.conftest import make_gameweek, make_player, make_projection, make_team

TEAM = 1234
HURT, MINE, CHEAP, STAR, PRICEY, DOUBT = 10, 11, 12, 13, 14, 15


@pytest.fixture
async def world(session, monkeypatch):
    for t in range(1, 7):
        team = make_team(t, f"T{t}")
        team.code = t * 3
        session.add(team)
    session.add_all([make_gameweek(g) for g in range(1, 6)])
    await session.flush()
    session.add_all([
        make_player(HURT, team_id=1, position=4, now_cost=78, web_name="Pedro", status="i", news="Thigh injury - Unknown return date"),
        make_player(MINE, team_id=2, position=4, now_cost=60, web_name="Mine"),
        make_player(CHEAP, team_id=3, position=4, now_cost=55, web_name="Cheap"),
        make_player(STAR, team_id=4, position=4, now_cost=80, web_name="Star"),  # 7.8 + 0.1 bank: affordable? no, 8.0 > 7.9
        make_player(PRICEY, team_id=5, position=4, now_cost=120, web_name="Pricey"),
        make_player(DOUBT, team_id=6, position=4, now_cost=60, web_name="Doubt", status="d"),
    ])
    await session.flush()
    for pid in (HURT, MINE, CHEAP, STAR, PRICEY, DOUBT):
        (await session.get(Player, pid)).code = 1000 + pid
    for gw in (2, 3, 4, 5):
        for pid, x in {HURT: 0.0, MINE: 3.0, CHEAP: 4.0, STAR: 9.0, PRICEY: 9.5, DOUBT: 8.0}.items():
            session.add(make_projection(pid, gw, xpts=x))
    now = utcnow()
    session.add_all([
        AvailabilityEvent(player_id=HURT, event_type="status_change", news_text="Knock - 75% chance of playing",
                          status_after="d", availability_after=0.75, detected_at=now - timedelta(days=4)),
        AvailabilityEvent(player_id=HURT, event_type="ruled_out", news_text="Thigh injury - Unknown return date",
                          status_after="i", availability_after=0.0, detected_at=now - timedelta(days=2)),
        AvailabilityEvent(player_id=HURT, event_type="price_change", news_text="Price fall", detected_at=now - timedelta(hours=3)),
        Alert(fpl_entry_id=TEAM, player_id=HURT, severity="critical", title="Pedro ruled out", body="Thigh injury", created_at=now),
        Alert(fpl_entry_id=999, player_id=HURT, severity="critical", title="Someone else's", body="", created_at=now),
        AdviceCache(fpl_entry_id=TEAM, gameweek_id=2, fingerprint="x", computed_at=now, body={
            "lineup": {"starting": [{"player_id": HURT}], "bench": []},
            "captain": {"pick": {"player_id": HURT}},
            "transfer": {"plan": {"out": [{"player_id": HURT, "name": "Pedro"}], "in": [{"player_id": CHEAP, "name": "Cheap"}]}},
        }),
    ])
    await session.commit()

    async def resolved(db, manager_id, target_gw, picks_gw, use_override=True):
        return ResolvedSquad(player_ids=[HURT, MINE], bank=1, free_transfers=1, source="fpl_api", picks_gameweek=picks_gw)

    monkeypatch.setattr(story, "resolve_squad", resolved)


async def get(client, player=HURT, alert=None):
    q = f"?alert_id={alert}" if alert else ""
    return await client.get(f"/api/v1/news/story/{TEAM}/{player}{q}")


async def test_a_squad_warning_story(client, world):
    r = await get(client)
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["headline"] == "Pedro is injured"
    assert s["summary"] == "Thigh injury - Unknown return date"
    assert s["severity"] == "critical"
    assert s["player"]["photo"].endswith("/250x250/p1010.png")
    # Dated by the injury news, not the later price move.
    assert [h["event_type"] for h in s["history"]] == ["price_change", "ruled_out", "status_change"]
    assert s["published_at"] == s["history"][1]["at"]
    you = s["you"]
    assert (you["owned"], you["starting"], you["captain"]) == (True, True, True)
    assert you["plan"] == {"out": "Pedro", "in": "Cheap", "in_player_id": CHEAP}


async def test_replacements_are_affordable_fit_and_not_yours(client, world):
    s = (await get(client)).json()
    # Budget 7.8 + 0.1 bank: Star (8.0) and Pricey are out of reach, Doubt is
    # doubtful, Mine is already owned. Cheap is the one left.
    assert [r["name"] for r in s["replacements"]] == ["Cheap"]
    assert s["replacements"][0]["xpts_horizon"] == 16.0  # 4 gameweeks of 4.0
    assert len(s["fixtures"]) == 3


async def test_an_alert_story_uses_the_alert(client, session, world):
    alert_id = (await session.execute(Alert.__table__.select().where(Alert.fpl_entry_id == TEAM))).first().id
    s = (await get(client, alert=alert_id)).json()
    assert s["headline"] == "Pedro ruled out" and s["summary"] == "Thigh injury"


async def test_someone_elses_alert_is_404(client, session, world):
    other = (await session.execute(Alert.__table__.select().where(Alert.fpl_entry_id == 999))).first().id
    assert (await get(client, alert=other)).status_code == 404


async def test_unknown_player_is_404(client, world):
    assert (await get(client, player=9999)).status_code == 404


async def test_alerts_carry_the_photo_and_club(client, world):
    alerts = (await client.get(f"/api/v1/news/alerts/{TEAM}")).json()
    assert alerts[0]["team"] == "T1" and alerts[0]["photo"].endswith("/250x250/p1010.png")
