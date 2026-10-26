"""
Advice worked out ahead: the default recommendation is stored per team, keyed
on a fingerprint of its inputs, served while they are unchanged, and
recomputed when projections are rebuilt, transfers are recorded or it ages out.
"""
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.models.accounts import FplAccount, Trial, User
from app.models.feedback import AdviceCache, RecommendationSnapshot, SquadOverride
from app.models.fpl import SyncState, utcnow
from app.services import advice
from app.services.projection import PROJECTIONS_BUILT_KEY
from app.services.squad_state import ResolvedSquad
from tests.conftest import make_gameweek, make_player, make_projection, make_team

TEAM = 1234
# Two keepers, five defenders, five midfielders, three forwards, from 15 clubs.
SQUAD = list(range(1, 16))
POSITIONS = {**{i: 1 for i in (1, 2)}, **{i: 2 for i in range(3, 8)}, **{i: 3 for i in range(8, 13)}, **{i: 4 for i in (13, 14, 15)}}
# A stronger player per position on the market, from clubs 16-19.
POOL = {101: 1, 102: 2, 103: 3, 104: 4}


@pytest.fixture
async def world(session, monkeypatch):
    session.add_all([make_team(t, f"T{t:02d}") for t in range(1, 21)])
    session.add_all([make_gameweek(g) for g in range(1, 7)])
    await session.flush()
    for pid, pos in POSITIONS.items():
        session.add(make_player(pid, team_id=pid, position=pos, now_cost=50, web_name=f"P{pid}"))
    for i, (pid, pos) in enumerate(POOL.items()):
        session.add(make_player(pid, team_id=16 + i, position=pos, now_cost=50, web_name=f"Star{pos}"))
    await session.flush()
    for gw in range(2, 7):
        for pid in POSITIONS:
            session.add(make_projection(pid, gw, xpts=3.0))
        for pid in POOL:
            session.add(make_projection(pid, gw, xpts=6.0))
    session.add(SyncState(key=PROJECTIONS_BUILT_KEY, at=utcnow()))
    await session.commit()

    calls = []

    async def resolved(db, manager_id, target_gw, picks_gw):
        calls.append(manager_id)
        if manager_id == 666:
            raise RuntimeError("FPL hiccup")
        return ResolvedSquad(player_ids=SQUAD, bank=5, free_transfers=1, source="fpl_api", picks_gameweek=picks_gw)

    monkeypatch.setattr(advice, "resolve_squad", resolved)
    return calls


async def get(client, query=""):
    r = await client.get(f"/api/v1/decisions/{TEAM}{query}")
    assert r.status_code == 200, r.text
    return r.json()


async def test_the_second_request_is_served_from_the_cache(client, session, world):
    first = await get(client)
    assert world == [TEAM]
    assert first["transfer"]["action"].startswith("TRANSFER")
    second = await get(client)
    assert world == [TEAM], "a cached answer reads no squad"
    assert second == first
    assert (await session.get(AdviceCache, TEAM)).gameweek_id == 2


async def test_a_projection_rebuild_recomputes(client, session, world):
    await get(client)
    stamp = await session.get(SyncState, PROJECTIONS_BUILT_KEY)
    stamp.at = utcnow() + timedelta(seconds=5)
    await session.commit()
    await get(client)
    assert world == [TEAM, TEAM]


async def test_recorded_transfers_recompute(client, session, world):
    await get(client)
    session.add(SquadOverride(fpl_entry_id=TEAM, gameweek_id=2, player_ids=SQUAD, bank=0, free_transfers=0,
                              transfers_applied=[{"out": 3, "in": 103}]))
    await session.commit()
    await get(client)
    assert len(world) == 2


async def test_old_advice_ages_out(client, session, world):
    await get(client)
    row = await session.get(AdviceCache, TEAM)
    row.computed_at = utcnow() - advice.MAX_AGE - timedelta(minutes=1)
    await session.commit()
    await get(client)
    assert len(world) == 2


async def test_other_options_are_never_cached(client, world):
    await get(client)
    await get(client, "?horizon=3")
    await get(client, "?captain_mode=safe")
    assert len(world) == 3


async def test_time_dependent_fields_are_current_when_served(client, session, world):
    await get(client)
    row = await session.get(AdviceCache, TEAM)
    row.body = {**row.body, "recorded_for_accuracy": True, "gameweek": {**row.body["gameweek"], "deadline_passed": True}}
    await session.commit()
    body = await get(client)
    assert body["gameweek"]["deadline_passed"] is False  # GW2's deadline is days away


# ── Working it out ahead ─────────────────────────────────────────────────────

async def subscriber(session, entry: int, premium: bool = True) -> uuid.UUID:
    user_id = uuid.uuid4()
    session.add(User(id=user_id))
    await session.flush()
    session.add(FplAccount(user_id=user_id, fpl_entry_id=entry, team_name=f"Team {entry}"))
    if premium:
        session.add(Trial(fpl_entry_id=entry, user_id=user_id, started_at=utcnow() - timedelta(days=1),
                          ends_at=utcnow() + timedelta(days=29)))
    await session.commit()
    return user_id


async def test_precompute_fills_the_cache_for_subscribers_only(client, session, world):
    await subscriber(session, TEAM)
    await subscriber(session, 5678, premium=False)

    report = await advice.precompute(session)
    assert (report["computed"], report["not_premium"], report["failed"]) == (1, 1, 0)
    assert world == [TEAM]
    # The advice is saved for the track record and the deadline reminder.
    snaps = await session.scalar(select(func.count()).select_from(RecommendationSnapshot).where(
        RecommendationSnapshot.fpl_entry_id == TEAM))
    assert snaps == 3

    # Opening the app now reads it, and a second run finds nothing to do.
    await get(client)
    assert world == [TEAM]
    assert (await advice.precompute(session))["already_fresh"] == 1


async def test_one_failing_team_does_not_stop_the_rest(session, world):
    await subscriber(session, 666)
    await subscriber(session, TEAM)
    report = await advice.precompute(session)
    assert (report["computed"], report["failed"]) == (1, 1)


async def test_teams_beyond_the_budget_wait_for_the_app(session, world):
    await subscriber(session, TEAM)
    report = await advice.precompute(session, budget_seconds=-1)
    assert (report["computed"], report["deferred"]) == (0, 1)
