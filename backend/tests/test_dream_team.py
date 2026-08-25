"""
Dream-team solver tests.

The property that matters most is the two-tier objective. A solver that simply
maximises the sum of all 15 spends real money on a bench that never plays, so
these assert the shape a competent manager would actually build: a strong XI
and a deliberately cheap bench — while still satisfying every FPL rule.
"""
import pytest
from tests.conftest import make_team, make_player, make_gameweek, make_projection
from app.services.dream_team import (
    build_dream_team, build_reasons, Candidate, _formation, _order_bench,
    SQUAD_COMPOSITION, XI_LIMITS, MAX_PER_CLUB, BENCH_WEIGHT, DEFAULT_BUDGET,
    POS_GKP, POS_DEF, POS_MID, POS_FWD,
)
from app.services.lineup import FORMATIONS


@pytest.fixture
async def pool(session):
    """
    A pool wide enough to build from: 20 clubs, and enough players per position
    that the club cap and budget actually bind.
    """
    for tid in range(1, 21):
        session.add(make_team(tid, f"T{tid:02d}"))
    session.add(make_gameweek(2, is_next=True))
    await session.flush()

    pid = 1
    # Price and projection both rise together, so the solver has a real
    # value trade-off rather than a single dominant pick.
    for position, count in ((POS_GKP, 12), (POS_DEF, 30), (POS_MID, 30), (POS_FWD, 20)):
        for i in range(count):
            cost = 40 + (i % 12) * 10          # £4.0m .. £15.0m
            session.add(make_player(
                pid, team_id=(pid % 20) + 1, position=position,
                now_cost=cost, web_name=f"P{pid}",
            ))
            pid += 1
    await session.flush()

    players = list(range(1, pid))
    for p in players:
        # Expected points scale with price, plus a little spread
        cost = 40 + ((p - 1) % 12) * 10
        session.add(make_projection(p, 2, xpts=round(cost / 20 + (p % 5) * 0.1, 2)))
    await session.commit()
    return session


# ── FPL rules ────────────────────────────────────────────────────────────────

async def test_squad_has_the_right_composition(pool):
    r = await build_dream_team(pool, horizon=1, time_limit=3.0)
    squad = r["starting"] + r["bench"]
    assert len(squad) == 15
    counts = {"GKP": 0, "DEF": 0, "MID": 0, "FWD": 0}
    for p in squad:
        counts[p["position"]] += 1
    assert counts == {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}


async def test_xi_is_eleven_in_a_legal_formation(pool):
    r = await build_dream_team(pool, horizon=1, time_limit=3.0)
    assert len(r["starting"]) == 11
    d = sum(1 for p in r["starting"] if p["position"] == "DEF")
    m = sum(1 for p in r["starting"] if p["position"] == "MID")
    f = sum(1 for p in r["starting"] if p["position"] == "FWD")
    assert sum(1 for p in r["starting"] if p["position"] == "GKP") == 1
    assert (d, m, f) in FORMATIONS
    assert r["formation"] == f"{d}-{m}-{f}"


async def test_budget_is_respected(pool):
    r = await build_dream_team(pool, budget=1000, horizon=1, time_limit=3.0)
    assert r["squad_cost"] <= 100.0
    assert r["money_left"] >= 0
    assert r["squad_cost"] + r["money_left"] == pytest.approx(100.0, abs=0.01)


@pytest.mark.parametrize("budget_m", [80.0, 90.0, 100.0, 110.0])
async def test_any_reasonable_budget_produces_a_legal_squad(pool, budget_m):
    r = await build_dream_team(pool, budget=int(budget_m * 10), horizon=1, time_limit=3.0)
    assert len(r["starting"]) + len(r["bench"]) == 15
    assert r["squad_cost"] <= budget_m


async def test_club_limit_is_respected(pool):
    r = await build_dream_team(pool, horizon=1, time_limit=3.0)
    counts: dict[str, int] = {}
    for p in r["starting"] + r["bench"]:
        counts[p["team"]] = counts.get(p["team"], 0) + 1
    assert max(counts.values()) <= MAX_PER_CLUB


async def test_exactly_one_captain_and_one_vice(pool):
    r = await build_dream_team(pool, horizon=1, time_limit=3.0)
    squad = r["starting"] + r["bench"]
    assert sum(1 for p in squad if p["is_captain"]) == 1
    assert sum(1 for p in squad if p["is_vice_captain"]) == 1


async def test_captain_is_in_the_xi(pool):
    r = await build_dream_team(pool, horizon=1, time_limit=3.0)
    captain = next(p for p in r["starting"] + r["bench"] if p["is_captain"])
    assert captain["is_starting"] is True


async def test_captain_and_vice_are_different_players(pool):
    r = await build_dream_team(pool, horizon=1, time_limit=3.0)
    squad = r["starting"] + r["bench"]
    captain = next(p for p in squad if p["is_captain"])
    vice = next(p for p in squad if p["is_vice_captain"])
    assert captain["player_id"] != vice["player_id"]


async def test_no_player_appears_twice(pool):
    r = await build_dream_team(pool, horizon=1, time_limit=3.0)
    ids = [p["player_id"] for p in r["starting"] + r["bench"]]
    assert len(ids) == len(set(ids))


# ── The two-tier objective ───────────────────────────────────────────────────

async def test_bench_is_cheaper_than_the_xi(pool):
    """
    The point of weighting the bench at a discount. Without it the solver
    spends real money on players who never score.
    """
    r = await build_dream_team(pool, horizon=1, time_limit=3.0)
    xi_avg = sum(p["price"] for p in r["starting"]) / len(r["starting"])
    bench_avg = sum(p["price"] for p in r["bench"]) / len(r["bench"])
    assert bench_avg < xi_avg, f"bench £{bench_avg:.1f}m vs XI £{xi_avg:.1f}m"


async def test_bench_weight_is_a_discount_not_a_dismissal(pool):
    """Zero would risk picking players projected at nothing, breaking autosubs."""
    assert 0 < BENCH_WEIGHT < 0.5


async def test_the_xi_outprojects_the_bench(pool):
    r = await build_dream_team(pool, horizon=1, time_limit=3.0)
    worst_starter = min(p["xpts"] for p in r["starting"])
    best_bench = max(p["xpts"] for p in r["bench"])
    # A bench player may edge a starter on raw points if position limits force
    # it, but the totals must not be inverted.
    assert sum(p["xpts"] for p in r["starting"]) > sum(p["xpts"] for p in r["bench"])
    assert worst_starter >= 0 and best_bench >= 0


async def test_reserve_keeper_is_first_on_the_bench(pool):
    r = await build_dream_team(pool, horizon=1, time_limit=3.0)
    assert r["bench"][0]["position"] == "GKP"
    assert r["bench"][0]["bench_order"] == 0


# ── Optimality ───────────────────────────────────────────────────────────────

async def test_a_solution_is_always_found_and_labelled_honestly(pool):
    """
    This pool is a deliberately hard instance: projections scale linearly with
    price, so hundreds of squads score almost identically and proving
    optimality is slow. The result must still be usable — and must not claim
    optimality it did not prove.
    """
    r = await build_dream_team(pool, horizon=1, time_limit=3.0)
    assert r["solver_status"] in ("OPTIMAL", "FEASIBLE")
    assert r["proven_optimal"] is (r["solver_status"] == "OPTIMAL")
    if not r["proven_optimal"]:
        assert r["optimality_note"], "an unproven result must say so"
    else:
        assert r["optimality_note"] is None


async def test_a_bigger_budget_never_produces_a_worse_squad(pool):
    lean = await build_dream_team(pool, budget=850, horizon=1, time_limit=3.0)
    rich = await build_dream_team(pool, budget=1050, horizon=1, time_limit=3.0)
    assert rich["projected_next_gw"] >= lean["projected_next_gw"] - 0.01


async def test_repeated_calls_agree_on_the_objective(pool):
    """
    The same request must produce an equally good squad. Exact player equality
    is only guaranteed when the solver proves optimality — with several workers
    under a time limit it may reach a different squad of the same value — so the
    stable property is the projected total, not the specific names.
    """
    a = await build_dream_team(pool, horizon=1, time_limit=3.0)
    b = await build_dream_team(pool, horizon=1, time_limit=3.0)
    assert a["projected_next_gw"] == pytest.approx(b["projected_next_gw"], abs=0.5)

    if a["proven_optimal"] and b["proven_optimal"]:
        # A proven optimum has a unique objective value, so the totals must match
        assert a["projected_next_gw"] == pytest.approx(b["projected_next_gw"], abs=0.01)


async def test_no_squad_is_ever_an_input(pool):
    """
    The signature takes no manager or squad argument at all — the guarantee is
    structural, not something two runs could demonstrate.
    """
    import inspect
    params = set(inspect.signature(build_dream_team).parameters)
    assert not {"manager_id", "squad_ids", "owned"} & params


# ── Constraints the caller supplies ──────────────────────────────────────────

async def test_must_include_forces_a_player_in(pool):
    r = await build_dream_team(pool, horizon=1, time_limit=3.0)
    picked = {p["player_id"] for p in r["starting"] + r["bench"]}
    outsider = next(pid for pid in range(1, 90) if pid not in picked)

    forced = await build_dream_team(pool, horizon=1, must_include=[outsider], time_limit=3.0)
    assert outsider in {p["player_id"] for p in forced["starting"] + forced["bench"]}


async def test_forcing_a_player_cannot_improve_the_total(pool):
    """Adding a constraint can only ever cost points."""
    free = await build_dream_team(pool, horizon=1, time_limit=3.0)
    picked = {p["player_id"] for p in free["starting"] + free["bench"]}
    outsider = next(pid for pid in range(1, 90) if pid not in picked)
    forced = await build_dream_team(pool, horizon=1, must_include=[outsider], time_limit=3.0)
    assert forced["projected_next_gw"] <= free["projected_next_gw"] + 0.01


async def test_exclude_keeps_a_player_out(pool):
    r = await build_dream_team(pool, horizon=1, time_limit=3.0)
    unwanted = r["starting"][0]["player_id"]
    without = await build_dream_team(pool, horizon=1, exclude=[unwanted], time_limit=3.0)
    assert unwanted not in {
        p["player_id"] for p in without["starting"] + without["bench"]
    }


async def test_forcing_an_unknown_player_is_rejected(pool):
    with pytest.raises(ValueError, match="not in the candidate pool"):
        await build_dream_team(pool, horizon=1, must_include=[999999], time_limit=3.0)


# ── Availability ─────────────────────────────────────────────────────────────

async def test_unavailable_players_are_never_picked(pool):
    from sqlalchemy import select
    from app.models.fpl import Player

    # Injure the highest-projected player
    r = await build_dream_team(pool, horizon=1, time_limit=3.0)
    star = max(r["starting"], key=lambda p: p["xpts"])["player_id"]
    player = await pool.get(Player, star)
    player.status = "i"
    await pool.commit()

    again = await build_dream_team(pool, horizon=1, time_limit=3.0)
    assert star not in {p["player_id"] for p in again["starting"] + again["bench"]}


# ── Failure modes ────────────────────────────────────────────────────────────

async def test_missing_projections_raise_a_clear_error(session):
    session.add(make_team(1))
    session.add(make_gameweek(2, is_next=True))
    await session.commit()
    with pytest.raises(ValueError, match="No projections|not enough"):
        await build_dream_team(session, horizon=1, time_limit=3.0)


async def test_too_few_players_is_reported_not_crashed(session):
    session.add(make_team(1, "AAA"))
    session.add(make_gameweek(2, is_next=True))
    await session.flush()
    for pid in range(1, 6):
        session.add(make_player(pid, team_id=1, position=3))
    await session.flush()
    for pid in range(1, 6):
        session.add(make_projection(pid, 2, xpts=4.0))
    await session.commit()

    with pytest.raises(ValueError, match="not enough"):
        await build_dream_team(session, horizon=1, time_limit=3.0)


async def test_an_impossible_budget_is_reported(pool):
    """15 players cannot be bought for £10m."""
    with pytest.raises(ValueError, match="budget|No legal squad"):
        await build_dream_team(pool, budget=100, horizon=1, time_limit=3.0)


# ── Explanations ─────────────────────────────────────────────────────────────

def _candidate(**kw) -> Candidate:
    player = make_player(
        1, position=kw.pop("position", POS_FWD),
        now_cost=kw.pop("now_cost", 100),
        penalties_order=kw.pop("penalties_order", None),
    )
    player.price_change_percent = kw.pop("price_change_percent", 0.0)
    return Candidate(
        player=player, team_short="AAA",
        xpts=kw.pop("xpts", 6.0), gw_xpts=kw.pop("gw_xpts", 6.0),
        p_start=kw.pop("p_start", 1.0), custom_fdr=kw.pop("custom_fdr", 2.0),
        components=kw.pop("components", {"goals": 3.0, "appearance": 2.0}),
        opponents=kw.pop("opponents", [{"fdr": 2.0, "is_home": True}]),
    )


def test_every_player_gets_at_least_one_reason():
    r = build_reasons(_candidate(), starting=True, is_captain=False,
                      position_rank=3, value_rank=50, position_count=60)
    assert len(r) >= 1


def test_captain_reason_states_the_doubling():
    r = build_reasons(_candidate(xpts=8.0), starting=True, is_captain=True,
                      position_rank=1, value_rank=5, position_count=60)
    assert any("doubled to 16.0" in x for x in r)


def test_top_ranked_player_is_named_as_such():
    r = build_reasons(_candidate(), starting=True, is_captain=False,
                      position_rank=1, value_rank=50, position_count=60)
    assert any("Top-projected" in x for x in r)


def test_bench_reason_explains_the_budget_trade_off():
    r = build_reasons(_candidate(now_cost=40), starting=False, is_captain=False,
                      position_rank=40, value_rank=3, position_count=60)
    assert any("Bench cover" in x for x in r)


def test_the_dominant_scoring_component_is_named():
    r = build_reasons(
        _candidate(components={"clean_sheet": 2.5, "appearance": 1.9}),
        starting=True, is_captain=False,
        position_rank=2, value_rank=20, position_count=60,
    )
    assert any("clean-sheet odds" in x for x in r)


def test_penalty_duty_is_surfaced():
    r = build_reasons(_candidate(penalties_order=1), starting=True,
                      is_captain=False, position_rank=1, value_rank=5,
                      position_count=60)
    assert any("penalty taker" in x for x in r)


def test_rotation_risk_is_stated_honestly():
    r = build_reasons(_candidate(p_start=0.45), starting=True, is_captain=False,
                      position_rank=2, value_rank=9, position_count=60)
    assert any("Risk" in x and "start" in x for x in r)


def test_imminent_price_rise_is_mentioned():
    r = build_reasons(_candidate(price_change_percent=88.0), starting=True,
                      is_captain=False, position_rank=2, value_rank=9,
                      position_count=60)
    assert any("Price rise likely" in x for x in r)


@pytest.mark.parametrize("fdr,expected", [
    (1.5, "Very favourable"),
    (2.4, "Favourable"),
    (3.2, "Average"),
    (4.0, "Tough"),
    (4.8, "Very tough"),
])
def test_fixture_difficulty_is_described_in_words(fdr, expected):
    r = build_reasons(
        _candidate(custom_fdr=fdr, opponents=[{"fdr": fdr, "is_home": True}]),
        starting=True, is_captain=False,
        position_rank=2, value_rank=50, position_count=60,
    )
    assert any(expected in x for x in r)


def test_a_blank_gameweek_produces_no_fixture_claim():
    r = build_reasons(_candidate(opponents=[]), starting=True, is_captain=False,
                      position_rank=2, value_rank=50, position_count=60)
    assert not any("fixture" in x.lower() for x in r)


async def test_reasons_are_present_for_all_fifteen(pool):
    r = await build_dream_team(pool, horizon=1, time_limit=3.0)
    for p in r["starting"] + r["bench"]:
        assert p["reasons"], f"{p['name']} has no reasons"


# ── API ──────────────────────────────────────────────────────────────────────

async def test_endpoint_returns_a_full_squad(client, pool):
    r = await client.get("/api/v1/dream-team?horizon=1")
    assert r.status_code == 200
    body = r.json()
    assert len(body["starting"]) == 11
    assert len(body["bench"]) == 4


@pytest.mark.parametrize("qs,expected", [
    ("budget=100", 200),
    ("budget=40", 422),        # below the allowed range
    ("budget=200", 422),
    ("horizon=0", 422),
    ("horizon=99", 422),
    ("must_include=abc", 400),
])
async def test_endpoint_validation(client, pool, qs, expected):
    r = await client.get(f"/api/v1/dream-team?{qs}")
    assert r.status_code == expected, r.text


async def test_endpoint_reports_a_missing_model_clearly(client, session):
    session.add(make_gameweek(2, is_next=True))
    await session.commit()
    r = await client.get("/api/v1/dream-team")
    assert r.status_code == 400
    assert "projections" in r.json()["detail"].lower() or "enough" in r.json()["detail"].lower()


# ── Helpers ──────────────────────────────────────────────────────────────────

def test_formation_string_counts_outfield_players():
    squad = (
        [_candidate(position=POS_GKP)]
        + [_candidate(position=POS_DEF) for _ in range(4)]
        + [_candidate(position=POS_MID) for _ in range(4)]
        + [_candidate(position=POS_FWD) for _ in range(2)]
    )
    assert _formation(squad) == "4-4-2"


def test_bench_ordering_puts_the_keeper_first():
    bench = [
        _candidate(position=POS_MID, gw_xpts=3.0),
        _candidate(position=POS_GKP, gw_xpts=1.0),
        _candidate(position=POS_DEF, gw_xpts=2.0),
    ]
    ordered = _order_bench(bench)
    assert ordered[0].player.position == POS_GKP


def test_xi_limits_match_the_legal_formations():
    """Derive the formations from the limits and compare."""
    derived = {
        (d, m, f)
        for d in range(XI_LIMITS[POS_DEF][0], XI_LIMITS[POS_DEF][1] + 1)
        for m in range(XI_LIMITS[POS_MID][0], XI_LIMITS[POS_MID][1] + 1)
        for f in range(XI_LIMITS[POS_FWD][0], XI_LIMITS[POS_FWD][1] + 1)
        if d + m + f == 10
    }
    assert derived == set(FORMATIONS)


def test_squad_composition_totals_fifteen():
    assert sum(SQUAD_COMPOSITION.values()) == 15
    assert DEFAULT_BUDGET == 1000
