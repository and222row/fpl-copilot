"""
Post-gameweek accuracy scoring.

Blueprint v1.1 §23: "After each Gameweek finalizes, show users how accurate
each recommendation category was. This is the single most effective retention
feature." It turns the product from something checked before a deadline into
something checked after every gameweek.

Three things are measured, and they answer genuinely different questions:

    error          were the projected points right?      (calibration)
    regret         was it the best available choice?     (decision quality)
    override_delta did ignoring us help or hurt?         (trust)

Regret matters more than error. A captain projected at 6 who scores 11 has a
large error and zero regret if nobody in the squad scored more — the decision
was correct even though the number was not. Reporting only error would call
that a failure.
"""
import logging
from dataclasses import dataclass
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models.fpl import Gameweek, PlayerGameweekStat, utcnow
from app.models.feedback import RecommendationSnapshot, RecommendationOutcome
from app.services.fpl_client import fetch_live_points, fetch_manager_picks

logger = logging.getLogger("fpl_copilot")

KIND_CAPTAIN = "captain"
KIND_LINEUP = "lineup"
KIND_TRANSFER = "transfer"


# ── Snapshotting ─────────────────────────────────────────────────────────────

async def snapshot_recommendation(
    db: AsyncSession,
    *,
    fpl_entry_id: int,
    gameweek_id: int,
    kind: str,
    model_version: str,
    payload: dict,
    predicted_value: float,
    confidence: int = 0,
) -> RecommendationSnapshot:
    """
    Freeze one recommendation so it can be scored later.

    Recommendations are computed on demand, so without a snapshot there is
    nothing to score afterwards — by the time the gameweek finishes the inputs
    have moved, and the model would be graded on advice it never gave.

    Idempotent per (entry, gameweek, kind, model): re-advising before the
    deadline updates the stored snapshot rather than adding a second one, so
    the history holds exactly one entry per decision.
    """
    existing = (await db.execute(
        select(RecommendationSnapshot).where(
            RecommendationSnapshot.fpl_entry_id == fpl_entry_id,
            RecommendationSnapshot.gameweek_id == gameweek_id,
            RecommendationSnapshot.kind == kind,
            RecommendationSnapshot.model_version == model_version,
        )
    )).scalars().first()

    if existing:
        existing.payload = payload
        existing.predicted_value = predicted_value
        existing.confidence = confidence
        existing.created_at = utcnow()
        await db.commit()
        return existing

    snap = RecommendationSnapshot(
        fpl_entry_id=fpl_entry_id,
        gameweek_id=gameweek_id,
        kind=kind,
        model_version=model_version,
        payload=payload,
        predicted_value=predicted_value,
        confidence=confidence,
    )
    db.add(snap)
    await db.commit()
    await db.refresh(snap)
    return snap


# ── Actual results ───────────────────────────────────────────────────────────

async def actual_points(
    db: AsyncSession, gameweek_id: int, player_ids: list[int]
) -> dict[int, int]:
    """
    Points actually scored, summed per player.

    Summed rather than taken singly because a double gameweek produces two
    rows for the same player.
    """
    if not player_ids:
        return {}
    rows = (await db.execute(
        select(PlayerGameweekStat.player_id, func.sum(PlayerGameweekStat.total_points))
        .where(
            PlayerGameweekStat.gameweek_id == gameweek_id,
            PlayerGameweekStat.player_id.in_(player_ids),
        )
        .group_by(PlayerGameweekStat.player_id)
    )).all()
    points = {pid: int(pts or 0) for pid, pts in rows}

    # Stored stats come from a heavy per-player ingest that rarely runs. FPL's
    # live endpoint has every player's total for the gameweek in one request,
    # doubles included, so it fills whatever is missing.
    missing = set(player_ids) - set(points)
    if missing:
        try:
            live = await fetch_live_points(gameweek_id)
            for element in live.get("elements", []):
                if element.get("id") in missing:
                    points[element["id"]] = int((element.get("stats") or {}).get("total_points") or 0)
        except Exception:
            logger.warning("live points unavailable", extra={"gameweek": gameweek_id}, exc_info=True)
    return points


@dataclass
class ActualSquad:
    """What the manager actually fielded, from FPL."""
    player_ids: list[int]
    starting_ids: list[int]
    bench_ids: list[int]
    captain_id: int | None
    vice_id: int | None
    points: int | None
    transfers_made: int
    transfer_cost: int


async def fetch_actual_squad(manager_id: int, gameweek_id: int) -> ActualSquad:
    data = await fetch_manager_picks(manager_id, gameweek_id)
    picks = data.get("picks", [])
    history = data.get("entry_history", {}) or {}

    return ActualSquad(
        player_ids=[p["element"] for p in picks],
        starting_ids=[p["element"] for p in picks if p["position"] <= 11],
        bench_ids=[p["element"] for p in picks if p["position"] > 11],
        captain_id=next((p["element"] for p in picks if p["is_captain"]), None),
        vice_id=next((p["element"] for p in picks if p["is_vice_captain"]), None),
        points=history.get("points"),
        transfers_made=history.get("event_transfers") or 0,
        transfer_cost=history.get("event_transfers_cost") or 0,
    )


# ── Scorers ──────────────────────────────────────────────────────────────────

def _score_captain(payload: dict, actual: ActualSquad, points: dict[int, int]) -> dict:
    """
    Did we name the right captain?

    Judged against the best scorer in the XI the manager actually fielded —
    that was the real choice set, so it is the fair benchmark.
    """
    our_pick = payload.get("player_id")
    our_points = points.get(our_pick, 0)

    candidates = {pid: points.get(pid, 0) for pid in actual.starting_ids}
    best_id, best_points = (
        max(candidates.items(), key=lambda kv: kv[1]) if candidates else (None, 0)
    )

    their_pick = actual.captain_id
    their_points = points.get(their_pick, 0) if their_pick else 0
    followed = their_pick == our_pick if their_pick is not None else None

    return {
        "actual_value": float(our_points * 2),
        "regret": float(max(0, best_points - our_points) * 2),
        "correct": our_pick is not None and our_points >= best_points,
        "followed": followed,
        # Positive means following us would have gained them points.
        "override_delta": (
            None if followed is not False else float((our_points - their_points) * 2)
        ),
        "detail": {
            "recommended_id": our_pick,
            "recommended_name": payload.get("name"),
            "recommended_points": our_points,
            "actual_captain_id": their_pick,
            "actual_captain_points": their_points,
            "best_available_id": best_id,
            "best_available_points": best_points,
        },
    }


def _score_lineup(payload: dict, actual: ActualSquad, points: dict[int, int]) -> dict:
    """
    Would our XI have beaten theirs?

    Both totals exclude the captain multiplier, which is scored separately;
    otherwise a good captain pick would flatter the lineup result.
    """
    our_xi = payload.get("starting_ids") or []
    our_total = sum(points.get(pid, 0) for pid in our_xi)
    their_total = sum(points.get(pid, 0) for pid in actual.starting_ids)

    # Best XI in hindsight — an upper bound on what any lineup call could do.
    all_sorted = sorted((points.get(pid, 0) for pid in actual.player_ids), reverse=True)
    best_possible = sum(all_sorted[:11])

    bench_points = sum(points.get(pid, 0) for pid in actual.bench_ids)
    followed = set(our_xi) == set(actual.starting_ids) if our_xi else None

    return {
        "actual_value": float(our_total),
        "regret": float(max(0, best_possible - our_total)),
        "correct": our_total >= their_total,
        "followed": followed,
        "override_delta": (
            None if followed is not False else float(our_total - their_total)
        ),
        "detail": {
            "recommended_xi_points": our_total,
            "actual_xi_points": their_total,
            "best_possible_xi_points": best_possible,
            "points_left_on_bench": bench_points,
            "formation": payload.get("formation"),
        },
    }


def _score_transfer(payload: dict, actual: ActualSquad, points: dict[int, int]) -> dict:
    """
    Did the recommended transfer pay off this gameweek?

    Only the first gameweek of the horizon is scored. A five-gameweek call
    cannot be judged on one week, so the horizon is carried into the detail to
    keep that limitation visible rather than implied.
    """
    in_ids = [p["player_id"] for p in payload.get("in", [])]
    out_ids = [p["player_id"] for p in payload.get("out", [])]

    in_points = sum(points.get(pid, 0) for pid in in_ids)
    out_points = sum(points.get(pid, 0) for pid in out_ids)
    gw_gain = float(in_points - out_points)

    if not in_ids:
        # We advised holding; following that means making no transfers.
        return {
            "actual_value": 0.0,
            "regret": 0.0,
            "correct": None,          # holding has no single right answer
            "followed": actual.transfers_made == 0,
            "override_delta": None,
            "detail": {
                "advice": "hold",
                "transfers_they_made": actual.transfers_made,
                "hit_they_took": actual.transfer_cost,
            },
        }

    owned = set(actual.player_ids)
    followed = all(pid in owned for pid in in_ids) and all(
        pid not in owned for pid in out_ids
    )

    hit = float(payload.get("hit", 0))
    horizon = payload.get("horizon_gameweeks")

    return {
        "actual_value": gw_gain - hit,
        "regret": 0.0,               # needs the full horizon to judge fairly
        "correct": (gw_gain - hit) > 0,
        "followed": followed,
        "override_delta": None,
        "detail": {
            "in": [
                {"player_id": p["player_id"], "name": p.get("name"),
                 "points": points.get(p["player_id"], 0)}
                for p in payload.get("in", [])
            ],
            "out": [
                {"player_id": p["player_id"], "name": p.get("name"),
                 "points": points.get(p["player_id"], 0)}
                for p in payload.get("out", [])
            ],
            "gameweek_gain_before_hit": gw_gain,
            "hit": hit,
            "horizon_gameweeks": horizon,
            "note": (
                "Scored on this gameweek only; the call was made over "
                f"{horizon} gameweeks."
            ),
        },
    }


SCORERS = {
    KIND_CAPTAIN: _score_captain,
    KIND_LINEUP: _score_lineup,
    KIND_TRANSFER: _score_transfer,
}


# ── Orchestration ────────────────────────────────────────────────────────────

def _referenced_players(snapshots, actual: ActualSquad) -> set[int]:
    referenced: set[int] = set(actual.player_ids)
    for s in snapshots:
        payload = s.payload or {}
        if s.kind == KIND_CAPTAIN and payload.get("player_id"):
            referenced.add(payload["player_id"])
        elif s.kind == KIND_LINEUP:
            referenced.update(payload.get("starting_ids") or [])
        elif s.kind == KIND_TRANSFER:
            referenced.update(p["player_id"] for p in payload.get("in", []))
            referenced.update(p["player_id"] for p in payload.get("out", []))
    return referenced


async def score_gameweek(
    db: AsyncSession, manager_id: int, gameweek_id: int, force: bool = False
) -> dict:
    """
    Score every snapshotted recommendation for one finished gameweek.

    Refuses to score an unfinished gameweek by default: partial results would
    bake a wrong verdict into the running history. `force` allows scoring on
    provisional results, since FPL's `finished` flag lags by days.
    """
    gw = await db.get(Gameweek, gameweek_id)
    if gw is None:
        return {"error": f"Gameweek {gameweek_id} not found", "scored": 0}

    if not gw.finished and not force:
        return {
            "error": (
                f"GW{gameweek_id} is not finished. Pass force=true to score it "
                f"on provisional results."
            ),
            "scored": 0,
        }

    snapshots = (await db.execute(
        select(RecommendationSnapshot).where(
            RecommendationSnapshot.fpl_entry_id == manager_id,
            RecommendationSnapshot.gameweek_id == gameweek_id,
        )
    )).scalars().all()

    if not snapshots:
        return {
            "error": (
                f"No recommendations were saved for GW{gameweek_id}. Accuracy "
                f"can only be measured for advice recorded before the deadline."
            ),
            "scored": 0,
        }

    already = {
        o.snapshot_id
        for o in (await db.execute(
            select(RecommendationOutcome).where(
                RecommendationOutcome.snapshot_id.in_([s.id for s in snapshots])
            )
        )).scalars().all()
    }

    try:
        actual = await fetch_actual_squad(manager_id, gameweek_id)
    except Exception as e:
        return {"error": f"Could not fetch actual squad: {e}", "scored": 0}

    points = await actual_points(
        db, gameweek_id, sorted(_referenced_players(snapshots, actual))
    )
    if not points:
        return {
            "error": (
                f"No actual results stored for GW{gameweek_id}. Run "
                f"POST /api/v1/projections/backtest/ingest-history first."
            ),
            "scored": 0,
        }

    scored = 0
    skipped = 0
    results = []

    for snap in snapshots:
        if snap.id in already and not force:
            skipped += 1
            continue

        scorer = SCORERS.get(snap.kind)
        if scorer is None:
            logger.warning("no scorer registered", extra={"kind": snap.kind})
            continue

        data = scorer(snap.payload or {}, actual, points)

        existing = (await db.execute(
            select(RecommendationOutcome).where(
                RecommendationOutcome.snapshot_id == snap.id
            )
        )).scalars().first()

        row = existing or RecommendationOutcome(
            snapshot_id=snap.id,
            fpl_entry_id=manager_id,
            gameweek_id=gameweek_id,
            kind=snap.kind,
            model_version=snap.model_version,
        )
        row.followed = data["followed"]
        row.correct = data["correct"]
        row.predicted_value = snap.predicted_value
        row.actual_value = data["actual_value"]
        row.error = round(data["actual_value"] - snap.predicted_value, 3)
        row.regret = data["regret"]
        row.override_delta = data["override_delta"]
        row.detail = data["detail"]
        row.scored_at = utcnow()

        if existing is None:
            db.add(row)
        scored += 1
        results.append({
            "kind": snap.kind,
            "predicted": snap.predicted_value,
            "actual": row.actual_value,
            "error": row.error,
            "regret": row.regret,
            "correct": row.correct,
            "followed": row.followed,
        })

    await db.commit()
    return {
        "gameweek": gameweek_id,
        "manager_id": manager_id,
        "scored": scored,
        "skipped_already_scored": skipped,
        "results": results,
    }


async def accuracy_summary(db: AsyncSession, manager_id: int) -> dict:
    """
    Running accuracy across every scored gameweek.

    Reported per category: the model can be good at one decision and poor at
    another, and a single aggregate would hide that.
    """
    outcomes = (await db.execute(
        select(RecommendationOutcome)
        .where(RecommendationOutcome.fpl_entry_id == manager_id)
        .order_by(RecommendationOutcome.gameweek_id)
    )).scalars().all()

    if not outcomes:
        return {
            "manager_id": manager_id,
            "gameweeks_scored": 0,
            "categories": {},
            "note": (
                "Nothing scored yet. Recommendations are saved when you view "
                "them, then scored once the gameweek finishes."
            ),
        }

    categories: dict[str, dict] = {}
    for o in outcomes:
        c = categories.setdefault(o.kind, {
            "count": 0, "correct": 0, "gradeable": 0,
            "total_error": 0.0, "total_abs_error": 0.0, "total_regret": 0.0,
            "followed": 0, "follow_gradeable": 0,
            "override_delta": 0.0, "override_count": 0,
        })
        c["count"] += 1
        c["total_error"] += o.error
        c["total_abs_error"] += abs(o.error)
        c["total_regret"] += o.regret
        if o.correct is not None:
            c["gradeable"] += 1
            c["correct"] += 1 if o.correct else 0
        if o.followed is not None:
            c["follow_gradeable"] += 1
            c["followed"] += 1 if o.followed else 0
        if o.override_delta is not None:
            c["override_count"] += 1
            c["override_delta"] += o.override_delta

    summary = {}
    for kind, c in categories.items():
        summary[kind] = {
            "decisions": c["count"],
            "hit_rate": round(c["correct"] / c["gradeable"], 3) if c["gradeable"] else None,
            "mean_error": round(c["total_error"] / c["count"], 2),
            "mean_absolute_error": round(c["total_abs_error"] / c["count"], 2),
            "mean_regret": round(c["total_regret"] / c["count"], 2),
            "follow_rate": (
                round(c["followed"] / c["follow_gradeable"], 3)
                if c["follow_gradeable"] else None
            ),
            "points_lost_by_overriding": (
                round(c["override_delta"], 1) if c["override_count"] else None
            ),
        }

    gameweeks = sorted({o.gameweek_id for o in outcomes})

    return {
        "manager_id": manager_id,
        "gameweeks_scored": len(gameweeks),
        "gameweeks": gameweeks,
        "categories": summary,
        "total_regret": round(sum(o.regret for o in outcomes), 1),
        "interpretation": {
            "hit_rate": "How often the recommendation was the best available "
                        "choice. The headline number.",
            "mean_error": "Actual minus predicted points. Negative means the "
                          "model over-projects.",
            "mean_regret": "Points forgone versus the best choice available. "
                           "Zero is a perfect decision even if the points "
                           "prediction was wrong.",
            "points_lost_by_overriding": "Net points difference on the "
                                         "occasions the advice was not "
                                         "followed. Positive means following "
                                         "would have scored more.",
        },
    }


async def outcome_history(db: AsyncSession, manager_id: int, limit: int = 50) -> list[dict]:
    """Per-gameweek outcomes, newest first, for the accuracy timeline."""
    rows = (await db.execute(
        select(RecommendationOutcome)
        .where(RecommendationOutcome.fpl_entry_id == manager_id)
        .order_by(RecommendationOutcome.gameweek_id.desc(),
                  RecommendationOutcome.kind)
        .limit(limit)
    )).scalars().all()

    return [
        {
            "gameweek": o.gameweek_id,
            "kind": o.kind,
            "predicted": round(o.predicted_value, 2),
            "actual": round(o.actual_value, 2),
            "error": round(o.error, 2),
            "regret": round(o.regret, 2),
            "correct": o.correct,
            "followed": o.followed,
            "override_delta": o.override_delta,
            "detail": o.detail,
            "model_version": o.model_version,
            "scored_at": o.scored_at,
        }
        for o in rows
    ]


async def score_finished(db: AsyncSession) -> dict:
    """
    Grade every saved recommendation whose gameweek FPL has marked finished.

    Run by the scheduled refresh, so the track record fills itself in a day or
    two after each gameweek (FPL's `finished` flag waits for bonus points and
    data checks). Already-graded snapshots are skipped, so it is cheap to
    repeat.
    """
    finished = select(Gameweek.id).where(Gameweek.finished.is_(True))
    graded = select(RecommendationOutcome.snapshot_id)
    pairs = (await db.execute(
        select(RecommendationSnapshot.fpl_entry_id, RecommendationSnapshot.gameweek_id)
        .where(
            RecommendationSnapshot.gameweek_id.in_(finished),
            RecommendationSnapshot.id.not_in(graded),
        )
        .distinct()
    )).all()

    scored = 0
    failures = []
    for entry, gameweek in pairs:
        result = await score_gameweek(db, entry, gameweek)
        scored += result.get("scored", 0)
        if result.get("error"):
            failures.append({"gameweek": gameweek, "error": result["error"][:200]})
    return {"teams_gameweeks": len(pairs), "scored": scored, "failures": failures}
