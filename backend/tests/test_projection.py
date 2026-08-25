"""
Projection model tests.

Guards two regressions found during Phase 3:
  1. FPL's per-90 rates are computed from whatever minutes exist, so a
     defender scoring once in 77 minutes reported xG/90 of 1.7 and outranked
     Haaland. Price-scaled priors plus a cap fixed it.
  2. `matches_played` derived from finished *gameweeks* was always 0, because
     FPL only sets `finished` after verifying data.
"""
import math
import pytest
from tests.conftest import make_player, make_fixture, make_team
from app.services.projection import (
    estimate_minutes, shrink, price_scaled_prior, poisson_zero,
    poisson_at_least, expected_conceded_penalty, project_player_gameweek,
    Rules, availability_multiplier,
    SHRINK_MINUTES, MAX_RATE_VS_PRIOR, BASELINE,
    POS_GKP, POS_DEF, POS_MID, POS_FWD,
)
from app.services.team_strength import (
    fdr_from_expected_goals, expected_goals_for_fixture,
)
from app.models.projections import TeamStrength


# ── Probability helpers ──────────────────────────────────────────────────────

def test_poisson_zero_matches_closed_form():
    assert poisson_zero(0.0) == pytest.approx(1.0)
    assert poisson_zero(1.0) == pytest.approx(math.exp(-1.0))
    assert poisson_zero(2.5) == pytest.approx(math.exp(-2.5))


def test_poisson_zero_is_a_probability():
    for mean in (0, 0.5, 1, 3, 10):
        assert 0.0 <= poisson_zero(mean) <= 1.0


def test_clean_sheet_probability_falls_as_opponent_improves():
    assert poisson_zero(0.5) > poisson_zero(1.5) > poisson_zero(3.0)


def test_poisson_at_least_zero_is_certain():
    assert poisson_at_least(3.0, 0) == 1.0


def test_poisson_at_least_decreases_with_threshold():
    p1 = poisson_at_least(5.0, 1)
    p5 = poisson_at_least(5.0, 5)
    p12 = poisson_at_least(5.0, 12)
    assert p1 > p5 > p12
    assert all(0.0 <= p <= 1.0 for p in (p1, p5, p12))


def test_poisson_at_least_rises_with_mean():
    assert poisson_at_least(12.0, 10) > poisson_at_least(4.0, 10)


def test_defensive_contribution_threshold_is_hard_to_hit_for_low_rate():
    # A forward averaging 2.5 CBIRT/90 should almost never reach 12.
    assert poisson_at_least(2.5, 12) < 0.01


def test_expected_conceded_penalty_counts_pairs():
    # With xGC 0, no penalty. Rises monotonically with goals conceded.
    assert expected_conceded_penalty(0.0, 2) == pytest.approx(0.0, abs=1e-9)
    a = expected_conceded_penalty(1.0, 2)
    b = expected_conceded_penalty(3.0, 2)
    assert 0 < a < b


# ── Shrinkage and priors ─────────────────────────────────────────────────────

def test_shrink_returns_prior_with_no_minutes():
    assert shrink(observed_per_90=5.0, prior=0.2, minutes=0) == pytest.approx(0.2)


def test_shrink_moves_toward_observed_as_minutes_accumulate():
    low = shrink(1.0, 0.2, minutes=90)
    high = shrink(1.0, 0.2, minutes=3000)
    assert 0.2 < low < high


def test_shrink_is_halfway_at_shrink_minutes_before_cap():
    # With prior high enough that the cap does not bind
    result = shrink(observed_per_90=0.30, prior=0.25, minutes=int(SHRINK_MINUTES))
    assert result == pytest.approx((0.30 + 0.25) / 2, abs=0.01)


def test_shrink_caps_at_multiple_of_prior():
    """The De Cuyper regression: one goal in 77 minutes reported xG/90 of 1.7."""
    result = shrink(observed_per_90=1.72, prior=0.06, minutes=77)
    assert result <= 0.06 * MAX_RATE_VS_PRIOR + 1e-9


def test_price_scaled_prior_is_linear_in_price_ratio():
    base = BASELINE[POS_FWD]["xg"]
    at_median = price_scaled_prior(base, cost=55, median_cost=55)
    premium = price_scaled_prior(base, cost=155, median_cost=55)
    assert at_median == pytest.approx(base)
    assert premium == pytest.approx(base * (155 / 55))


def test_premium_forward_prior_is_realistic():
    """A £15.5m forward should imply roughly 0.9-1.1 xG/90, not 3.0."""
    prior = price_scaled_prior(BASELINE[POS_FWD]["xg"], cost=155, median_cost=55)
    assert 0.8 < prior < 1.2


def test_cheap_defender_prior_stays_low():
    prior = price_scaled_prior(BASELINE[POS_DEF]["xg"], cost=45, median_cost=45)
    assert prior < 0.10


def test_price_prior_degrades_safely_on_zero_inputs():
    assert price_scaled_prior(0.2, cost=0, median_cost=55) == 0.2
    assert price_scaled_prior(0.2, cost=55, median_cost=0) == 0.2


# ── Expected minutes ─────────────────────────────────────────────────────────

def test_unavailable_player_gets_no_minutes():
    p = make_player(status="i")
    m = estimate_minutes(p, matches_played=5)
    assert m.expected_minutes == 0.0
    assert m.p_start == 0.0
    assert m.p_appear == 0.0


def test_no_matches_played_uses_neutral_assumption():
    """
    The Phase 3 bug: with matches_played=0 the old code divided by a
    meaningless denominator and gave every player p_start = 1.0.
    """
    nailed = make_player(player_id=1, minutes=900, starts=10)
    fringe = make_player(player_id=2, minutes=30, starts=0)
    a = estimate_minutes(nailed, matches_played=0)
    b = estimate_minutes(fringe, matches_played=0)
    assert a.p_start == b.p_start          # no data means no differentiation
    assert 0.0 < a.p_start < 1.0           # and not a false certainty


def test_regular_starter_gets_high_start_probability():
    p = make_player(minutes=10 * 90, starts=10)
    m = estimate_minutes(p, matches_played=10)
    assert m.p_start > 0.85
    assert m.expected_minutes > 70


def test_bench_player_gets_low_start_probability():
    p = make_player(minutes=45, starts=0)
    m = estimate_minutes(p, matches_played=10)
    assert m.p_start < 0.15
    assert m.expected_minutes < 20


def test_doubtful_player_minutes_scale_by_availability():
    healthy = make_player(minutes=900, starts=10)
    doubtful = make_player(minutes=900, starts=10,
                           news="Knock - 50% chance of playing", status="d")
    a = estimate_minutes(healthy, matches_played=10)
    b = estimate_minutes(doubtful, matches_played=10)
    assert b.expected_minutes == pytest.approx(a.expected_minutes * 0.5, rel=0.02)


@pytest.mark.parametrize("chance", [0, 25, 50, 75, 100])
def test_appearance_probability_never_exceeds_availability(chance):
    """
    Availability is P(fit to feature), so no split of start/sub can push the
    chance of appearing above it. Deriving the substitute term from the already
    availability-scaled start probability broke this invariant.
    """
    p = make_player(minutes=900, starts=10, status="d",
                    news=f"Knock - {chance}% chance of playing")
    m = estimate_minutes(p, matches_played=10)
    assert m.p_appear <= m.availability + 1e-9, (
        f"p_appear {m.p_appear} > availability {m.availability}"
    )


def test_probabilities_are_ordered_and_bounded():
    for minutes, starts in ((900, 10), (450, 5), (60, 0), (0, 0)):
        m = estimate_minutes(make_player(minutes=minutes, starts=starts), matches_played=10)
        assert 0.0 <= m.p_60 <= m.p_appear <= 1.0
        assert 0.0 <= m.p_start <= 1.0
        assert 0.0 <= m.expected_minutes <= 90.0


def test_availability_multiplier_reads_news_over_field():
    p = make_player(status="d", chance=0,
                    news="Lack of match fitness - 75% chance of playing")
    assert availability_multiplier(p) == 0.75


# ── Custom FDR ───────────────────────────────────────────────────────────────

def test_fdr_scale_is_ordered_and_clamped():
    easy = fdr_from_expected_goals(0.4)
    mid = fdr_from_expected_goals(1.4)
    hard = fdr_from_expected_goals(3.0)
    assert easy < mid < hard
    assert 1.0 <= easy and hard <= 5.0


def test_expected_goals_falls_back_to_baseline_for_unknown_team():
    assert expected_goals_for_fixture({}, 1, 2, True) > 0


def test_expected_goals_beats_baseline_against_weak_defence():
    strong_attack = TeamStrength(team_id=1, model_version="t", attack_home=2.0,
                                 attack_away=1.6, defence_home=1.0, defence_away=1.2)
    leaky = TeamStrength(team_id=2, model_version="t", attack_home=1.0,
                         attack_away=0.8, defence_home=2.0, defence_away=2.2)
    solid = TeamStrength(team_id=3, model_version="t", attack_home=1.0,
                         attack_away=0.8, defence_home=0.7, defence_away=0.8)
    vs_leaky = expected_goals_for_fixture({1: strong_attack, 2: leaky}, 1, 2, True)
    vs_solid = expected_goals_for_fixture({1: strong_attack, 3: solid}, 1, 3, True)
    assert vs_leaky > vs_solid


def test_expected_goals_stays_in_sane_range():
    absurd = TeamStrength(team_id=1, model_version="t", attack_home=99.0,
                          attack_away=99.0, defence_home=99.0, defence_away=99.0)
    val = expected_goals_for_fixture({1: absurd, 2: absurd}, 1, 2, True)
    assert 0.1 <= val <= 5.0


# ── Full projection ──────────────────────────────────────────────────────────

def _strength():
    ts = lambda i: TeamStrength(  # noqa: E731
        team_id=i, model_version="t", attack_home=1.5, attack_away=1.2,
        defence_home=1.2, defence_away=1.5,
    )
    return {1: ts(1), 2: ts(2)}


def test_blank_gameweek_projects_zero():
    r = project_player_gameweek(make_player(), [], _strength(), Rules(), 5)
    assert r.xpts == 0.0
    assert r.fixture_count == 0


def test_injured_player_projects_zero_even_with_a_fixture():
    r = project_player_gameweek(
        make_player(status="i"), [(make_fixture(), True)], _strength(), Rules(), 5
    )
    assert r.xpts == 0.0


def test_components_sum_to_total():
    r = project_player_gameweek(
        make_player(), [(make_fixture(), True)], _strength(), Rules(), 5
    )
    assert sum(r.components.values()) == pytest.approx(r.xpts, abs=0.01)


def test_double_gameweek_beats_single():
    single = project_player_gameweek(
        make_player(), [(make_fixture(1), True)], _strength(), Rules(), 5
    )
    double = project_player_gameweek(
        make_player(),
        [(make_fixture(1), True), (make_fixture(2, team_h=2, team_a=1), False)],
        _strength(), Rules(), 5,
    )
    assert double.xpts > single.xpts
    assert double.fixture_count == 2


def test_goalkeeper_earns_clean_sheet_and_saves_not_attacking_returns():
    gk = make_player(position=POS_GKP, now_cost=50, saves90=3.0, xg90=0.0, xa90=0.0)
    r = project_player_gameweek(gk, [(make_fixture(), True)], _strength(), Rules(), 5)
    assert r.components["clean_sheet"] > 0
    assert r.components["saves"] > 0
    assert r.components["goals"] == pytest.approx(0.0, abs=0.05)


def test_forward_earns_no_clean_sheet_points():
    fwd = make_player(position=POS_FWD)
    r = project_player_gameweek(fwd, [(make_fixture(), True)], _strength(), Rules(), 5)
    assert r.components["clean_sheet"] == 0.0


def test_defender_earns_clean_sheet_points():
    dfn = make_player(position=POS_DEF, now_cost=45)
    r = project_player_gameweek(dfn, [(make_fixture(), True)], _strength(), Rules(), 5)
    assert r.components["clean_sheet"] > 0


def test_goalkeeper_goal_worth_more_than_forward_goal():
    """2026/27 rules: GK goals are worth 10, forwards 4."""
    rules = Rules()
    assert rules.goals["GKP"] == 10
    assert rules.goals["FWD"] == 4


def test_penalty_taker_out_projects_identical_non_taker():
    plain = make_player(player_id=1, position=POS_FWD, penalties_order=None)
    taker = make_player(player_id=2, position=POS_FWD, penalties_order=1)
    a = project_player_gameweek(plain, [(make_fixture(), True)], _strength(), Rules(), 5)
    b = project_player_gameweek(taker, [(make_fixture(), True)], _strength(), Rules(), 5)
    assert b.components["goals"] > a.components["goals"]


def test_cards_are_a_penalty():
    r = project_player_gameweek(
        make_player(yellow=5), [(make_fixture(), True)], _strength(), Rules(), 5
    )
    assert r.components["cards"] < 0


def test_premium_forward_outprojects_cheap_defender_on_equal_data():
    """
    The core Phase 3 regression, as a test: identical observed rates, price is
    the only differentiator, and the expensive attacker must win.
    """
    medians = {POS_GKP: 45, POS_DEF: 45, POS_MID: 55, POS_FWD: 55}
    haaland = make_player(player_id=1, position=POS_FWD, now_cost=155,
                          xg90=0.9, xa90=0.2, minutes=900, starts=10)
    fullback = make_player(player_id=2, position=POS_DEF, now_cost=45,
                           xg90=1.72, xa90=0.25, minutes=77, starts=1)
    a = project_player_gameweek(haaland, [(make_fixture(), True)],
                                _strength(), Rules(), 1, median_cost=medians)
    b = project_player_gameweek(fullback, [(make_fixture(), True)],
                                _strength(), Rules(), 1, median_cost=medians)
    assert a.xpts > b.xpts, f"premium {a.xpts} should beat outlier {b.xpts}"


def test_variance_is_non_negative():
    r = project_player_gameweek(
        make_player(), [(make_fixture(), True)], _strength(), Rules(), 5
    )
    assert r.variance >= 0
