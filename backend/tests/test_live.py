"""
The live gameweek: bonus from BPS, projected automatic substitutions and
captaincy, chips, and the live league table. FPL is faked with payloads shaped
like the real /event/{gw}/live/, /fixtures/?event= and picks responses.
scripts/live_check.py compares the same code with FPL's own totals.
"""
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.models.fpl import Gameweek
from app.services import leagues, live
from app.services.live import DONE, PLAYING, TO_PLAY, PlayerLive, bonus_from_bps, players_live, provisional_bonus, team_live
from tests.conftest import make_player, make_team

NOW = datetime.now(timezone.utc)
GW = 8

# A 3-4-3: GKP 1; DEF 2-4; MID 5-8; FWD 9-11. Bench: GKP 12, DEF 13, MID 14, FWD 15.
TYPES = {1: 1, 2: 2, 3: 2, 4: 2, 5: 3, 6: 3, 7: 3, 8: 3, 9: 4, 10: 4, 11: 4, 12: 1, 13: 2, 14: 3, 15: 4}


@pytest.fixture(autouse=True)
def fresh_memo():
    live.clear_memo()
    yield
    live.clear_memo()


def picks(captain=9, vice=10, chip=None, cost=0, total=500, points=None, order=None):
    order = order or list(range(1, 16))
    return {
        "active_chip": chip,
        "automatic_subs": [],
        "entry_history": {"event": GW, "points": points or 0, "total_points": total, "event_transfers_cost": cost},
        "picks": [
            {"element": e, "position": slot, "multiplier": 1 if slot <= 11 else 0, "element_type": TYPES[e],
             "is_captain": e == captain, "is_vice_captain": e == vice}
            for slot, e in enumerate(order, start=1)
        ],
    }


def played(points=2, minutes=90, bonus=0, state=DONE):
    return PlayerLive(points, bonus, minutes, state)


def everyone(**overrides) -> dict[int, PlayerLive]:
    """Every starter played for 2 points; the bench didn't play. Override by id: p5=..."""
    out = {e: played() if e <= 11 else played(0, 0) for e in TYPES}
    out.update({int(k[1:]): v for k, v in overrides.items()})
    return out


# ── Bonus ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bps,expected", [
    ([(1, 40), (2, 30), (3, 20), (4, 10)], {1: 3, 2: 2, 3: 1}),
    ([(1, 30), (2, 30), (3, 20), (4, 10)], {1: 3, 2: 3, 3: 1}),  # tie for first
    ([(1, 40), (2, 30), (3, 30), (4, 10)], {1: 3, 2: 2, 3: 2}),  # tie for second
    ([(1, 40), (2, 30), (3, 20), (4, 20)], {1: 3, 2: 2, 3: 1, 4: 1}),  # tie for third
    ([(1, 30), (2, 30), (3, 30), (4, 10)], {1: 3, 2: 3, 3: 3}),
    ([], {}),
])
def test_bonus_follows_fpl_tie_rules(bps, expected):
    assert bonus_from_bps(bps) == expected


def fixture(fid, home, away, state, bps=(), bonus=()):
    return {
        "id": fid, "team_h": home, "team_a": away, "kickoff_time": f"2026-10-24T1{fid % 10}:00:00Z",
        "started": state != TO_PLAY, "finished_provisional": state == DONE, "finished": False,
        "stats": [
            {"identifier": "bps", "h": [{"element": e, "value": v} for e, v in bps], "a": []},
            {"identifier": "bonus", "h": [{"element": e, "value": v} for e, v in bonus], "a": []},
        ],
    }


def test_provisional_bonus_only_where_fpl_has_not_confirmed_it():
    fixtures = [
        fixture(1, 1, 2, PLAYING, bps=[(5, 30), (6, 20), (7, 10)]),
        fixture(2, 3, 4, DONE, bps=[(8, 50), (9, 1)], bonus=[(8, 3)]),  # confirmed: already in points
        fixture(3, 5, 6, TO_PLAY, bps=[(10, 99)]),
    ]
    assert provisional_bonus(fixtures) == {5: 3, 6: 2, 7: 1}


def test_player_state_follows_their_clubs_matches():
    fixtures = [fixture(1, 1, 2, DONE), fixture(2, 3, 4, PLAYING), fixture(3, 1, 5, TO_PLAY)]  # club 1 has a double
    team_of = {100: 1, 200: 2, 300: 3, 600: 6, 700: None}
    elements = {"elements": [{"id": e, "stats": {"total_points": 1, "minutes": 10}} for e in team_of]}
    state = {e: p.state for e, p in players_live(elements, fixtures, team_of).items()}
    assert state == {100: TO_PLAY, 200: DONE, 300: PLAYING, 600: DONE, 700: TO_PLAY}  # 600 blanks


# ── Substitutions and captaincy ──────────────────────────────────────────────

def test_a_starter_who_did_not_play_gives_way_to_the_first_bench_player_who_did():
    t = team_live(picks(), everyone(p2=played(0, 0), p13=played(0, 0), p14=played(3)))
    # 13 (DEF) didn't play, so 14 (MID) comes in: 2 DEF left is illegal, so not
    # for DEF 2... unless the formation allows it. It doesn't, so no sub at all.
    assert t.auto_subs == []

    t = team_live(picks(), everyone(p2=played(0, 0), p13=played(6)))
    assert t.auto_subs == [(2, 13)]
    assert t.points == 10 * 2 + 2 + 6  # ten starters, the captain doubled, plus the sub


def test_bench_players_who_did_not_play_are_passed_over():
    t = team_live(picks(), everyone(p5=played(0, 0), p13=played(0, 0), p14=played(5)))
    assert t.auto_subs == [(5, 14)]


def test_goalkeepers_only_replace_goalkeepers():
    t = team_live(picks(), everyone(p1=played(0, 0), p5=played(0, 0), p12=played(4)))
    assert t.auto_subs == [(1, 12)]  # the keeper; MID 5 has no outfield sub who played


def test_nobody_is_subbed_off_before_their_match():
    t = team_live(picks(), everyone(p5=played(0, 0, state=TO_PLAY), p14=played(5)))
    assert t.auto_subs == []
    assert t.players_left == 1


def test_the_vice_captain_steps_in_when_the_captain_does_not_play():
    t = team_live(picks(captain=9, vice=10), everyone(p9=played(0, 0), p10=played(7), p15=played(1)))
    assert t.armband == 10
    rows = {r["element"]: r for r in t.rows}
    assert rows[10]["multiplier"] == 2 and rows[9]["multiplier"] == 0 and rows[15]["subbed_in"]


def test_nobody_is_doubled_when_neither_captain_plays():
    t = team_live(picks(captain=9, vice=10), everyone(p9=played(0, 0), p10=played(0, 0)))
    assert t.armband is None
    assert all(r["multiplier"] <= 1 for r in t.rows)


def test_triple_captain_and_hits():
    t = team_live(picks(chip="3xc", cost=4), everyone(p9=played(10)))
    assert t.points == 10 * 2 + 10 * 3 - 4
    assert t.transfer_cost == 4


def test_bench_boost_counts_the_bench_and_makes_no_subs():
    t = team_live(picks(chip="bboost"), everyone(p2=played(0, 0), p13=played(6), p14=played(1)))
    assert t.auto_subs == []
    assert t.points == 9 * 2 + 2 * 2 + 0 + 6 + 1  # starters (2 scored 0), captain, bench


def test_provisional_bonus_counts_and_is_doubled_for_the_captain():
    t = team_live(picks(captain=9), everyone(p9=played(5, bonus=3, state=PLAYING)))
    assert t.provisional_bonus == 6
    assert t.points == 10 * 2 + (5 + 3) * 2
    assert t.players_left == 1


def test_fpls_own_substitutions_are_kept():
    # FPL has already brought 13 on for 2: it swapped their slots.
    order = [1, 13, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 2, 14, 15]
    t = team_live(picks(order=order), everyone(p2=played(0, 0), p13=played(6)))
    assert t.auto_subs == []
    assert t.points == 10 * 2 + 2 + 6


# ── Swing players ────────────────────────────────────────────────────────────

def test_swing_against_a_rival_is_the_difference_in_multipliers():
    players = everyone(p9=played(0, 0, state=TO_PLAY), p10=played(0, 0, state=TO_PLAY), p11=played(0, 0, state=TO_PLAY))
    you = team_live(picks(captain=9, vice=10), players)
    # The rival captains 10 instead, and has 14 where you have 11.
    them = team_live(picks(captain=10, vice=9, order=[*range(1, 11), 14, 12, 13, 11, 15]), players)
    out = live.swing(you, them, [them], players)
    versus = {r["player_id"]: r for r in out["against_rival"]}
    assert versus[9] == {"player_id": 9, "you": 2, "them": 1, "net": 1}
    assert versus[10]["net"] == -1
    assert versus[11]["net"] == 1
    assert 5 not in versus  # same multiplier for both: decides nothing
    assert 14 not in versus  # their MID 14 for your FWD 11 is a different position; 14 has played already


def test_swing_lists_only_players_still_to_play():
    players = everyone(p9=played(0, 0, state=TO_PLAY))
    you = team_live(picks(captain=9), players)
    them = team_live(picks(captain=10), players)
    out = live.swing(you, them, [them], players)
    assert [r["player_id"] for r in out["against_rival"]] == [9]  # 10's match is over


def test_swing_against_the_league_uses_effective_ownership():
    players = everyone(**{f"p{i}": played(0, 0, state=TO_PLAY) for i in TYPES})
    you = team_live(picks(captain=9), players)
    field = [team_live(picks(captain=10), players) for _ in range(3)]
    out = live.swing(you, None, field, players)
    for_you = {r["player_id"]: r for r in out["for_you"]}
    against = {r["player_id"]: r for r in out["against_you"]}
    assert for_you[9] == {"player_id": 9, "you": 2, "eo": 1.0, "net": 1.0}
    assert against[10] == {"player_id": 10, "you": 1, "eo": 2.0, "net": -1.0}
    assert out["against_rival"] == []


# ── The API ──────────────────────────────────────────────────────────────────

YOU, RIVAL, THIRD = 6727534, 4276486, 1055545
PRIVATE = 911741


@pytest.fixture
async def world(session, monkeypatch):
    aaa, bbb = make_team(1, "AAA"), make_team(2, "BBB")
    aaa.code, bbb.code = 3, 43
    session.add_all([aaa, bbb])
    session.add_all([
        Gameweek(id=GW, name="Gameweek 8", deadline_time=NOW - timedelta(days=2), average_entry_score=45, highest_score=120),
        Gameweek(id=GW + 1, name="Gameweek 9", deadline_time=NOW + timedelta(days=5)),
    ])
    await session.flush()
    for e, t in TYPES.items():
        session.add(make_player(e, team_id=1 if e % 2 else 2, web_name=f"P{e}", position=t))
    await session.commit()

    calls = {"live": 0, "picks": 0}
    # Club 1 (odd ids) has finished; club 2 (even ids) is playing; 4 leads its BPS.
    fixtures = [fixture(1, 1, 3, DONE), fixture(2, 2, 4, PLAYING, bps=[(4, 40), (6, 30), (8, 20)])]

    async def fake_live(gw):
        calls["live"] += 1
        return {"elements": [
            {"id": e, "stats": {"total_points": 0 if e in (3, 12) else 2, "minutes": 0 if e in (3, 12) else 90}}
            for e in TYPES
        ]}

    async def fake_fixtures(gw):
        return fixtures

    squads = {
        YOU: picks(captain=9, total=500, points=20),
        # FPL's table, which lags, still has the rival 20 ahead of you.
        RIVAL: picks(captain=4, total=495, points=20, cost=4),
        THIRD: picks(captain=1, total=480, points=20),
    }

    async def fake_picks(manager_id, gw):
        calls["picks"] += 1
        if manager_id not in squads:
            raise httpx.HTTPStatusError("404", request=httpx.Request("GET", "x"), response=httpx.Response(404))
        return squads[manager_id]

    async def info(manager_id):
        return {"leagues": {"classic": [
            {"id": PRIVATE, "name": "Mates", "league_type": "x", "rank_count": 3, "entry_rank": 2, "entry_last_rank": 2},
        ]}}

    async def table(league_id, page=1):
        rows = [(1, RIVAL, "Rivals", 520, 20), (2, YOU, "Andrew's Team", 500, 20), (3, THIRD, "Third", 480, 20)]
        return {"league": {"id": PRIVATE, "name": "Mates"}, "standings": {"results": [
            {"rank": r, "last_rank": r, "rank_sort": r, "entry": e, "entry_name": n, "player_name": f"M{r}",
             "total": t, "event_total": ev} for r, e, n, t, ev in rows
        ]}}

    monkeypatch.setattr(live, "fetch_live_points", fake_live)
    monkeypatch.setattr(live, "fetch_event_fixtures", fake_fixtures)
    monkeypatch.setattr(live, "fetch_event_picks", fake_picks)
    monkeypatch.setattr(leagues, "fetch_manager_info", info)
    monkeypatch.setattr(leagues, "fetch_league_standings", table)
    return calls, squads


async def test_my_live_points(client, world):
    body = (await client.get(f"/api/v1/live/{YOU}")).json()
    assert body["gameweek"] == {"id": GW, "name": "Gameweek 8", "average": 45, "highest": 120}
    assert body["in_play"] is True and body["finished"] is False
    assert (body["matches_done"], body["matches_total"]) == (1, 2)
    # 3 (DEF, club 1, done) didn't play: 13 is on the bench and played. 4 has
    # 3 provisional bonus, 6 has 2, 8 has 1. The captain, 9, is doubled.
    assert body["auto_subs"] == [{"out": "P3", "in": "P13"}]
    assert body["provisional_bonus"] == 6
    assert body["points"] == 11 * 2 + 2 + 6
    assert body["total"] == 500 - 20 + body["points"]
    assert body["players_left"] == 5  # 2, 4, 6, 8, 10 are playing
    assert (body["captain"], body["armband"]) == ("P9", "P9")

    squad = {p["name"]: p for p in body["squad"]}
    assert squad["P4"]["points"] == 5 and squad["P4"]["provisional_bonus"] == 3 and squad["P4"]["state"] == PLAYING
    assert squad["P3"]["subbed_out"] and not squad["P3"]["starting"]
    assert squad["P13"]["subbed_in"] and squad["P13"]["starting"]
    assert squad["P9"]["multiplier"] == 2 and squad["P9"]["kit"]


async def test_live_data_is_shared_between_requests(client, world):
    calls, _ = world
    await client.get(f"/api/v1/live/{YOU}")
    await client.get(f"/api/v1/live/{YOU}")
    assert calls == {"live": 1, "picks": 1}


async def test_no_squad_this_gameweek_is_404(client, world):
    _, squads = world
    del squads[YOU]
    r = await client.get(f"/api/v1/live/{YOU}")
    assert r.status_code == 404
    assert "after its deadline" in r.json()["detail"]


async def test_fpl_down_is_503(client, world, monkeypatch):
    async def down(gw):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(live, "fetch_live_points", down)
    assert (await client.get(f"/api/v1/live/{YOU}")).status_code == 503


async def test_live_league_reranks_by_live_points(client, world):
    body = (await client.get(f"/api/v1/live/{YOU}/leagues/{PRIVATE}")).json()
    rows = {r["entry"]: r for r in body["standings"]}
    you, rival = rows[YOU], rows[RIVAL]
    # Same players, but the rival captained 4 (bonus) and took a hit.
    assert you["gameweek_points"] == 30
    assert rival["gameweek_points"] == 11 * 2 + 2 + 6 - 2 + 5 - 4
    # Before the gameweek: FPL's total, less this gameweek's points, with the hit added back.
    assert you["total"] == 500 - 20 + 30 and rival["total"] == 495 - 20 + 4 + rival["gameweek_points"]
    assert [r["entry"] for r in body["standings"]] == [YOU, RIVAL, THIRD]
    assert (you["live_rank"], you["rank"]) == (1, 2)
    assert body["your_live_rank"] == 1 and body["gap_to_next"] is None
    assert you["captain"] == "P9" and rival["captain"] == "P4"
    assert body["partial"] is False

    # You lead, so the swing is against the manager just behind you. Same
    # squads; you captain 9 (match over), they captain 4 (still playing).
    swing = body["swing"]
    assert swing["rival"] == {"entry": RIVAL, "team_name": "Rivals", "gap": rival["total"] - you["total"]}
    assert swing["managers"] == 2
    versus = {r["name"]: r for r in swing["against_rival"]}
    assert set(versus) == {"P4"}
    assert (versus["P4"]["you"], versus["P4"]["them"], versus["P4"]["net"], versus["P4"]["state"]) == (1, 2, -1, PLAYING)


async def test_a_manager_without_live_picks_keeps_fpls_figures(client, world):
    _, squads = world
    del squads[THIRD]
    body = (await client.get(f"/api/v1/live/{YOU}/leagues/{PRIVATE}")).json()
    third = next(r for r in body["standings"] if r["entry"] == THIRD)
    assert (third["total"], third["gameweek_points"], third["players_left"]) == (480, 20, None)


async def test_you_outside_the_sample_get_no_live_rank(client, world, monkeypatch):
    monkeypatch.setattr(live, "LIVE_LEAGUE_SAMPLE", 1)
    body = (await client.get(f"/api/v1/live/{YOU}/leagues/{PRIVATE}")).json()
    assert body["partial"] is True and body["managers_read"] == 1
    you = next(r for r in body["standings"] if r["is_you"])
    assert you["live_rank"] is None and body["your_live_rank"] is None
    assert body["standings"][-1]["is_you"]


async def test_another_managers_team_scored_live(client, world):
    body = (await client.get(f"/api/v1/live/{YOU}/managers/{RIVAL}")).json()
    # The rival's squad, captain 4, with the hit FPL charged them.
    assert body["captain"] == "P4" and body["transfer_cost"] == 4
    assert len(body["squad"]) == 15 and body["squad"][0]["kit"]
    assert (await client.get(f"/api/v1/live/{YOU}/managers/999")).status_code == 404  # no squad this gameweek
    assert (await client.get(f"/api/v1/live/{YOU}/managers/0")).status_code == 422


async def test_a_league_you_are_not_in_is_404(client, world):
    assert (await client.get(f"/api/v1/live/{YOU}/leagues/999")).status_code == 404
