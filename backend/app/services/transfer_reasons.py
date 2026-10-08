"""
Plain-language reasons for a recommended transfer, read off the model.

Every reason compares two numbers the projection already holds for the
players involved, so each claim can be checked against the player screens.
Nothing here decides a transfer; the optimiser already has.
"""
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fpl import Player
from app.models.projections import Projection
from app.services.projection import MODEL_VERSION

# Differences below these are noise at the precision the model has.
MINUTES_GAP = 10.0
FDR_GAP = 0.4
COMPONENT_GAP = 0.75
PRICE_GAP = 0.5

UNAVAILABLE = {"i": "injured", "s": "suspended", "u": "unavailable", "n": "not in the squad"}


@dataclass
class _Profile:
    name: str
    status: str
    news: str
    gameweeks: int
    avg_minutes: float
    avg_fdr: float
    attack: float
    defence: float


async def _profiles(db: AsyncSession, player_ids: set[int], gameweek_ids: list[int]) -> dict[int, _Profile]:
    players = {
        p.id: p for p in (await db.execute(select(Player).where(Player.id.in_(player_ids)))).scalars()
    }
    rows = (await db.execute(
        select(Projection).where(
            Projection.player_id.in_(player_ids),
            Projection.gameweek_id.in_(gameweek_ids),
            Projection.model_version == MODEL_VERSION,
        )
    )).scalars().all()

    by_player: dict[int, list[Projection]] = {}
    for r in rows:
        by_player.setdefault(r.player_id, []).append(r)

    profiles = {}
    for pid, p in players.items():
        rs = by_player.get(pid, [])
        n = len(rs) or 1
        profiles[pid] = _Profile(
            name=p.web_name,
            status=p.status,
            news=p.news or "",
            gameweeks=len(rs),
            avg_minutes=sum(r.expected_minutes for r in rs) / n,
            avg_fdr=sum(r.custom_fdr for r in rs) / n,
            attack=sum(r.xpts_goals + r.xpts_assists + r.xpts_penalties for r in rs),
            defence=sum(
                r.xpts_clean_sheet + r.xpts_defensive_contribution + r.xpts_saves + r.xpts_goals_conceded
                for r in rs
            ),
        )
    return profiles


def _reasons(out: _Profile, inc: _Profile, out_price: float, in_price: float) -> list[str]:
    reasons = []
    if out.status in UNAVAILABLE:
        reasons.append(f"{out.name} is {UNAVAILABLE[out.status]}" + (f": {out.news}" if out.news else ""))
    elif out.status == "d":
        reasons.append(f"{out.name} is a doubt" + (f": {out.news}" if out.news else ""))

    if inc.avg_minutes - out.avg_minutes >= MINUTES_GAP:
        reasons.append(
            f"More secure minutes: {inc.avg_minutes:.0f} expected per gameweek vs {out.avg_minutes:.0f}"
        )
    if inc.attack - out.attack >= COMPONENT_GAP:
        reasons.append(
            f"Higher attacking projection: +{inc.attack - out.attack:.1f} pts from goals and assists"
        )
    if inc.defence - out.defence >= COMPONENT_GAP:
        reasons.append(
            f"Stronger defensive projection: +{inc.defence - out.defence:.1f} pts from clean sheets and defending"
        )
    if out.avg_fdr - inc.avg_fdr >= FDR_GAP:
        reasons.append(
            f"Easier fixtures: average difficulty {inc.avg_fdr:.1f} vs {out.avg_fdr:.1f} (1 is easiest)"
        )
    if out_price - in_price >= PRICE_GAP:
        reasons.append(f"Frees £{out_price - in_price:.1f}m")
    return reasons


def _pair_by_position(outs: list[dict], ins: list[dict]) -> list[tuple[dict, dict]]:
    """FPL transfers are like-for-like by position, so pair them that way."""
    remaining = list(ins)
    pairs = []
    for o in outs:
        match = next((i for i in remaining if i["position"] == o["position"]), None)
        if match is None and remaining:
            match = remaining[0]
        if match is None:
            continue
        remaining.remove(match)
        pairs.append((o, match))
    return pairs


async def explain_plans(db: AsyncSession, plans: list[dict], gameweek_ids: list[int]) -> None:
    """Add a `moves` list, with reasons, to each serialised transfer plan in place."""
    ids = {p["player_id"] for plan in plans for p in plan["out"] + plan["in"]}
    if not ids:
        for plan in plans:
            plan["moves"] = []
        return
    profiles = await _profiles(db, ids, gameweek_ids)

    for plan in plans:
        moves = []
        for o, i in _pair_by_position(plan["out"], plan["in"]):
            out_p, in_p = profiles.get(o["player_id"]), profiles.get(i["player_id"])
            gain = round(i["horizon_xpts"] - o["horizon_xpts"], 2)
            reasons = _reasons(out_p, in_p, o["price"], i["price"]) if out_p and in_p else []
            if not reasons:
                reasons = [f"Projected {gain:+.1f} pts over the horizon"]
            moves.append({"out": o, "in": i, "xpts_gain": gain, "reasons": reasons})
        plan["moves"] = moves
