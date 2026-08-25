"""
Lineup, bench and captaincy tests.

The XI is solved by enumerating all eight legal formations, so these tests can
assert *optimality*, not just plausibility — an important property to lock down,
because a silent regression here quietly costs the user points every gameweek.
"""
import pytest
from tests.conftest import make_player, make_projection
from app.services.lineup import (
    SquadEntry, best_starting_xi, order_bench, captain_candidates,
    pick_captain_and_vice, FORMATIONS,
    POS_GKP, POS_DEF, POS_MID, POS_FWD,
)


def entry(player_id, position, xpts, *, team_id=1, p_start=1.0,
          variance=2.0, cost=55, ownership=10.0, name=None) -> SquadEntry:
    p = make_player(
        player_id, position=position, team_id=team_id, now_cost=cost,
        web_name=name or f"P{player_id}",
    )
    p.selected_by_percent = ownership
    return SquadEntry(
        player=p,
        projection=make_projection(player_id, xpts=xpts, p_start=p_start,
                                   variance=variance),
        team_short=f"T{team_id}",
    )


def valid_squad(**overrides) -> list[SquadEntry]:
    """A legal 15: 2 GKP, 5 DEF, 5 MID, 3 FWD, descending xPts per position."""
    squad = []
    pid = 1
    plan = [(POS_GKP, 2, 4.0), (POS_DEF, 5, 3.5), (POS_MID, 5, 4.5), (POS_FWD, 3, 5.0)]
    for position, count, top in plan:
        for i in range(count):
            squad.append(entry(pid, position, top - i * 0.7,
                               team_id=(pid % 5) + 1))
            pid += 1
    for player_id, xpts in overrides.items():
        idx = int(player_id.replace("p", "")) - 1
        squad[idx].projection.xpts = xpts
    return squad


# ── Formation legality ───────────────────────────────────────────────────────

def test_all_formations_have_ten_outfield():
    for d, m, f in FORMATIONS:
        assert d + m + f == 10


def test_all_formations_respect_position_limits():
    for d, m, f in FORMATIONS:
        assert 3 <= d <= 5
        assert 2 <= m <= 5
        assert 1 <= f <= 3


def test_formation_list_is_complete():
    """Derive the legal set independently and compare."""
    expected = {
        (d, m, f)
        for d in range(3, 6)
        for m in range(2, 6)
        for f in range(1, 4)
        if d + m + f == 10
    }
    assert set(FORMATIONS) == expected


# ── XI selection ─────────────────────────────────────────────────────────────

def test_xi_has_eleven_players_and_four_on_bench():
    r = best_starting_xi(valid_squad())
    assert len(r.starting) == 11
    assert len(r.bench) == 4


def test_xi_has_exactly_one_goalkeeper():
    r = best_starting_xi(valid_squad())
    assert sum(1 for e in r.starting if e.position == POS_GKP) == 1


def test_chosen_formation_is_legal():
    r = best_starting_xi(valid_squad())
    d = sum(1 for e in r.starting if e.position == POS_DEF)
    m = sum(1 for e in r.starting if e.position == POS_MID)
    f = sum(1 for e in r.starting if e.position == POS_FWD)
    assert (d, m, f) in FORMATIONS


def test_no_player_both_starting_and_benched():
    r = best_starting_xi(valid_squad())
    assert not ({e.player.id for e in r.starting} & {e.player.id for e in r.bench})


def test_selected_xi_is_the_global_optimum():
    """The reported total must equal the best across every formation."""
    r = best_starting_xi(valid_squad())
    assert r.starting_xpts == pytest.approx(max(c["xpts"] for c in r.considered))


def test_all_feasible_formations_are_evaluated():
    r = best_starting_xi(valid_squad())
    assert len(r.considered) == len(FORMATIONS)


def test_high_scoring_forwards_pull_the_formation_toward_them():
    squad = valid_squad()
    # Make all three forwards excellent
    for e in squad:
        if e.position == POS_FWD:
            e.projection.xpts = 12.0
    r = best_starting_xi(squad)
    assert sum(1 for e in r.starting if e.position == POS_FWD) == 3


def test_high_scoring_defenders_pull_the_formation_the_other_way():
    squad = valid_squad()
    for e in squad:
        if e.position == POS_DEF:
            e.projection.xpts = 12.0
    r = best_starting_xi(squad)
    assert sum(1 for e in r.starting if e.position == POS_DEF) == 5


def test_zero_projection_player_is_benched():
    squad = valid_squad()
    target = next(e for e in squad if e.position == POS_MID)
    target.projection.xpts = 0.0
    r = best_starting_xi(squad)
    assert target.player.id in {e.player.id for e in r.bench}


def test_squad_without_goalkeeper_raises():
    squad = [e for e in valid_squad() if e.position != POS_GKP]
    with pytest.raises(ValueError, match="goalkeeper"):
        best_starting_xi(squad)


def test_missing_projection_treated_as_zero_not_crash():
    squad = valid_squad()
    squad[5].projection = None
    r = best_starting_xi(squad)
    assert len(r.starting) == 11


# ── Bench ordering ───────────────────────────────────────────────────────────

def test_reserve_keeper_is_first_on_bench():
    r = best_starting_xi(valid_squad())
    assert r.bench[0].position == POS_GKP


def test_outfield_bench_ordered_by_expected_contribution():
    bench = [
        entry(101, POS_GKP, 2.0),
        entry(102, POS_DEF, 1.0, p_start=1.0),
        entry(103, POS_MID, 3.0, p_start=1.0),
        entry(104, POS_FWD, 2.0, p_start=1.0),
    ]
    ordered = order_bench(bench)
    assert ordered[0].position == POS_GKP
    outfield = [e.player.id for e in ordered[1:]]
    assert outfield == [103, 104, 102]


def test_doubtful_bench_player_ranked_below_reliable_one():
    """A sub who may not play is poor cover even with a high ceiling."""
    bench = [
        entry(101, POS_GKP, 2.0),
        entry(102, POS_MID, 4.0, p_start=0.05),   # high ceiling, unlikely to feature
        entry(103, POS_MID, 3.0, p_start=1.0),    # dependable
    ]
    bench[1].projection.p_appear = 0.05
    bench[2].projection.p_appear = 1.0
    ordered = order_bench(bench)
    assert ordered[1].player.id == 103


# ── Captaincy ────────────────────────────────────────────────────────────────

def test_balanced_mode_picks_highest_expected_points():
    xi = [entry(1, POS_FWD, 8.0), entry(2, POS_MID, 5.0), entry(3, POS_DEF, 3.0)]
    ranked = captain_candidates(xi, mode="balanced")
    assert ranked[0]["player_id"] == 1
    assert ranked[0]["expected_captain_points"] == pytest.approx(16.0)


def test_captain_points_are_doubled():
    xi = [entry(1, POS_FWD, 6.0)]
    assert captain_candidates(xi)[0]["expected_captain_points"] == pytest.approx(12.0)


def test_safe_mode_prefers_certainty_over_ceiling():
    risky = entry(1, POS_FWD, 7.0, p_start=0.5, variance=8.0)
    steady = entry(2, POS_MID, 6.5, p_start=1.0, variance=1.0)
    ranked = captain_candidates([risky, steady], mode="safe")
    assert ranked[0]["player_id"] == 2


def test_balanced_mode_would_prefer_the_risky_one():
    """Confirms the safe-mode test above is actually exercising the penalty."""
    risky = entry(1, POS_FWD, 7.0, p_start=0.5, variance=8.0)
    steady = entry(2, POS_MID, 6.5, p_start=1.0, variance=1.0)
    ranked = captain_candidates([risky, steady], mode="balanced")
    assert ranked[0]["player_id"] == 1


def test_differential_mode_prefers_lower_ownership():
    popular = entry(1, POS_FWD, 6.0, ownership=85.0)
    obscure = entry(2, POS_FWD, 5.8, ownership=2.0)
    ranked = captain_candidates([popular, obscure], mode="differential")
    assert ranked[0]["player_id"] == 2


def test_differential_mode_will_not_pick_a_bad_player():
    """Low ownership is a tiebreaker, not a licence to captain anyone."""
    good = entry(1, POS_FWD, 9.0, ownership=90.0)
    poor = entry(2, POS_DEF, 1.0, ownership=0.1)
    ranked = captain_candidates([good, poor], mode="differential")
    assert ranked[0]["player_id"] == 1


def test_vice_captain_comes_from_a_different_club():
    xi = [
        entry(1, POS_FWD, 9.0, team_id=1),
        entry(2, POS_MID, 8.5, team_id=1),   # same club as captain
        entry(3, POS_MID, 8.0, team_id=2),
    ]
    captain, vice, _ = pick_captain_and_vice(xi)
    assert captain.player.id == 1
    assert vice.player.team_id != captain.player.team_id


def test_vice_falls_back_to_same_club_rather_than_none():
    xi = [entry(1, POS_FWD, 9.0, team_id=1), entry(2, POS_MID, 8.0, team_id=1)]
    captain, vice, _ = pick_captain_and_vice(xi)
    assert vice is not None
    assert vice.player.id == 2


def test_vice_is_chosen_for_reliability():
    xi = [
        entry(1, POS_FWD, 9.0, team_id=1),
        entry(2, POS_MID, 7.0, team_id=2, p_start=0.2),   # ceiling, unreliable
        entry(3, POS_MID, 6.0, team_id=3, p_start=1.0),   # dependable
    ]
    _, vice, _ = pick_captain_and_vice(xi)
    assert vice.player.id == 3


def test_empty_xi_returns_no_captain():
    captain, vice, ranked = pick_captain_and_vice([])
    assert captain is None and vice is None and ranked == []
