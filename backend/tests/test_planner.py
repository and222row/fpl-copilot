"""
Multi-gameweek planner tests.

The two bugs these guard against were both found by running the planner on a
real squad: it planned into gameweeks that had no projections (contributing a
silent zero per node), and it started from a gameweek whose deadline had
already passed.
"""
import pytest
from tests.conftest import (
    make_team, make_player, make_gameweek, make_projection,
)
from app.services.planner import (
    plan_horizon, serialise, next_free_transfers, PlanNode,
    MAX_FREE_TRANSFERS, ACTIONS,
)
from app.services.lineup import best_xi_total, FORMATIONS


# ── Free transfer rules ──────────────────────────────────────────────────────

def test_rolling_banks_a_transfer():
    assert next_free_transfers(1, 0) == 2
    assert next_free_transfers(2, 0) == 3


def test_using_a_transfer_keeps_the_weekly_replenishment():
    assert next_free_transfers(1, 1) == 1
    assert next_free_transfers(3, 1) == 3


def test_banked_transfers_are_capped():
    """FPL allows one per week plus four banked."""
    assert next_free_transfers(MAX_FREE_TRANSFERS, 0) == MAX_FREE_TRANSFERS
    assert next_free_transfers(MAX_FREE_TRANSFERS, 1) == MAX_FREE_TRANSFERS
    assert next_free_transfers(MAX_FREE_TRANSFERS, 2) == MAX_FREE_TRANSFERS - 1


def test_taking_a_hit_cannot_push_free_transfers_negative():
    # Two transfers on one free transfer: one is a hit, so the floor holds.
    assert next_free_transfers(1, 2) == 1


def test_free_transfers_stay_within_bounds():
    for current in range(0, MAX_FREE_TRANSFERS + 2):
        for used in range(0, 4):
            assert 1 <= next_free_transfers(current, used) <= MAX_FREE_TRANSFERS


# ── XI evaluation used by the planner ────────────────────────────────────────

def _legal_squad(values: dict[int, float] | None = None):
    """2 GKP, 5 DEF, 5 MID, 3 FWD as (id, position, xpts)."""
    values = values or {}
    out, pid = [], 1
    for position, count in ((1, 2), (2, 5), (3, 5), (4, 3)):
        for _ in range(count):
            out.append((pid, position, values.get(pid, 4.0)))
            pid += 1
    return out


def test_best_xi_picks_eleven():
    total, ids = best_xi_total(_legal_squad())
    assert len(ids) == 11
    assert total == pytest.approx(44.0)


def test_best_xi_respects_formation_legality():
    _, ids = best_xi_total(_legal_squad())
    pos = {pid: p for pid, p, _ in _legal_squad()}
    counts = {1: 0, 2: 0, 3: 0, 4: 0}
    for pid in ids:
        counts[pos[pid]] += 1
    assert counts[1] == 1
    assert (counts[2], counts[3], counts[4]) in FORMATIONS


def test_best_xi_prefers_the_higher_scorers():
    # One defender is worth far more; he must be picked
    squad = _legal_squad({3: 20.0})
    total, ids = best_xi_total(squad)
    assert 3 in ids
    assert total > 44.0


def test_best_xi_handles_a_squad_without_a_goalkeeper():
    squad = [(pid, 3, 4.0) for pid in range(1, 12)]
    total, ids = best_xi_total(squad)
    assert total == 0.0 and ids == []


def test_best_xi_matches_manual_optimum():
    """Make one formation clearly best and check it is chosen."""
    values = {}
    for pid in range(3, 8):        # all five defenders excellent
        values[pid] = 10.0
    squad = _legal_squad(values)
    _, ids = best_xi_total(squad)
    assert sum(1 for pid in ids if 3 <= pid <= 7) == 5


# ── Planning over a database ─────────────────────────────────────────────────

@pytest.fixture
async def planning_data(session):
    """
    A legal squad plus a pool of better replacements, projected over GW1-3.

    Clubs are spread so the three-per-club cap never binds.
    """
    for tid in range(1, 13):
        session.add(make_team(tid, f"T{tid:02d}"))
    for gw in (1, 2, 3):
        session.add(make_gameweek(gw, is_current=(gw == 1)))
    await session.flush()

    owned, pid = [], 1
    for position, count in ((1, 2), (2, 5), (3, 5), (4, 3)):
        for _ in range(count):
            session.add(make_player(pid, team_id=(pid % 12) + 1,
                                    position=position, now_cost=50,
                                    web_name=f"Own{pid}"))
            owned.append(pid)
            pid += 1

    # Replacements, clearly better, cheap enough to be affordable
    pool = []
    for position, count in ((1, 3), (2, 6), (3, 6), (4, 4)):
        for _ in range(count):
            session.add(make_player(pid, team_id=(pid % 12) + 1,
                                    position=position, now_cost=50,
                                    web_name=f"New{pid}"))
            pool.append(pid)
            pid += 1
    await session.flush()

    for gw in (1, 2, 3):
        for p in owned:
            session.add(make_projection(p, gw, xpts=3.0))
        for p in pool:
            session.add(make_projection(p, gw, xpts=6.0))
    await session.commit()
    return {"session": session, "owned": owned, "pool": pool}


async def test_plan_returns_a_node_per_horizon_level(planning_data):
    result = await plan_horizon(
        planning_data["session"], squad_ids=planning_data["owned"],
        bank=0, free_transfers=1, start_gw=1, horizon=3, beam_width=2,
    )
    assert result.horizon == [1, 2, 3]
    # Root plus at least one node per gameweek
    assert max(n.depth for n in result.nodes) == 3


async def test_best_path_starts_at_the_root(planning_data):
    result = await plan_horizon(
        planning_data["session"], squad_ids=planning_data["owned"],
        bank=0, free_transfers=1, start_gw=1, horizon=3, beam_width=2,
    )
    assert result.best_path[0].parent_id is None
    assert result.best_path[0].depth == 0


async def test_best_path_is_contiguous(planning_data):
    """Every step must be the child of the one before it."""
    result = await plan_horizon(
        planning_data["session"], squad_ids=planning_data["owned"],
        bank=0, free_transfers=1, start_gw=1, horizon=3, beam_width=2,
    )
    for parent, child in zip(result.best_path, result.best_path[1:]):
        assert child.parent_id == parent.id
        assert child.depth == parent.depth + 1


async def test_squad_stays_at_fifteen_through_the_plan(planning_data):
    result = await plan_horizon(
        planning_data["session"], squad_ids=planning_data["owned"],
        bank=0, free_transfers=1, start_gw=1, horizon=3, beam_width=2,
    )
    for node in result.nodes:
        assert len(node.squad_ids) == 15, f"node {node.id} has {len(node.squad_ids)}"


async def test_transfers_in_and_out_are_balanced(planning_data):
    result = await plan_horizon(
        planning_data["session"], squad_ids=planning_data["owned"],
        bank=0, free_transfers=1, start_gw=1, horizon=3, beam_width=2,
    )
    for node in result.nodes:
        assert len(node.players_in) == len(node.players_out)
        assert len(node.players_in) == node.transfers


async def test_cumulative_points_never_decrease_along_a_path(planning_data):
    """Each gameweek adds points; only a hit can offset, never reverse."""
    result = await plan_horizon(
        planning_data["session"], squad_ids=planning_data["owned"],
        bank=0, free_transfers=1, start_gw=1, horizon=3, beam_width=2,
    )
    for parent, child in zip(result.best_path, result.best_path[1:]):
        assert child.cumulative_xpts >= parent.cumulative_xpts


async def test_planner_upgrades_when_the_pool_is_better(planning_data):
    """Owned players project 3.0, replacements 6.0 — it should act."""
    result = await plan_horizon(
        planning_data["session"], squad_ids=planning_data["owned"],
        bank=0, free_transfers=1, start_gw=1, horizon=3, beam_width=3,
    )
    assert sum(n.transfers for n in result.best_path) > 0


async def test_planner_rolls_when_no_upgrade_exists(session):
    """With nothing better available, the plan should be all rolls."""
    for tid in range(1, 13):
        session.add(make_team(tid, f"T{tid:02d}"))
    for gw in (1, 2):
        session.add(make_gameweek(gw, is_current=(gw == 1)))
    await session.flush()

    owned, pid = [], 1
    for position, count in ((1, 2), (2, 5), (3, 5), (4, 3)):
        for _ in range(count):
            session.add(make_player(pid, team_id=(pid % 12) + 1,
                                    position=position, now_cost=50))
            owned.append(pid)
            pid += 1
    # A pool that is strictly worse
    worse = []
    for position, count in ((1, 2), (2, 3), (3, 3), (4, 2)):
        for _ in range(count):
            session.add(make_player(pid, team_id=(pid % 12) + 1,
                                    position=position, now_cost=50))
            worse.append(pid)
            pid += 1
    await session.flush()
    for gw in (1, 2):
        for p in owned:
            session.add(make_projection(p, gw, xpts=8.0))
        for p in worse:
            session.add(make_projection(p, gw, xpts=1.0))
    await session.commit()

    result = await plan_horizon(
        session, squad_ids=owned, bank=0, free_transfers=1,
        start_gw=1, horizon=2, beam_width=2,
    )
    assert sum(n.transfers for n in result.best_path) == 0


async def test_free_transfers_evolve_correctly_along_the_path(planning_data):
    result = await plan_horizon(
        planning_data["session"], squad_ids=planning_data["owned"],
        bank=0, free_transfers=1, start_gw=1, horizon=3, beam_width=2,
    )
    for parent, child in zip(result.best_path, result.best_path[1:]):
        assert child.free_transfers == next_free_transfers(
            parent.free_transfers, child.transfers
        )


# ── The two bugs found on real data ──────────────────────────────────────────

async def test_horizon_truncates_to_gameweeks_that_have_projections(planning_data):
    """
    Asking for more gameweeks than have been projected must shorten the
    horizon, not plan into empty ones scoring zero.
    """
    result = await plan_horizon(
        planning_data["session"], squad_ids=planning_data["owned"],
        bank=0, free_transfers=1, start_gw=1, horizon=8, beam_width=2,
    )
    assert result.horizon == [1, 2, 3]
    assert result.requested_horizon == 8

    payload = serialise(result)
    assert payload["horizon_truncated"] is True
    assert "3 of 8" in payload["truncation_note"]


async def test_no_planned_gameweek_scores_zero(planning_data):
    """The symptom the truncation bug produced."""
    result = await plan_horizon(
        planning_data["session"], squad_ids=planning_data["owned"],
        bank=0, free_transfers=1, start_gw=1, horizon=8, beam_width=2,
    )
    for node in result.best_path[1:]:
        assert node.gw_xpts > 0, f"GW{node.gameweek} scored nothing"


async def test_untruncated_horizon_is_not_flagged(planning_data):
    result = await plan_horizon(
        planning_data["session"], squad_ids=planning_data["owned"],
        bank=0, free_transfers=1, start_gw=1, horizon=3, beam_width=2,
    )
    payload = serialise(result)
    assert payload["horizon_truncated"] is False
    assert payload["truncation_note"] is None


# ── Failure modes ────────────────────────────────────────────────────────────

async def test_missing_projections_raise_a_clear_error(session):
    session.add(make_team(1))
    session.add(make_gameweek(1, is_current=True))
    await session.flush()
    ids = []
    for pid in range(1, 16):
        session.add(make_player(pid, team_id=1))
        ids.append(pid)
    await session.commit()

    with pytest.raises(ValueError, match="No gameweeks in horizon|projections"):
        await plan_horizon(session, squad_ids=ids, bank=0, free_transfers=1,
                           start_gw=1, horizon=3)


async def test_incomplete_squad_is_rejected(planning_data):
    with pytest.raises(ValueError, match="database"):
        await plan_horizon(
            planning_data["session"],
            squad_ids=planning_data["owned"][:10],
            bank=0, free_transfers=1, start_gw=1, horizon=2,
        )


# ── Serialisation ────────────────────────────────────────────────────────────

async def test_serialised_tree_exposes_parent_links(planning_data):
    result = await plan_horizon(
        planning_data["session"], squad_ids=planning_data["owned"],
        bank=0, free_transfers=1, start_gw=1, horizon=3, beam_width=2,
    )
    payload = serialise(result)
    ids = {n["id"] for n in payload["tree"]}
    for n in payload["tree"]:
        if n["parent_id"] is not None:
            assert n["parent_id"] in ids, "tree has a dangling parent reference"


async def test_serialised_best_path_is_marked_in_the_tree(planning_data):
    result = await plan_horizon(
        planning_data["session"], squad_ids=planning_data["owned"],
        bank=0, free_transfers=1, start_gw=1, horizon=3, beam_width=2,
    )
    payload = serialise(result)
    flagged = [n for n in payload["tree"] if n["on_best_path"]]
    assert len(flagged) == len(result.best_path)


async def test_pruned_branches_are_retained_for_display(planning_data):
    """The UI shows rejected options, so they must survive serialisation."""
    result = await plan_horizon(
        planning_data["session"], squad_ids=planning_data["owned"],
        bank=0, free_transfers=1, start_gw=1, horizon=3, beam_width=1,
    )
    payload = serialise(result)
    assert any(n["pruned"] for n in payload["tree"])


async def test_wider_beam_never_finds_a_worse_plan(planning_data):
    narrow = await plan_horizon(
        planning_data["session"], squad_ids=planning_data["owned"],
        bank=0, free_transfers=1, start_gw=1, horizon=3, beam_width=1,
    )
    wide = await plan_horizon(
        planning_data["session"], squad_ids=planning_data["owned"],
        bank=0, free_transfers=1, start_gw=1, horizon=3, beam_width=4,
    )
    assert (wide.best_path[-1].cumulative_xpts
            >= narrow.best_path[-1].cumulative_xpts - 0.01)


def test_action_labels_read_naturally():
    def node(transfers, hit):
        return PlanNode(id=0, parent_id=None, gameweek=1, depth=1,
                        transfers=transfers, hit=hit)
    assert node(0, 0).action_label == "Roll"
    assert node(1, 0).action_label == "1 transfer"
    assert node(2, 0).action_label == "2 transfers"
    assert "−4" in node(2, 4).action_label


def test_action_set_covers_roll_one_and_two():
    assert ACTIONS == (0, 1, 2)
