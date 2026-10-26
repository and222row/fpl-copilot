"""
The gameweek review: how a finished gameweek went for one manager.

Points against the average and the highest, gameweek and overall rank and
how the overall rank moved, the best and worst contributions, the captain
against the best captain the XI offered, points left on the bench, how the
advice did (graded by services/feedback.py), the mini-leagues, and the season
so far for a chart. Everything comes from data already read elsewhere: FPL's
live points and picks through services/live.py, the manager's FPL history
(cached), and our own track record. Nothing new is stored.
"""
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.feedback import RecommendationOutcome
from app.models.fpl import Fixture, Gameweek
from app.services import live
from app.services.fpl_client import fetch_manager_history
from app.services.fpl_sync import deadline_has_passed
from app.services.leagues import _player_rows, manager_leagues

BEST_SHOWN = 3
WORST_SHOWN = 2


class ReviewUnavailable(Exception):
    """No finished gameweek yet, or FPL has no squad for the manager in it."""


async def reviewable_gameweek(db: AsyncSession) -> Gameweek | None:
    """The latest gameweek whose matches are all over, by the synced fixtures."""
    started = [g for g in (await db.execute(select(Gameweek).order_by(Gameweek.id.desc()))).scalars() if deadline_has_passed(g)]
    for gw in started:
        states = (await db.execute(
            select(Fixture.finished_provisional, Fixture.finished).where(Fixture.gameweek_id == gw.id)
        )).all()
        if states and all(fp or f for fp, f in states):
            return gw
    return None


async def review(db: AsyncSession, manager_id: int, gameweek: int | None = None) -> dict:
    gw = await db.get(Gameweek, gameweek) if gameweek is not None else await reviewable_gameweek(db)
    if gw is None or not deadline_has_passed(gw):
        raise ReviewUnavailable("No finished gameweek to review yet.")
    players, fixtures = await live._world(db, gw.id)
    try:
        picks = await live._picks(manager_id, gw.id)
    except httpx.HTTPStatusError as e:
        if e.response is not None and e.response.status_code == 404:
            raise ReviewUnavailable(f"FPL has no squad for you in {gw.name}.")
        raise
    team = live.team_live(picks, players)
    info = await _player_rows(db, {r["element"] for r in team.rows}, gw.id)

    def player(row: dict) -> dict:
        base = info.get(row["element"], {"player_id": row["element"], "name": f"#{row['element']}", "team": "", "position": "UNK"})
        return {
            "player_id": base["player_id"], "name": base["name"], "team": base["team"], "position": base["position"],
            "points": row["points"], "multiplier": row["multiplier"], "contribution": row["points"] * row["multiplier"],
            "minutes": row["minutes"],
        }

    counted = sorted((player(r) for r in team.rows if r["multiplier"]), key=lambda p: (-p["contribution"], p["name"]))
    unused = [player(r) for r in team.rows if not r["multiplier"] and not r["subbed_out"]]
    armband = next((p for p in counted if p["player_id"] == team.armband), None)
    best_captain = max(counted, key=lambda p: p["points"], default=None)
    extra = (armband["multiplier"] - 1) if armband else 1

    history = {h["event"]: h for h in (await fetch_manager_history(manager_id)).get("current") or []}
    this, before = history.get(gw.id, {}), history.get(gw.id - 1, {})
    averages = dict((await db.execute(select(Gameweek.id, Gameweek.average_entry_score))).all())

    outcomes = (await db.execute(
        select(RecommendationOutcome).where(
            RecommendationOutcome.fpl_entry_id == manager_id, RecommendationOutcome.gameweek_id == gw.id,
        ).order_by(RecommendationOutcome.kind)
    )).scalars().all()

    try:
        leagues = [l for l in await manager_leagues(manager_id) if l["private"]]
    except httpx.HTTPError:
        leagues = []

    return {
        "gameweek": {"id": gw.id, "name": gw.name, "average": gw.average_entry_score or None, "highest": gw.highest_score or None},
        "finished": all(live.fixture_state(f) == live.DONE for f in fixtures),
        "points": team.points,
        "transfer_cost": team.transfer_cost,
        "chip": team.chip,
        "gameweek_rank": this.get("rank"),
        "overall_rank": this.get("overall_rank"),
        "previous_overall_rank": before.get("overall_rank"),
        "best": counted[:BEST_SHOWN],
        "worst": sorted(counted, key=lambda p: (p["contribution"], p["name"]))[:WORST_SHOWN],
        "captain": {
            "pick": armband,
            "best": best_captain,
            # What the armband on the XI's top scorer would have added.
            "missed": max(0, (best_captain["points"] - (armband["points"] if armband else 0)) * extra) if best_captain else 0,
        },
        "bench_points": sum(p["points"] for p in unused),
        "bench": sorted(unused, key=lambda p: -p["points"]),
        "auto_subs": [{"out": info.get(o, {}).get("name"), "in": info.get(i, {}).get("name")} for o, i in team.auto_subs],
        "advice": [
            {
                "kind": o.kind, "followed": o.followed, "correct": o.correct,
                "predicted": round(o.predicted_value, 1), "actual": round(o.actual_value, 1),
                "regret": round(o.regret, 1),
                "override_delta": round(o.override_delta, 1) if o.override_delta is not None else None,
            }
            for o in outcomes
        ],
        "leagues": [{"id": l["id"], "name": l["name"], "rank": l["rank"], "last_rank": l["last_rank"], "size": l["size"]} for l in leagues],
        "season": [
            {"gameweek": e, "points": h.get("points", 0) - h.get("event_transfers_cost", 0),
             "average": averages.get(e) or None, "overall_rank": h.get("overall_rank")}
            for e, h in sorted(history.items()) if e <= gw.id
        ],
    }
