"""
Transfer optimiser tests.

An optimiser that silently breaks an FPL rule is worse than not having one, so
these assert constraint satisfaction on the *returned squad*, not just that a
solution came back.
"""
import pytest
from tests.conftest import make_player
from app.services.transfers import (
    TransferCandidate, optimise_transfers, compare_transfer_counts,
    SQUAD_COMPOSITION, MAX_PER_CLUB, HIT_COST,
    POS_GKP, POS_DEF, POS_MID, POS_FWD,
)


def candidate(pid, position, xpts, cost, team_id) -> TransferCandidate:
    return TransferCandidate(
        player=make_player(pid, position=position, now_cost=cost,
                           team_id=team_id, web_name=f"P{pid}"),
        horizon_xpts=xpts,
        team_short=f"T{team_id}",
    )


def build_owned() -> list[TransferCandidate]:
    """A legal 15 costing exactly 100.0m, spread across 8 clubs."""
    owned, pid = [], 1
    plan = [(POS_GKP, 2, 45), (POS_DEF, 5, 50), (POS_MID, 5, 75), (POS_FWD, 3, 80)]
    for position, count, cost in plan:
        for i in range(count):
            owned.append(candidate(pid, position, 10.0 + i, cost, (pid % 8) + 1))
            pid += 1
    # Normalise total cost to 1000 (100.0m)
    total = sum(c.cost for c in owned)
    owned[0].player.now_cost += 1000 - total
    return owned


def build_pool(better: bool = True) -> list[TransferCandidate]:
    """Replacements, deliberately from clubs 20+ so club limits never bind."""
    pool, pid = [], 500
    plan = [(POS_GKP, 4, 45), (POS_DEF, 8, 50), (POS_MID, 8, 70), (POS_FWD, 6, 80)]
    for position, count, cost in plan:
        for i in range(count):
            xpts = (40.0 - i) if better else (1.0 + i * 0.1)
            pool.append(candidate(pid, position, xpts, cost, 20 + (pid % 6)))
            pid += 1
    return pool


def final_squad(owned, pool, plan):
    by_id = {c.player.id: c for c in owned + pool}
    out_ids = {p["player_id"] for p in plan.players_out}
    in_ids = {p["player_id"] for p in plan.players_in}
    ids = ({c.player.id for c in owned} - out_ids) | in_ids
    return [by_id[i] for i in ids]


# ── Constraint satisfaction ──────────────────────────────────────────────────

@pytest.mark.parametrize("max_transfers", [1, 2, 3])
def test_solution_satisfies_every_fpl_constraint(max_transfers):
    owned, pool = build_owned(), build_pool()
    budget = sum(c.cost for c in owned) + 0

    plan = optimise_transfers(owned, pool, bank=0, free_transfers=1,
                              max_transfers=max_transfers)
    assert plan.feasible, plan.note

    squad = final_squad(owned, pool, plan)

    assert len(squad) == 15
    for position, expected in SQUAD_COMPOSITION.items():
        assert sum(1 for c in squad if c.player.position == position) == expected

    clubs: dict[int, int] = {}
    for c in squad:
        clubs[c.player.team_id] = clubs.get(c.player.team_id, 0) + 1
    assert max(clubs.values()) <= MAX_PER_CLUB

    assert sum(c.cost for c in squad) <= budget
    assert plan.transfers_made <= max_transfers
    assert len(plan.players_out) == len(plan.players_in)
    assert plan.bank_after >= 0


def test_hit_arithmetic_is_correct():
    owned, pool = build_owned(), build_pool()
    plan = optimise_transfers(owned, pool, bank=0, free_transfers=1, max_transfers=3)
    expected_hit = max(0, plan.transfers_made - 1) * HIT_COST
    assert plan.hit == expected_hit


def test_net_gain_is_after_the_hit():
    owned, pool = build_owned(), build_pool()
    plan = optimise_transfers(owned, pool, bank=0, free_transfers=1, max_transfers=2)
    assert plan.net_gain == pytest.approx(
        plan.squad_xpts_after - plan.squad_xpts_before - plan.hit, abs=0.01
    )


def test_free_transfers_incur_no_hit():
    owned, pool = build_owned(), build_pool()
    plan = optimise_transfers(owned, pool, bank=0, free_transfers=2, max_transfers=2)
    assert plan.hit == 0


def test_budget_is_respected_when_pool_is_expensive():
    owned = build_owned()
    # Replacements far beyond affordability
    pool = [candidate(600 + i, POS_MID, 99.0, 300, 20) for i in range(5)]
    plan = optimise_transfers(owned, pool, bank=0, free_transfers=1, max_transfers=2)
    assert plan.feasible
    squad = final_squad(owned, pool, plan)
    assert sum(c.cost for c in squad) <= sum(c.cost for c in owned)


def test_bank_funds_a_more_expensive_replacement():
    owned = build_owned()
    pool = [candidate(700, POS_MID, 99.0, owned[0].cost + 20, 20)]
    poor = optimise_transfers(owned, pool, bank=0, free_transfers=1, max_transfers=1)
    rich = optimise_transfers(owned, pool, bank=500, free_transfers=1, max_transfers=1)
    assert rich.feasible
    # With money available the upgrade becomes reachable
    assert rich.squad_xpts_after >= poor.squad_xpts_after


def test_club_limit_blocks_a_fourth_from_one_team():
    owned = build_owned()
    # Six strong midfielders, all from club 30
    pool = [candidate(800 + i, POS_MID, 99.0, 55, 30) for i in range(6)]
    plan = optimise_transfers(owned, pool, bank=200, free_transfers=5, max_transfers=3)
    squad = final_squad(owned, pool, plan)
    from_30 = sum(1 for c in squad if c.player.team_id == 30)
    assert from_30 <= MAX_PER_CLUB


def test_locked_player_is_never_sold():
    owned, pool = build_owned(), build_pool()
    locked = owned[7].player.id
    plan = optimise_transfers(owned, pool, bank=0, free_transfers=1,
                              max_transfers=3, locked_player_ids={locked})
    assert locked not in {p["player_id"] for p in plan.players_out}


# ── Decision quality ─────────────────────────────────────────────────────────

def test_no_transfer_made_when_pool_is_worse():
    owned, pool = build_owned(), build_pool(better=False)
    plan = optimise_transfers(owned, pool, bank=0, free_transfers=1, max_transfers=2)
    assert plan.transfers_made == 0
    assert plan.net_gain == pytest.approx(0.0, abs=0.01)


def test_hit_not_taken_when_it_does_not_pay_for_itself():
    """
    Blueprint §12: never recommend -4 on raw xPts alone.

    The pool here is only ~1 point better than the worst owned player, so a
    second (paid) transfer cannot clear the 4-point hit.
    """
    owned = build_owned()
    worst = min(c.horizon_xpts for c in owned if c.player.position == POS_MID)
    pool = [candidate(900 + i, POS_MID, worst + 1.0, 70, 21 + i) for i in range(3)]
    plan = optimise_transfers(owned, pool, bank=200, free_transfers=1, max_transfers=3)
    assert plan.hit == 0, (
        f"took a -{plan.hit} hit for {plan.net_gain} net gain"
    )


def test_ties_are_broken_toward_fewer_transfers():
    """
    A transfer has option value: an unused one can be rolled. When two plans
    net the same, the optimiser must take the smaller one rather than churn
    the squad for nothing.
    """
    owned = build_owned()
    best_owned = max(c.horizon_xpts for c in owned)
    # Each replacement is worth +5 over the worst MIDs, so transfer 1 nets +5
    # and transfer 2 nets +4 - 4 hit = 0. Both plans total +5.
    pool = [candidate(900 + i, POS_MID, best_owned + 1.0, 70, 21 + i) for i in range(3)]
    plan = optimise_transfers(owned, pool, bank=200, free_transfers=1, max_transfers=3)
    assert plan.transfers_made == 1, (
        f"took {plan.transfers_made} transfers for {plan.net_gain} net when "
        f"1 achieves the same"
    )


def test_option_cost_does_not_block_a_clearly_good_move():
    """The tie-break penalty must be small enough to stay a tie-break."""
    owned = build_owned()
    pool = [candidate(950, POS_MID, 500.0, 70, 21)]
    plan = optimise_transfers(owned, pool, bank=200, free_transfers=1, max_transfers=1)
    assert plan.transfers_made == 1
    assert plan.net_gain > 100


def test_hit_is_taken_when_the_gain_clearly_justifies_it():
    owned = build_owned()
    pool = [candidate(910 + i, POS_MID, 200.0, 70, 21 + i) for i in range(3)]
    plan = optimise_transfers(owned, pool, bank=300, free_transfers=1, max_transfers=2)
    assert plan.transfers_made == 2
    assert plan.net_gain > 0


def test_more_transfers_never_reduce_the_optimum():
    owned, pool = build_owned(), build_pool()
    gains = [
        optimise_transfers(owned, pool, bank=0, free_transfers=1, max_transfers=n).squad_xpts_after
        for n in (1, 2, 3)
    ]
    assert gains[0] <= gains[1] <= gains[2] + 1e-6


# ── Comparison against holding ───────────────────────────────────────────────

def test_hold_is_always_offered_as_an_option():
    owned, pool = build_owned(), build_pool()
    plans = compare_transfer_counts(owned, pool, bank=0, free_transfers=1, max_transfers=2)
    assert any(p.transfers_made == 0 for p in plans)
    hold = next(p for p in plans if p.transfers_made == 0)
    assert hold.net_gain == 0.0
    assert "Hold" in hold.note


def test_comparison_covers_every_transfer_count():
    owned, pool = build_owned(), build_pool()
    plans = compare_transfer_counts(owned, pool, bank=0, free_transfers=1, max_transfers=2)
    assert len(plans) == 3          # hold, up-to-1, up-to-2


def test_empty_inputs_report_infeasible_rather_than_crash():
    plan = optimise_transfers([], [], bank=0, free_transfers=1, max_transfers=1)
    assert plan.feasible is False
    assert plan.note
