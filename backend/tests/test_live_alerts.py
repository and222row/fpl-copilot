"""
Pushes while matches are on: one per goal, assist and the like by a player in
your team, one full-time summary per match you have players in, never twice,
only inside the match window, and only to subscribers who want them.
"""
from datetime import timedelta

import pytest

from app.config import Settings
from app.models.accounts import FplAccount, Trial, User
from app.models.fpl import Fixture, Gameweek, utcnow
from app.models.notifications import Device, NotificationPreference
from app.services import live, live_alerts, push
from app.services.live_alerts import events_for
from tests.auth_helpers import USER_A, USER_B
from tests.conftest import make_player, make_team

GW = 8
TOKEN_A = "ExponentPushToken[aaaaaaaaaaaaaaaaaaaaaa]"
TOKEN_B = "ExponentPushToken[bbbbbbbbbbbbbbbbbbbbbb]"
NAMES = {1: "Raya", 2: "Saka", 3: "Haaland", 4: "Bench"}
TEAM_OF = {1: 1, 2: 1, 3: 2, 4: 2}
SHORT = {1: "ARS", 2: "MCI", 3: "LIV"}


def picks(chip=None, captain=2):
    # Three starters and one on the bench, enough to show who counts.
    return {"active_chip": chip, "entry_history": {}, "picks": [
        {"element": 1, "position": 1, "is_captain": captain == 1},
        {"element": 2, "position": 2, "is_captain": captain == 2},
        {"element": 3, "position": 3, "is_captain": captain == 3},
        {"element": 4, "position": 12, "is_captain": False},
    ]}


def match(fid=71, home=1, away=2, done=False, score=(2, 0), kickoff=None):
    return {"id": fid, "team_h": home, "team_a": away, "started": True, "finished_provisional": done, "finished": False,
            "team_h_score": score[0], "team_a_score": score[1],
            "kickoff_time": (kickoff or utcnow() - timedelta(minutes=50)).isoformat().replace("+00:00", "Z"), "stats": []}


def stat(identifier, value, points):
    return {"identifier": identifier, "value": value, "points": points}


EXPLAIN = {
    1: [{"fixture": 71, "stats": [stat("minutes", 90, 2), stat("clean_sheets", 1, 4)]}],
    2: [{"fixture": 71, "stats": [stat("minutes", 90, 2), stat("goals_scored", 2, 10), stat("assists", 1, 3)]}],
    3: [{"fixture": 71, "stats": [stat("minutes", 90, 2), stat("red_cards", 1, -3)]}],
    4: [{"fixture": 71, "stats": [stat("minutes", 20, 1), stat("goals_scored", 1, 4)]}],
}


def run(p=None, fixtures=None, bonus=None):
    fixtures = fixtures or {71: match()}
    return events_for(p or picks(), EXPLAIN, fixtures, bonus or {}, NAMES, TEAM_OF, SHORT, GW)


# ── What a manager hears ─────────────────────────────────────────────────────

def test_each_goal_and_assist_is_its_own_push_with_the_points():
    by_key = {e.key: e for e in run()}
    assert "8:71:2:goals_scored:1" in by_key and "8:71:2:goals_scored:2" in by_key
    goal = by_key["8:71:2:goals_scored:1"]
    assert goal.title == "Goal: Saka"
    assert goal.body == "ARS 2-0 MCI · +10 for you (captain)"
    assert by_key["8:71:2:assists:1"].body == "ARS 2-0 MCI · +6 for you (captain)"
    assert by_key["8:71:3:red_cards:1"].body == "ARS 2-0 MCI · −3 for you"


def test_the_bench_is_quiet_unless_bench_boost_is_on():
    assert not any(":4:" in e.key for e in run())
    assert any(e.key == "8:71:4:goals_scored:1" for e in run(picks(chip="bboost")))


def test_triple_captain_triples():
    goal = next(e for e in run(picks(chip="3xc")) if e.key == "8:71:2:goals_scored:1")
    assert "+15 for you" in goal.body


def test_full_time_sums_each_players_match_once_it_is_over():
    assert not any(e.key.endswith(":ft") for e in run())  # still playing
    ft = next(e for e in run(fixtures={71: match(done=True)}) if e.key == "8:71:ft")
    assert ft.title == "Full time: ARS 2-0 MCI"
    # Raya 6; Saka (2 + 10 + 3) x 2; Haaland 2 - 3.
    assert ft.body == "Raya 6, Saka 30 (C), Haaland −1"


def test_full_time_counts_provisional_bonus_and_says_so():
    ft = next(e for e in run(fixtures={71: match(done=True)}, bonus={71: {2: 3}}) if e.key == "8:71:ft")
    assert ft.body == "Raya 6, Saka 36 (C), Haaland −1 · bonus not yet confirmed"


def test_full_time_names_a_player_who_did_not_play():
    explain = {**EXPLAIN, 3: []}
    events = events_for(picks(), explain, {71: match(done=True)}, {}, NAMES, TEAM_OF, SHORT, GW)
    assert next(e for e in events if e.key == "8:71:ft").body.endswith("Haaland didn't play")


def test_matches_without_your_players_say_nothing():
    assert run(fixtures={99: match(fid=99, home=3, away=3, done=True)}) == []


# ── Sending ──────────────────────────────────────────────────────────────────

class FakeExpo:
    def __init__(self):
        self.sent: list[push.Message] = []

    async def send(self, messages):
        self.sent.extend(messages)
        return [{"status": "ok"} for _ in messages]


@pytest.fixture(autouse=True)
def fresh_memo():
    live.clear_memo()
    yield
    live.clear_memo()


@pytest.fixture
async def world(session, monkeypatch):
    session.add_all([make_team(1, "ARS"), make_team(2, "MCI")])
    session.add(Gameweek(id=GW, name="Gameweek 8", deadline_time=utcnow() - timedelta(days=1)))
    await session.flush()
    for pid, name in NAMES.items():
        session.add(make_player(pid, team_id=TEAM_OF[pid], web_name=name))
    session.add(Fixture(id=71, gameweek_id=GW, team_h=1, team_a=2, kickoff_time=utcnow() - timedelta(minutes=50)))
    session.add_all([User(id=USER_A), User(id=USER_B)])
    await session.flush()
    for user, entry, token in ((USER_A, 1001, TOKEN_A), (USER_B, 1002, TOKEN_B)):
        session.add(FplAccount(user_id=user, fpl_entry_id=entry, team_name="T"))
        session.add(Device(user_id=user, token=token, platform="ios"))
    # Only A is a subscriber.
    session.add(Trial(fpl_entry_id=1001, user_id=USER_A, started_at=utcnow() - timedelta(days=1), ends_at=utcnow() + timedelta(days=29)))
    await session.commit()

    fpl = {"live": 0, "fixtures": [match()]}

    async def fake_live(gw):
        fpl["live"] += 1
        return {"elements": [{"id": e, "stats": {}, "explain": x} for e, x in EXPLAIN.items()]}

    async def fake_fixtures(gw):
        return fpl["fixtures"]

    async def fake_picks(entry, gw):
        return picks()

    monkeypatch.setattr(live, "fetch_live_points", fake_live)
    monkeypatch.setattr(live, "fetch_event_fixtures", fake_fixtures)
    monkeypatch.setattr(live, "fetch_event_picks", fake_picks)
    expo = FakeExpo()
    monkeypatch.setattr(push, "send", expo.send)
    return expo, fpl


async def test_a_tick_sends_each_event_once(session, world):
    expo, _ = world
    result = await live_alerts.tick(session)
    assert result["active"] and result["sent"] == 4  # Saka's two goals and assist, Haaland's red card
    assert {m.token for m in expo.sent} == {TOKEN_A}  # B has no subscription
    assert {m.data["type"] for m in expo.sent} == {"live"}

    expo.sent.clear()
    assert (await live_alerts.tick(session))["sent"] == 0
    assert expo.sent == []


async def test_full_time_follows_when_the_match_ends(session, world):
    expo, fpl = world
    await live_alerts.tick(session)
    expo.sent.clear()
    fpl["fixtures"] = [match(done=True)]
    live.clear_memo()
    await live_alerts.tick(session)
    assert [m.title for m in expo.sent] == ["Full time: ARS 2-0 MCI"]


async def test_switched_off_means_nothing(session, world):
    expo, _ = world
    session.add(NotificationPreference(user_id=USER_A, live=False))
    await session.commit()
    await live_alerts.tick(session)
    assert expo.sent == []


async def test_outside_a_match_window_fpl_is_not_called(session, world):
    expo, fpl = world
    fixture = await session.get(Fixture, 71)
    fixture.kickoff_time = utcnow() - timedelta(hours=5)
    await session.commit()
    assert await live_alerts.tick(session) == {"active": False}
    assert fpl["live"] == 0 and expo.sent == []


async def test_an_old_match_in_the_same_gameweek_is_not_resent(session, world):
    expo, fpl = world
    # Saturday's match is in FPL's data, but only Monday's is in its window.
    fpl["fixtures"] = [match(kickoff=utcnow() - timedelta(days=2), done=True), match(fid=72, home=3, away=3)]
    await live_alerts.tick(session)
    assert expo.sent == []


@pytest.mark.parametrize("environment,explicit,on", [
    ("production", None, True), ("development", None, False), ("production", False, False), ("development", True, True),
])
def test_on_in_production_unless_told_otherwise(environment, explicit, on):
    assert Settings(environment=environment, live_alerts_enabled=explicit).live_alerts_on is on
