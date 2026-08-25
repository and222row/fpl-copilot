"""
Backtest harness.

Blueprint §25: "Build a backtest command before tuning model weights."
This exists so model changes are judged on measured accuracy rather than
whether the numbers look plausible.

Metrics:
    MAE      mean absolute error in points
    RMSE     root mean squared error (punishes big misses)
    bias     mean signed error; positive = model over-projects
    spearman rank correlation — matters more than absolute error, because
             FPL decisions are comparisons between players, not forecasts
"""
import math
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models.fpl import Player, PlayerGameweekStat, Gameweek
from app.models.projections import Projection
from app.services.fpl_client import fetch_player_detail


async def ingest_player_history(
    db: AsyncSession,
    player_ids: list[int] | None = None,
    limit: int | None = None,
) -> dict:
    """
    Pull per-gameweek actuals from /element-summary/{id}/ into
    player_gameweek_stats.

    One HTTP call per player, so this is slow for the full 600+ squad list.
    Pass `limit` to sample, or `player_ids` to target.
    """
    if player_ids is None:
        q = select(Player.id).order_by(Player.total_points.desc())
        if limit:
            q = q.limit(limit)
        player_ids = list((await db.execute(q)).scalars().all())

    existing_keys = set(
        (await db.execute(
            select(PlayerGameweekStat.player_id, PlayerGameweekStat.gameweek_id,
                   PlayerGameweekStat.fixture_id)
        )).all()
    )

    inserted = 0
    failed = 0
    for pid in player_ids:
        try:
            detail = await fetch_player_detail(pid)
        except Exception:
            failed += 1
            continue

        for h in detail.get("history", []):
            gw = h.get("round")
            fid = h.get("fixture")
            if gw is None:
                continue
            if (pid, gw, fid) in existing_keys:
                continue
            db.add(PlayerGameweekStat(
                player_id=pid,
                gameweek_id=gw,
                fixture_id=fid,
                opponent_team=h.get("opponent_team"),
                was_home=bool(h.get("was_home")),
                total_points=_i(h.get("total_points")),
                minutes=_i(h.get("minutes")),
                starts=_i(h.get("starts")),
                goals_scored=_i(h.get("goals_scored")),
                assists=_i(h.get("assists")),
                clean_sheets=_i(h.get("clean_sheets")),
                goals_conceded=_i(h.get("goals_conceded")),
                own_goals=_i(h.get("own_goals")),
                penalties_saved=_i(h.get("penalties_saved")),
                penalties_missed=_i(h.get("penalties_missed")),
                yellow_cards=_i(h.get("yellow_cards")),
                red_cards=_i(h.get("red_cards")),
                saves=_i(h.get("saves")),
                bonus=_i(h.get("bonus")),
                bps=_i(h.get("bps")),
                defensive_contribution=_i(h.get("defensive_contribution")),
                expected_goals=_f(h.get("expected_goals")),
                expected_assists=_f(h.get("expected_assists")),
                expected_goals_conceded=_f(h.get("expected_goals_conceded")),
                value=_i(h.get("value")),
            ))
            existing_keys.add((pid, gw, fid))
            inserted += 1

    await db.commit()
    return {"players_processed": len(player_ids), "rows_inserted": inserted, "failed": failed}


async def backtest(
    db: AsyncSession,
    model_version: str,
    gameweeks: list[int] | None = None,
    min_expected_minutes: float = 0.0,
) -> dict:
    """
    Score stored projections against recorded actuals.

    Only finished gameweeks with both a projection and an actual are scored.
    """
    q = (
        select(Projection, PlayerGameweekStat.total_points, Player.position)
        .join(
            PlayerGameweekStat,
            (PlayerGameweekStat.player_id == Projection.player_id)
            & (PlayerGameweekStat.gameweek_id == Projection.gameweek_id),
        )
        .join(Player, Player.id == Projection.player_id)
        .where(Projection.model_version == model_version)
    )
    if gameweeks:
        q = q.where(Projection.gameweek_id.in_(gameweeks))
    if min_expected_minutes > 0:
        q = q.where(Projection.expected_minutes >= min_expected_minutes)

    rows = (await db.execute(q)).all()
    if not rows:
        return {
            "model_version": model_version,
            "sample_size": 0,
            "note": "No overlapping projections and actuals. "
                    "Ingest history and project a finished gameweek first.",
        }

    # A double gameweek produces two actual rows per projection; sum them.
    agg: dict[tuple[int, int], dict] = {}
    for proj, actual, position in rows:
        key = (proj.player_id, proj.gameweek_id)
        if key not in agg:
            agg[key] = {"pred": proj.xpts, "actual": 0.0, "position": position}
        agg[key]["actual"] += actual

    preds = [v["pred"] for v in agg.values()]
    actuals = [v["actual"] for v in agg.values()]
    n = len(preds)

    errors = [p - a for p, a in zip(preds, actuals)]
    mae = sum(abs(e) for e in errors) / n
    rmse = math.sqrt(sum(e * e for e in errors) / n)
    bias = sum(errors) / n

    # Per-position breakdown
    by_position: dict[str, dict] = {}
    pos_names = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
    for v in agg.values():
        name = pos_names.get(v["position"], "UNK")
        b = by_position.setdefault(name, {"n": 0, "abs_err": 0.0, "err": 0.0})
        b["n"] += 1
        b["abs_err"] += abs(v["pred"] - v["actual"])
        b["err"] += v["pred"] - v["actual"]
    for name, b in by_position.items():
        b["mae"] = round(b["abs_err"] / b["n"], 3)
        b["bias"] = round(b["err"] / b["n"], 3)
        del b["abs_err"], b["err"]

    # How much of the player pool does this sample actually cover? If history
    # was ingested with a `limit`, it is the TOP-N by points — a sample of
    # known high scorers, which inflates mean_actual and shows up as large
    # negative bias that is selection, not model error.
    total_players = (await db.execute(select(func.count()).select_from(Player))).scalar() or 0
    coverage = round(n / total_players, 3) if total_players else 0.0

    caveats = []
    if coverage < 0.5:
        caveats.append(
            f"Sample covers only {coverage:.0%} of players. If history was ingested "
            f"with a limit it is the top scorers, so `bias` reflects that selection "
            f"rather than model error. Ingest all players for a trustworthy bias figure."
        )

    # Was the projected gameweek already played when the projection was built?
    scored_gws = sorted({gw for _, gw in agg.keys()})
    played = (await db.execute(
        select(Gameweek.id).where(
            Gameweek.id.in_(scored_gws),
            (Gameweek.finished.is_(True)) | (Gameweek.is_current.is_(True)),
        )
    )).scalars().all()
    if played:
        caveats.append(
            f"GW{played} had already been played when these projections were built, "
            f"so season-total inputs contain the result being predicted (leakage). "
            f"For a clean read, project a future GW and score it after it finishes."
        )

    return {
        "model_version": model_version,
        "sample_size": n,
        "gameweeks_scored": scored_gws,
        "player_coverage": coverage,
        "mae": round(mae, 3),
        "rmse": round(rmse, 3),
        "bias": round(bias, 3),
        "spearman": round(_spearman(preds, actuals), 4),
        "mean_predicted": round(sum(preds) / n, 3),
        "mean_actual": round(sum(actuals) / n, 3),
        "by_position": by_position,
        "caveats": caveats,
        "interpretation": {
            "mae": "Average points wrong per player per GW. Lower is better.",
            "bias": "Positive = model over-projects; negative = under-projects. "
                    "Only meaningful on an unbiased sample — see caveats.",
            "spearman": "Rank correlation (-1..1). The metric that matters most: "
                        "FPL decisions are comparisons between players, not "
                        "absolute forecasts.",
        },
    }


def _rank(values: list[float]) -> list[float]:
    """Average ranks, handling ties."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _spearman(a: list[float], b: list[float]) -> float:
    """Spearman rank correlation via Pearson on ranks (tie-safe)."""
    n = len(a)
    if n < 2:
        return 0.0
    ra, rb = _rank(a), _rank(b)
    ma, mb = sum(ra) / n, sum(rb) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    da = math.sqrt(sum((x - ma) ** 2 for x in ra))
    dbv = math.sqrt(sum((y - mb) ** 2 for y in rb))
    if da == 0 or dbv == 0:
        return 0.0
    return num / (da * dbv)


def _i(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _f(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0
