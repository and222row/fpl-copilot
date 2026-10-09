"""
Accuracy scoring tests.

The distinction these protect is the whole point of the feature: `error`
measures whether the points prediction was right, `regret` measures whether
the *decision* was right. A captain projected at 6 who scores 11 has a big
error and zero regret if nobody scored more — grading that as a failure would
make the accuracy report actively misleading.
"""
import pytest
from app.services.feedback import (
    ActualSquad, _score_captain, _score_lineup, _score_transfer,
    accuracy_summary, snapshot_recommendation, score_gameweek,
    KIND_CAPTAIN, KIND_LINEUP, KIND_TRANSFER,
)
from app.models.feedback import RecommendationOutcome
from tests.conftest import make_team, make_player, make_gameweek
from app.models.fpl import PlayerGameweekStat


def squad(
    starting=(1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11),
    bench=(12, 13, 14, 15),
    captain=1,
    vice=2,
    transfers=0,
    cost=0,
) -> ActualSquad:
    return ActualSquad(
        player_ids=list(starting) + list(bench),
        starting_ids=list(starting),
        bench_ids=list(bench),
        captain_id=captain,
        vice_id=vice,
        points=None,
        transfers_made=transfers,
        transfer_cost=cost,
    )


# ── Captain scoring ──────────────────────────────────────────────────────────

def test_captain_value_is_doubled():
    points = {1: 12, 2: 5}
    r = _score_captain({"player_id": 1}, squad(captain=1), points)
    assert r["actual_value"] == 24.0


def test_captain_is_correct_when_it_was_the_top_scorer():
    points = {i: 2 for i in range(1, 16)}
    points[3] = 15
    r = _score_captain({"player_id": 3}, squad(captain=3), points)
    assert r["correct"] is True
    assert r["regret"] == 0.0


def test_captain_regret_is_the_doubled_shortfall():
    points = {i: 2 for i in range(1, 16)}
    points[3] = 15          # best available
    points[7] = 4           # what we picked
    r = _score_captain({"player_id": 7}, squad(captain=7), points)
    assert r["correct"] is False
    assert r["regret"] == (15 - 4) * 2


def test_large_error_with_zero_regret_is_still_correct():
    """The case that makes error alone a bad metric."""
    points = {i: 1 for i in range(1, 16)}
    points[1] = 11          # our pick, way over its projection
    r = _score_captain({"player_id": 1}, squad(captain=1), points)
    assert r["correct"] is True
    assert r["regret"] == 0.0


def test_captain_regret_ignores_bench_players():
    """Only the fielded XI was a real choice."""
    points = {i: 2 for i in range(1, 16)}
    points[14] = 20         # benched, so never captainable
    r = _score_captain({"player_id": 1}, squad(captain=1), points)
    assert r["regret"] == 0.0


def test_captain_followed_when_the_manager_used_our_pick():
    r = _score_captain({"player_id": 5}, squad(captain=5), {5: 8})
    assert r["followed"] is True
    assert r["override_delta"] is None


def test_override_delta_is_positive_when_following_would_have_helped():
    points = {5: 10, 9: 2}
    r = _score_captain({"player_id": 5}, squad(captain=9), points)
    assert r["followed"] is False
    assert r["override_delta"] == (10 - 2) * 2


def test_override_delta_is_negative_when_the_manager_was_right():
    points = {5: 1, 9: 12}
    r = _score_captain({"player_id": 5}, squad(captain=9), points)
    assert r["override_delta"] == (1 - 12) * 2


def test_captain_scoring_survives_missing_points_data():
    r = _score_captain({"player_id": 99}, squad(), {})
    assert r["actual_value"] == 0.0
    assert r["correct"] is True      # nobody scored, so nothing was missed


# ── Lineup scoring ───────────────────────────────────────────────────────────

def test_lineup_totals_our_recommended_xi():
    points = {i: 3 for i in range(1, 16)}
    r = _score_lineup({"starting_ids": list(range(1, 12))}, squad(), points)
    assert r["actual_value"] == 33.0


def test_lineup_regret_measures_the_best_possible_eleven():
    points = {i: 1 for i in range(1, 16)}
    points[13] = 20                     # a benched player hauled
    r = _score_lineup({"starting_ids": list(range(1, 12))}, squad(), points)
    # Best XI swaps the 20 in for a 1
    assert r["regret"] == pytest.approx((10 * 1 + 20) - 11)


def test_lineup_correct_when_we_match_or_beat_what_they_fielded():
    points = {i: 2 for i in range(1, 16)}
    r = _score_lineup({"starting_ids": list(range(1, 12))}, squad(), points)
    assert r["correct"] is True
    assert r["followed"] is True


def test_lineup_detects_a_different_xi_and_prices_the_difference():
    points = {i: 1 for i in range(1, 16)}
    points[12] = 9                       # we said start him, they benched him
    ours = list(range(1, 11)) + [12]
    r = _score_lineup({"starting_ids": ours}, squad(), points)
    assert r["followed"] is False
    assert r["override_delta"] == pytest.approx((10 + 9) - 11)


def test_bench_points_are_reported():
    points = {i: 1 for i in range(1, 16)}
    points[13] = 7
    r = _score_lineup({"starting_ids": list(range(1, 12))}, squad(), points)
    assert r["detail"]["points_left_on_bench"] == 3 + 7


# ── Transfer scoring ─────────────────────────────────────────────────────────

def test_transfer_gain_is_net_of_the_hit():
    payload = {
        "in": [{"player_id": 50, "name": "In"}],
        "out": [{"player_id": 3, "name": "Out"}],
        "hit": 4,
        "horizon_gameweeks": 5,
    }
    r = _score_transfer(payload, squad(starting=(50, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11)),
                        {50: 9, 3: 2})
    assert r["detail"]["gameweek_gain_before_hit"] == 7.0
    assert r["actual_value"] == 3.0
    assert r["correct"] is True


def test_transfer_marked_incorrect_when_the_hit_was_not_repaid():
    payload = {
        "in": [{"player_id": 50, "name": "In"}],
        "out": [{"player_id": 3, "name": "Out"}],
        "hit": 4,
        "horizon_gameweeks": 5,
    }
    r = _score_transfer(payload, squad(starting=(50, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12)),
                        {50: 3, 3: 2})
    assert r["actual_value"] == -3.0
    assert r["correct"] is False


def test_transfer_detail_states_the_single_gameweek_limitation():
    payload = {
        "in": [{"player_id": 50, "name": "In"}],
        "out": [{"player_id": 3, "name": "Out"}],
        "hit": 0,
        "horizon_gameweeks": 5,
    }
    r = _score_transfer(payload, squad(), {50: 6, 3: 1})
    assert r["detail"]["horizon_gameweeks"] == 5
    assert "this gameweek only" in r["detail"]["note"]


def test_transfer_followed_requires_in_owned_and_out_gone():
    payload = {"in": [{"player_id": 50}], "out": [{"player_id": 3}], "hit": 0}
    # 50 is in the squad, 3 is not
    acted = squad(starting=(50, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12), bench=(13, 14, 15, 16))
    assert _score_transfer(payload, acted, {50: 5, 3: 1})["followed"] is True
    # 3 still owned, so they did not do it
    assert _score_transfer(payload, squad(), {50: 5, 3: 1})["followed"] is False


def test_hold_advice_is_followed_when_no_transfers_were_made():
    r = _score_transfer({"in": [], "out": []}, squad(transfers=0), {})
    assert r["followed"] is True
    assert r["correct"] is None          # holding has no single right answer
    assert r["detail"]["advice"] == "hold"


def test_hold_advice_is_overridden_when_they_transferred():
    r = _score_transfer({"in": [], "out": []}, squad(transfers=2, cost=4), {})
    assert r["followed"] is False
    assert r["detail"]["hit_they_took"] == 4


# ── End-to-end through the database ──────────────────────────────────────────

@pytest.fixture
async def seeded(session):
    session.add(make_team(1, "AAA"))
    session.add(make_gameweek(1, finished=True))
    await session.flush()
    for pid in range(1, 16):
        session.add(make_player(pid, team_id=1, web_name=f"P{pid}"))
    await session.flush()
    # Actual results: player 3 hauls, everyone else scores 2
    for pid in range(1, 16):
        session.add(PlayerGameweekStat(
            player_id=pid, gameweek_id=1, fixture_id=1,
            total_points=15 if pid == 3 else 2, minutes=90,
        ))
    await session.commit()
    return session


async def test_snapshot_is_idempotent_per_decision(seeded):
    for value in (8.0, 9.5):
        await snapshot_recommendation(
            seeded, fpl_entry_id=1, gameweek_id=1, kind=KIND_CAPTAIN,
            model_version="proj-v1",
            payload={"player_id": 1, "name": "P1"}, predicted_value=value,
        )
    from sqlalchemy import select, func
    from app.models.feedback import RecommendationSnapshot
    count = (await seeded.execute(
        select(func.count()).select_from(RecommendationSnapshot)
    )).scalar()
    assert count == 1, "re-advising should update, not duplicate"

    row = (await seeded.execute(select(RecommendationSnapshot))).scalars().first()
    assert row.predicted_value == 9.5


async def test_scoring_refuses_an_unfinished_gameweek(session):
    session.add(make_gameweek(2, finished=False))
    await session.commit()
    result = await score_gameweek(session, manager_id=1, gameweek_id=2)
    assert result["scored"] == 0
    assert "not finished" in result["error"]


async def test_scoring_explains_when_nothing_was_recorded(seeded):
    result = await score_gameweek(seeded, manager_id=1, gameweek_id=1)
    assert result["scored"] == 0
    assert "No recommendations were saved" in result["error"]


async def test_scoring_reports_a_missing_gameweek(session):
    result = await score_gameweek(session, manager_id=1, gameweek_id=99)
    assert result["scored"] == 0
    assert "not found" in result["error"]


async def test_accuracy_summary_is_empty_before_anything_is_scored(session):
    s = await accuracy_summary(session, manager_id=1)
    assert s["gameweeks_scored"] == 0
    assert s["categories"] == {}
    assert "Nothing scored yet" in s["note"]


async def test_accuracy_summary_aggregates_per_category(session):
    session.add_all([
        RecommendationOutcome(
            snapshot_id=1, fpl_entry_id=1, gameweek_id=1, kind=KIND_CAPTAIN,
            model_version="v1", correct=True, followed=True,
            predicted_value=10.0, actual_value=12.0, error=2.0, regret=0.0,
        ),
        RecommendationOutcome(
            snapshot_id=2, fpl_entry_id=1, gameweek_id=2, kind=KIND_CAPTAIN,
            model_version="v1", correct=False, followed=False,
            predicted_value=10.0, actual_value=4.0, error=-6.0, regret=8.0,
            override_delta=-3.0,
        ),
        RecommendationOutcome(
            snapshot_id=3, fpl_entry_id=1, gameweek_id=1, kind=KIND_LINEUP,
            model_version="v1", correct=True, followed=True,
            predicted_value=40.0, actual_value=44.0, error=4.0, regret=2.0,
        ),
    ])
    await session.commit()

    s = await accuracy_summary(session, manager_id=1)
    assert s["gameweeks_scored"] == 2

    cap = s["categories"][KIND_CAPTAIN]
    assert cap["decisions"] == 2
    assert cap["hit_rate"] == 0.5
    assert cap["mean_error"] == -2.0
    assert cap["mean_regret"] == 4.0
    assert cap["follow_rate"] == 0.5
    assert cap["points_lost_by_overriding"] == -3.0

    assert s["categories"][KIND_LINEUP]["hit_rate"] == 1.0
    assert s["total_regret"] == 10.0


async def test_summary_isolates_managers(session):
    session.add_all([
        RecommendationOutcome(
            snapshot_id=1, fpl_entry_id=1, gameweek_id=1, kind=KIND_CAPTAIN,
            model_version="v1", correct=True, predicted_value=1, actual_value=1,
        ),
        RecommendationOutcome(
            snapshot_id=2, fpl_entry_id=2, gameweek_id=1, kind=KIND_CAPTAIN,
            model_version="v1", correct=False, predicted_value=1, actual_value=1,
        ),
    ])
    await session.commit()
    assert (await accuracy_summary(session, 1))["categories"][KIND_CAPTAIN]["hit_rate"] == 1.0
    assert (await accuracy_summary(session, 2))["categories"][KIND_CAPTAIN]["hit_rate"] == 0.0


# ── API surface ──────────────────────────────────────────────────────────────

async def test_accuracy_endpoint_on_empty_history(client):
    r = await client.get("/api/v1/feedback/1/accuracy")
    assert r.status_code == 200
    assert r.json()["gameweeks_scored"] == 0


async def test_history_endpoint_returns_a_list(client):
    r = await client.get("/api/v1/feedback/1/history")
    assert r.status_code == 200
    assert r.json() == []


async def test_pending_endpoint_reports_nothing_saved(client):
    r = await client.get("/api/v1/feedback/1/pending")
    assert r.status_code == 200
    assert r.json()["count"] == 0


async def test_score_endpoint_requires_a_gameweek(client):
    r = await client.post("/api/v1/feedback/1/score")
    assert r.status_code == 422


async def test_score_endpoint_400s_with_an_explanation(client, session):
    session.add(make_gameweek(1, finished=True))
    await session.commit()
    r = await client.post("/api/v1/feedback/1/score?gameweek=1")
    assert r.status_code == 400
    assert "No recommendations were saved" in r.json()["detail"]


async def test_score_all_is_safe_with_nothing_recorded(client):
    r = await client.post("/api/v1/feedback/1/score-all")
    assert r.status_code == 200
    assert r.json()["scored_gameweeks"] == []


# ── Automatic grading in the refresh ─────────────────────────────────────────

@pytest.fixture
async def finished_without_stats(session):
    """A finished gameweek with a saved captain pick and no stored results."""
    session.add(make_team(1, "AAA"))
    session.add(make_gameweek(1, finished=True))
    session.add(make_gameweek(2, finished=False))
    await session.flush()
    for pid in range(1, 16):
        session.add(make_player(pid, team_id=1, web_name=f"P{pid}"))
    await session.flush()
    for gw in (1, 2):
        await snapshot_recommendation(
            session, fpl_entry_id=7, gameweek_id=gw, kind=KIND_CAPTAIN,
            model_version="proj-v1", payload={"player_id": 1, "name": "P1"}, predicted_value=12.0,
        )
    return session


def _live(points_by_player):
    async def fetch(gameweek):
        return {"elements": [{"id": pid, "stats": {"total_points": pts}} for pid, pts in points_by_player.items()]}
    return fetch


async def test_finished_gameweeks_are_graded_from_live_points(finished_without_stats, monkeypatch):
    from app.services import feedback

    async def actual(manager_id, gameweek_id):
        return squad(captain=1)

    monkeypatch.setattr(feedback, "fetch_actual_squad", actual)
    monkeypatch.setattr(feedback, "fetch_live_points", _live({pid: (9 if pid == 1 else 2) for pid in range(1, 16)}))

    result = await feedback.score_finished(finished_without_stats)
    assert result == {"teams_gameweeks": 1, "scored": 1, "failures": []}  # GW2 is not finished

    summary = await accuracy_summary(finished_without_stats, 7)
    assert summary["gameweeks_scored"] == 1
    assert summary["categories"]["captain"]["hit_rate"] == 1.0  # 9 was the best in the XI

    again = await feedback.score_finished(finished_without_stats)
    assert again["teams_gameweeks"] == 0  # already graded, nothing to redo


async def test_live_points_outage_reports_instead_of_failing(finished_without_stats, monkeypatch):
    from app.services import feedback

    async def actual(manager_id, gameweek_id):
        return squad(captain=1)

    async def down(gameweek):
        raise RuntimeError("FPL down")

    monkeypatch.setattr(feedback, "fetch_actual_squad", actual)
    monkeypatch.setattr(feedback, "fetch_live_points", down)
    result = await feedback.score_finished(finished_without_stats)
    assert result["scored"] == 0 and result["failures"]
