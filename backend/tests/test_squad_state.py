"""
Squad-state resolution tests.

The bug these exist for: FPL's public API cannot show transfers made for a
gameweek that has not started, so the app was advising on the squad locked at
the *previous* deadline — and re-suggesting transfers the manager had already
made. Confirmed against the live API:

    /entry/{id}/event/{next_gw}/picks/   404
    /entry/{id}/transfers/               omits pending moves
    /my-team/{id}/                       403 without the manager's own login

The data is genuinely not exposed, so the fix is to let the manager correct it
and to never present a stale squad as current.
"""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from tests.conftest import make_team, make_player
from app.models.fpl import Gameweek
from app.models.feedback import SquadOverride
from app.services.squad_state import (
    resolve_squad, apply_transfers, save_override, clear_override,
    prune_stale_overrides, SOURCE_FPL, SOURCE_OVERRIDE,
)


def gw(gw_id: int, days: float) -> Gameweek:
    return Gameweek(
        id=gw_id,
        name=f"Gameweek {gw_id}",
        deadline_time=datetime.now(timezone.utc) + timedelta(days=days),
    )


OWNED = list(range(1, 16))


@pytest.fixture
async def squad(session):
    """GW1 played, GW2 open — the situation where the bug appears."""
    session.add_all([make_team(1, "AAA"), make_team(2, "BBB")])
    session.add_all([gw(1, -4), gw(2, +3)])
    await session.flush()
    for pid in OWNED:
        session.add(make_player(pid, team_id=1, now_cost=50, web_name=f"Own{pid}"))
    # Replacements
    for pid in (100, 101, 102):
        session.add(make_player(pid, team_id=2, now_cost=60, web_name=f"New{pid}"))
    session.add(make_player(103, team_id=2, now_cost=40, web_name="Cheap"))
    await session.commit()
    return session


def _fpl_picks(bank: int = 5, limit: int = 1):
    return AsyncMock(return_value={
        "picks": [{"element": pid, "position": i + 1, "is_captain": False,
                   "is_vice_captain": False, "multiplier": 1}
                  for i, pid in enumerate(OWNED)],
        "entry_history": {"bank": bank, "value": 1000},
        "transfers": {"limit": limit},
    })


# ── Falling back to FPL ──────────────────────────────────────────────────────

async def test_without_an_override_it_uses_fpl(squad):
    with patch("app.services.squad_state.fetch_manager_picks", _fpl_picks()):
        r = await resolve_squad(squad, 1, target_gw=2, picks_gw=1)
    assert r.source == SOURCE_FPL
    assert r.player_ids == OWNED
    assert r.bank == 5


async def test_a_stale_warning_is_attached_when_gameweeks_differ(squad):
    """The user must be told the squad may predate their transfers."""
    with patch("app.services.squad_state.fetch_manager_picks", _fpl_picks()):
        r = await resolve_squad(squad, 1, target_gw=2, picks_gw=1)
    assert r.stale_warning is not None
    assert "GW1" in r.stale_warning and "GW2" in r.stale_warning


async def test_no_warning_when_target_and_picks_match(squad):
    with patch("app.services.squad_state.fetch_manager_picks", _fpl_picks()):
        r = await resolve_squad(squad, 1, target_gw=1, picks_gw=1)
    assert r.stale_warning is None


async def test_null_transfer_limit_floors_at_one(squad):
    """FPL returns null before the first deadline."""
    with patch("app.services.squad_state.fetch_manager_picks", _fpl_picks(limit=None)):
        r = await resolve_squad(squad, 1, target_gw=2, picks_gw=1)
    assert r.free_transfers == 1


# ── Recording transfers ──────────────────────────────────────────────────────

async def test_recording_a_transfer_swaps_the_player(squad):
    # Bank must cover the £1.0m upgrade, or the (correct) affordability check fires
    with patch("app.services.squad_state.fetch_manager_picks", _fpl_picks(bank=20)):
        r = await apply_transfers(
            squad, manager_id=1, gameweek_id=2, picks_gw=1,
            moves=[{"out": 1, "in": 100}],
            player_costs={1: 50, 100: 60},
        )
    assert r.source == SOURCE_OVERRIDE
    assert 1 not in r.player_ids
    assert 100 in r.player_ids
    assert len(r.player_ids) == 15


async def test_bank_moves_with_the_transfer(squad):
    """Selling at 50 and buying at 60 costs 10."""
    with patch("app.services.squad_state.fetch_manager_picks", _fpl_picks(bank=20)):
        r = await apply_transfers(
            squad, manager_id=1, gameweek_id=2, picks_gw=1,
            moves=[{"out": 1, "in": 100}],
            player_costs={1: 50, 100: 60},
        )
    assert r.bank == 10


async def test_bank_increases_when_downgrading(squad):
    with patch("app.services.squad_state.fetch_manager_picks", _fpl_picks(bank=0)):
        r = await apply_transfers(
            squad, manager_id=1, gameweek_id=2, picks_gw=1,
            moves=[{"out": 1, "in": 103}],
            player_costs={1: 50, 103: 40},
        )
    assert r.bank == 10


async def test_free_transfers_are_consumed(squad):
    with patch("app.services.squad_state.fetch_manager_picks", _fpl_picks(limit=2)):
        r = await apply_transfers(
            squad, manager_id=1, gameweek_id=2, picks_gw=1,
            moves=[{"out": 1, "in": 100}, {"out": 2, "in": 101}],
            player_costs={1: 50, 2: 50, 100: 50, 101: 50},
        )
    assert r.free_transfers == 0


async def test_free_transfers_never_go_negative(squad):
    with patch("app.services.squad_state.fetch_manager_picks", _fpl_picks(limit=1)):
        r = await apply_transfers(
            squad, manager_id=1, gameweek_id=2, picks_gw=1,
            moves=[{"out": 1, "in": 100}, {"out": 2, "in": 101},
                   {"out": 3, "in": 102}],
            player_costs={i: 50 for i in (1, 2, 3, 100, 101, 102)},
        )
    assert r.free_transfers == 0


async def test_multiple_transfers_all_apply(squad):
    """The real case: three transfers made at once."""
    with patch("app.services.squad_state.fetch_manager_picks", _fpl_picks(bank=50)):
        r = await apply_transfers(
            squad, manager_id=1, gameweek_id=2, picks_gw=1,
            moves=[{"out": 1, "in": 100}, {"out": 2, "in": 101},
                   {"out": 3, "in": 102}],
            player_costs={1: 50, 2: 50, 3: 50, 100: 50, 101: 50, 102: 50},
        )
    assert len(r.player_ids) == 15
    assert {1, 2, 3}.isdisjoint(r.player_ids)
    assert {100, 101, 102}.issubset(r.player_ids)
    assert len(r.transfers_applied) == 3


# ── Rejecting nonsense ───────────────────────────────────────────────────────

async def test_selling_a_player_you_do_not_own_is_rejected(squad):
    with patch("app.services.squad_state.fetch_manager_picks", _fpl_picks()):
        with pytest.raises(ValueError, match="not in the squad"):
            await apply_transfers(
                squad, manager_id=1, gameweek_id=2, picks_gw=1,
                moves=[{"out": 999, "in": 100}],
                player_costs={999: 50, 100: 50},
            )


async def test_buying_a_player_you_already_own_is_rejected(squad):
    with patch("app.services.squad_state.fetch_manager_picks", _fpl_picks()):
        with pytest.raises(ValueError, match="already in the squad"):
            await apply_transfers(
                squad, manager_id=1, gameweek_id=2, picks_gw=1,
                moves=[{"out": 1, "in": 2}],
                player_costs={1: 50, 2: 50},
            )


async def test_an_unaffordable_transfer_is_rejected(squad):
    """A negative bank means the recorded state is wrong."""
    with patch("app.services.squad_state.fetch_manager_picks", _fpl_picks(bank=0)):
        with pytest.raises(ValueError, match="bank"):
            await apply_transfers(
                squad, manager_id=1, gameweek_id=2, picks_gw=1,
                moves=[{"out": 1, "in": 100}],
                player_costs={1: 40, 100: 150},
            )


async def test_a_rejected_transfer_leaves_no_override(squad):
    with patch("app.services.squad_state.fetch_manager_picks", _fpl_picks()):
        with pytest.raises(ValueError):
            await apply_transfers(
                squad, manager_id=1, gameweek_id=2, picks_gw=1,
                moves=[{"out": 999, "in": 100}],
                player_costs={999: 50, 100: 50},
            )
        r = await resolve_squad(squad, 1, target_gw=2, picks_gw=1)
    assert r.source == SOURCE_FPL


# ── Lifecycle ────────────────────────────────────────────────────────────────

async def test_override_takes_precedence_over_fpl(squad):
    await save_override(
        squad, manager_id=1, gameweek_id=2,
        player_ids=[100, 101, 102] + OWNED[3:],
        bank=7, free_transfers=0,
    )
    with patch("app.services.squad_state.fetch_manager_picks", _fpl_picks()):
        r = await resolve_squad(squad, 1, target_gw=2, picks_gw=1)
    assert r.source == SOURCE_OVERRIDE
    assert r.bank == 7
    assert 100 in r.player_ids


async def test_saving_twice_updates_rather_than_duplicates(squad):
    from sqlalchemy import select, func
    for bank in (5, 9):
        await save_override(
            squad, manager_id=1, gameweek_id=2,
            player_ids=OWNED, bank=bank, free_transfers=1,
        )
    count = (await squad.execute(
        select(func.count()).select_from(SquadOverride)
    )).scalar()
    assert count == 1
    row = (await squad.execute(select(SquadOverride))).scalars().first()
    assert row.bank == 9


async def test_overrides_are_isolated_per_gameweek(squad):
    await save_override(squad, manager_id=1, gameweek_id=2,
                        player_ids=OWNED, bank=1, free_transfers=1)
    with patch("app.services.squad_state.fetch_manager_picks", _fpl_picks()):
        gw2 = await resolve_squad(squad, 1, target_gw=2, picks_gw=1)
        gw3 = await resolve_squad(squad, 1, target_gw=3, picks_gw=1)
    assert gw2.source == SOURCE_OVERRIDE
    assert gw3.source == SOURCE_FPL


async def test_overrides_are_isolated_per_manager(squad):
    await save_override(squad, manager_id=1, gameweek_id=2,
                        player_ids=OWNED, bank=1, free_transfers=1)
    with patch("app.services.squad_state.fetch_manager_picks", _fpl_picks()):
        assert (await resolve_squad(squad, 1, 2, 1)).source == SOURCE_OVERRIDE
        assert (await resolve_squad(squad, 2, 2, 1)).source == SOURCE_FPL


async def test_an_override_is_discarded_once_its_gameweek_starts(squad):
    """
    The important safety property. Keeping it would shadow the real squad
    indefinitely, which is worse than being stale — it would look authoritative.
    """
    await save_override(squad, manager_id=1, gameweek_id=1,   # GW1 already started
                        player_ids=OWNED, bank=1, free_transfers=1)
    pruned = await prune_stale_overrides(squad)
    assert pruned == 1

    with patch("app.services.squad_state.fetch_manager_picks", _fpl_picks()):
        r = await resolve_squad(squad, 1, target_gw=1, picks_gw=1)
    assert r.source == SOURCE_FPL


async def test_pruning_leaves_future_overrides_alone(squad):
    await save_override(squad, manager_id=1, gameweek_id=2,   # deadline ahead
                        player_ids=OWNED, bank=1, free_transfers=1)
    assert await prune_stale_overrides(squad) == 0


async def test_clearing_returns_to_fpl(squad):
    await save_override(squad, manager_id=1, gameweek_id=2,
                        player_ids=OWNED, bank=1, free_transfers=1)
    assert await clear_override(squad, 1, 2) is True
    with patch("app.services.squad_state.fetch_manager_picks", _fpl_picks()):
        assert (await resolve_squad(squad, 1, 2, 1)).source == SOURCE_FPL


async def test_clearing_a_nonexistent_override_is_harmless(squad):
    assert await clear_override(squad, 999, 2) is False


# ── API surface ──────────────────────────────────────────────────────────────

async def test_squad_state_endpoint_reports_the_source(client, squad):
    with patch("app.services.squad_state.fetch_manager_picks", _fpl_picks()):
        r = await client.get("/api/v1/fpl/manager/1/squad-state")
    assert r.status_code == 200
    body = r.json()
    assert body["squad_source"] == "fpl_api"
    assert body["stale_warning"] is not None
    assert len(body["squad"]) == 15


async def test_recording_transfers_through_the_api(client, squad):
    with patch("app.services.squad_state.fetch_manager_picks", _fpl_picks(bank=20)):
        r = await client.post(
            "/api/v1/fpl/manager/1/squad-state/transfers",
            json={"moves": [{"out": 1, "in": 100}]},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["squad_source"] == "manager_override"
    assert body["squad_size"] == 15


async def test_api_rejects_an_unknown_player_id(client, squad):
    with patch("app.services.squad_state.fetch_manager_picks", _fpl_picks()):
        r = await client.post(
            "/api/v1/fpl/manager/1/squad-state/transfers",
            json={"moves": [{"out": 1, "in": 99999}]},
        )
    assert r.status_code == 400
    assert "Unknown player" in r.json()["detail"]


async def test_api_rejects_an_empty_move_list(client, squad):
    r = await client.post(
        "/api/v1/fpl/manager/1/squad-state/transfers", json={"moves": []}
    )
    assert r.status_code == 422


async def test_delete_endpoint_clears_the_override(client, squad):
    await save_override(squad, manager_id=1, gameweek_id=2,
                        player_ids=OWNED, bank=1, free_transfers=1)
    r = await client.delete("/api/v1/fpl/manager/1/squad-state")
    assert r.json()["cleared"] is True


# ── Alerts must follow the corrected squad ───────────────────────────────────
#
# The user's report: "you recommended I transfer Pedro for Thiago" — then got a
# price alert about Pedro, who was already sold. The alert job was reading FPL
# picks directly instead of the resolved squad.

async def test_alerts_are_hidden_for_players_no_longer_owned(client, squad):
    from app.models.news import Alert

    # An alert raised while player 1 was still owned
    squad.add(Alert(
        fpl_entry_id=1, player_id=1, severity="warning",
        title="Own1 price likely to rise soon", body="77% of the way",
    ))
    await squad.commit()

    with patch("app.services.squad_state.fetch_manager_picks", _fpl_picks()):
        before = (await client.get("/api/v1/news/alerts/1")).json()
    assert len(before) == 1
    assert before[0]["still_owned"] is True

    # Sell him
    with patch("app.services.squad_state.fetch_manager_picks", _fpl_picks(bank=20)):
        await apply_transfers(
            squad, manager_id=1, gameweek_id=2, picks_gw=1,
            moves=[{"out": 1, "in": 100}],
            player_costs={1: 50, 100: 60},
        )
        after = (await client.get("/api/v1/news/alerts/1")).json()

    assert after == [], "an alert about a sold player should not be shown"


async def test_sold_alerts_can_still_be_inspected(client, squad):
    from app.models.news import Alert
    squad.add(Alert(fpl_entry_id=1, player_id=1, severity="warning", title="x"))
    await squad.commit()

    with patch("app.services.squad_state.fetch_manager_picks", _fpl_picks(bank=20)):
        await apply_transfers(
            squad, manager_id=1, gameweek_id=2, picks_gw=1,
            moves=[{"out": 1, "in": 100}],
            player_costs={1: 50, 100: 60},
        )
        shown = (await client.get(
            "/api/v1/news/alerts/1?include_sold=true"
        )).json()

    assert len(shown) == 1
    assert shown[0]["still_owned"] is False


async def test_new_alerts_use_the_corrected_squad(squad):
    """
    The root cause. `_alerts_for_tracked` read FPL picks directly, so it warned
    about the pre-transfer squad.
    """
    from app.services.jobs import register_manager, _alerts_for_tracked

    await register_manager(squad, 1)
    with patch("app.services.squad_state.fetch_manager_picks", _fpl_picks(bank=20)):
        await apply_transfers(
            squad, manager_id=1, gameweek_id=2, picks_gw=1,
            moves=[{"out": 1, "in": 100}],
            player_costs={1: 50, 100: 60},
        )

        seen = {}

        async def capture(db, *, fpl_entry_id, squad_player_ids, **kw):
            seen["ids"] = squad_player_ids
            return {"alerts_created": 0}

        with patch("app.services.jobs.generate_alerts", capture):
            await _alerts_for_tracked(squad)

    assert 1 not in seen["ids"], "alerts were generated for a sold player"
    assert 100 in seen["ids"], "the incoming player was not considered"


# ── The squad display must follow the override too ───────────────────────────
#
# Third instance of the same root cause: the /squad endpoint and the planner
# both read FPL picks directly, so the dashboard showed the pre-transfer XI
# while the recommendation used the corrected one — visibly contradicting
# itself on the same page.

def _picks_with_slots():
    return AsyncMock(return_value={
        "picks": [
            {"element": pid, "position": i + 1,
             "is_captain": pid == 5, "is_vice_captain": pid == 6,
             "multiplier": 1}
            for i, pid in enumerate(OWNED)
        ],
        "entry_history": {"bank": 20, "value": 1000},
        "transfers": {"limit": 1},
    })


async def test_squad_endpoint_reflects_a_recorded_transfer(client, squad):
    with patch("app.services.squad_state.fetch_manager_picks", _picks_with_slots()), \
         patch("app.routers.fpl.fetch_manager_picks", _picks_with_slots()):
        await apply_transfers(
            squad, manager_id=1, gameweek_id=2, picks_gw=1,
            moves=[{"out": 1, "in": 100}],
            player_costs={1: 50, 100: 60},
        )
        body = (await client.get("/api/v1/fpl/manager/1/squad")).json()

    ids = {p["id"] for p in body["squad"]}
    assert 1 not in ids, "the sold player is still shown"
    assert 100 in ids, "the incoming player is missing"
    assert len(body["squad"]) == 15


async def test_incoming_player_is_labelled_with_who_he_replaced(client, squad):
    with patch("app.services.squad_state.fetch_manager_picks", _picks_with_slots()), \
         patch("app.routers.fpl.fetch_manager_picks", _picks_with_slots()):
        await apply_transfers(
            squad, manager_id=1, gameweek_id=2, picks_gw=1,
            moves=[{"out": 1, "in": 100}],
            player_costs={1: 50, 100: 60},
        )
        body = (await client.get("/api/v1/fpl/manager/1/squad")).json()

    incoming = next(p for p in body["squad"] if p["id"] == 100)
    assert incoming["transferred_in"] is True
    assert incoming["replaced_player_id"] == 1
    assert incoming["replaced_name"] == "Own1"


async def test_incoming_player_inherits_the_slot_not_the_armband(client, squad):
    """
    A player just brought in cannot already be captain. Copying the pick
    wholesale would hand him the armband of whoever he replaced.
    """
    with patch("app.services.squad_state.fetch_manager_picks", _picks_with_slots()), \
         patch("app.routers.fpl.fetch_manager_picks", _picks_with_slots()):
        await apply_transfers(
            squad, manager_id=1, gameweek_id=2, picks_gw=1,
            moves=[{"out": 5, "in": 100}],      # player 5 was captain
            player_costs={5: 50, 100: 60},
        )
        body = (await client.get("/api/v1/fpl/manager/1/squad")).json()

    incoming = next(p for p in body["squad"] if p["id"] == 100)
    assert incoming["slot"] == 5                 # kept the slot
    assert incoming["is_captain"] is False       # not the armband
    assert sum(1 for p in body["squad"] if p["is_captain"]) == 0


async def test_untouched_players_keep_their_armband(client, squad):
    with patch("app.services.squad_state.fetch_manager_picks", _picks_with_slots()), \
         patch("app.routers.fpl.fetch_manager_picks", _picks_with_slots()):
        await apply_transfers(
            squad, manager_id=1, gameweek_id=2, picks_gw=1,
            moves=[{"out": 1, "in": 100}],
            player_costs={1: 50, 100: 60},
        )
        body = (await client.get("/api/v1/fpl/manager/1/squad")).json()

    captain = next(p for p in body["squad"] if p["is_captain"])
    assert captain["id"] == 5


async def test_squad_without_an_override_has_no_transfer_markers(client, squad):
    with patch("app.services.squad_state.fetch_manager_picks", _picks_with_slots()), \
         patch("app.routers.fpl.fetch_manager_picks", _picks_with_slots()):
        body = (await client.get("/api/v1/fpl/manager/1/squad")).json()
    assert not any(p.get("transferred_in") for p in body["squad"])


async def test_every_player_carries_a_photo_url(client, squad):
    with patch("app.services.squad_state.fetch_manager_picks", _picks_with_slots()), \
         patch("app.routers.fpl.fetch_manager_picks", _picks_with_slots()):
        body = (await client.get("/api/v1/fpl/manager/1/squad")).json()
    # conftest builds players without a code, so the field must still exist
    assert all("photo" in p for p in body["squad"])


def test_photo_url_shape():
    from app.routers.fpl import player_photo
    assert player_photo(223094).endswith("/110x140/p223094.png")
    assert player_photo(0) is None, "a missing code must not produce a broken URL"


# ── Free-form transfers follow FPL's squad rules ─────────────────────────────

async def test_a_transfer_must_swap_like_for_like(squad):
    squad.add(make_player(200, team_id=2, position=2, now_cost=45, web_name="Defender"))
    await squad.commit()
    with patch("app.services.squad_state.fetch_manager_picks", _fpl_picks(bank=20)):
        with pytest.raises(ValueError, match="different positions"):
            await apply_transfers(
                squad, manager_id=1, gameweek_id=2, picks_gw=1,
                moves=[{"out": 1, "in": 200}], player_costs={1: 50, 200: 45},
            )


async def test_a_fourth_player_from_one_club_is_refused(squad):
    squad.add(make_player(104, team_id=2, now_cost=60, web_name="Fourth"))
    await squad.commit()
    moves = [{"out": o, "in": i} for o, i in [(1, 100), (2, 101), (3, 102), (4, 104)]]
    costs = {**{o: 50 for o in (1, 2, 3, 4)}, **{i: 60 for i in (100, 101, 102, 104)}}
    with patch("app.services.squad_state.fetch_manager_picks", _fpl_picks(bank=50)):
        with pytest.raises(ValueError, match="4 players from Team 2.*3 per club"):
            await apply_transfers(squad, manager_id=1, gameweek_id=2, picks_gw=1, moves=moves, player_costs=costs)


async def test_three_from_one_club_is_allowed(squad):
    moves = [{"out": o, "in": i} for o, i in [(1, 100), (2, 101), (3, 102)]]
    costs = {**{o: 50 for o in (1, 2, 3)}, **{i: 60 for i in (100, 101, 102)}}
    with patch("app.services.squad_state.fetch_manager_picks", _fpl_picks(bank=50)):
        r = await apply_transfers(squad, manager_id=1, gameweek_id=2, picks_gw=1, moves=moves, player_costs=costs)
    assert {100, 101, 102} <= set(r.player_ids)
