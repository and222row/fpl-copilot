"""
Transfer trends: who the crowd is buying and selling this gameweek and whose
price is about to move, each set against the projections.

The crowd follows form and price rises; the model follows minutes, fixtures
and underlying numbers. Where they disagree is the useful part, so every
popular buy carries the best alternative in his position at the same price
or less, when it projects clearly more over the next five gameweeks, and
every popular sell says where the model ranks him.

Everything is already synced from FPL's bootstrap: transfers this gameweek,
ownership, and FPL's own price-change projections (`price_change_percent` is
progress toward a change; each projection is FPL's forecast of that progress
tonight and the next two nights, and 100 or more means a change).
"""
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fpl import Gameweek, Player, Team
from app.models.projections import Projection
from app.services.fpl_sync import get_next_open_gameweek
from app.services.leagues import POSITIONS, kit_url
from app.services.projection import MODEL_VERSION

SHOWN = 10
HORIZON = 5
# An alternative must beat the popular pick by this much over the horizon to be worth naming.
BETTER_BY = 1.0
NIGHTS = {0: "tonight", 1: "tomorrow", 2: "in 2 days"}


def price_move(percent: float, projections: list[dict] | None) -> dict | None:
    """When FPL expects this player's price to change, if within its forecast."""
    for p in sorted(projections or [], key=lambda p: p.get("offset", 0)):
        try:
            projected = float(p.get("projected_percent"))
        except (TypeError, ValueError):
            continue
        if abs(projected) >= 100:
            offset = int(p.get("offset", 0))
            return {
                "direction": "rise" if projected > 0 else "fall",
                "when": NIGHTS.get(offset, f"in {offset} days"),
                "offset": offset,
                # FPL signs it with the direction (-5 for a likely fall).
                "likelihood": abs(int(p["likelihood"])) if p.get("likelihood") is not None else None,
                "progress": round(percent, 1),
            }
    return None


async def trends(db: AsyncSession) -> dict:
    target = await get_next_open_gameweek(db)
    if target is None:
        return {"gameweek": None, "most_bought": [], "most_sold": [], "rising": [], "falling": []}
    gws = (await db.execute(
        select(Gameweek.id).where(Gameweek.id >= target.id).order_by(Gameweek.id).limit(HORIZON)
    )).scalars().all()
    next_gw = dict((await db.execute(
        select(Projection.player_id, Projection.xpts).where(
            Projection.gameweek_id == target.id, Projection.model_version == MODEL_VERSION)
    )).all())
    horizon = dict((await db.execute(
        select(Projection.player_id, func.sum(Projection.xpts)).where(
            Projection.gameweek_id.in_(gws), Projection.model_version == MODEL_VERSION,
        ).group_by(Projection.player_id)
    )).all())
    rows = (await db.execute(select(Player, Team.short_name, Team.code).join(Team, Team.id == Player.team_id))).all()

    # Rank within position by the horizon projection, for "the model rates him".
    by_position: dict[int, list[tuple[float, int]]] = {}
    for p, _, _ in rows:
        by_position.setdefault(p.position, []).append((float(horizon.get(p.id, 0.0)), p.id))
    rank = {}
    for pos, items in by_position.items():
        for i, (_, pid) in enumerate(sorted(items, key=lambda t: (-t[0], t[1])), start=1):
            rank[pid] = (i, len(items))

    def row(p: Player, short: str, code: int) -> dict:
        r, of = rank.get(p.id, (None, None))
        return {
            "player_id": p.id,
            "name": p.web_name,
            "team": short,
            "position": POSITIONS.get(p.position, "UNK"),
            "price": round(p.now_cost / 10, 1),
            "kit": kit_url(code, p.position),
            "ownership": p.selected_by_percent,
            "transfers_in": p.transfers_in_event,
            "transfers_out": p.transfers_out_event,
            "net": p.transfers_in_event - p.transfers_out_event,
            "status": p.status,
            "news": p.news or None,
            "xpts_next": round(float(next_gw.get(p.id, 0.0)), 2),
            "xpts_horizon": round(float(horizon.get(p.id, 0.0)), 2),
            "position_rank": r,
            "position_count": of,
            "price_move": price_move(p.price_change_percent, p.price_change_projections),
        }

    players = {p.id: (p, short, code) for p, short, code in rows}

    def alternative(p: Player) -> dict | None:
        """The best available player in his position for the same price or less, if clearly better."""
        mine = float(horizon.get(p.id, 0.0))
        best = max(
            (
                q for q, _, _ in players.values()
                if q.position == p.position and q.id != p.id and q.status == "a" and q.now_cost <= p.now_cost
            ),
            key=lambda q: float(horizon.get(q.id, 0.0)),
            default=None,
        )
        if best is None or float(horizon.get(best.id, 0.0)) - mine < BETTER_BY:
            return None
        return row(*players[best.id])

    def top(key, reverse=True) -> list[Player]:
        return sorted((p for p, _, _ in rows), key=key, reverse=reverse)[:SHOWN]

    most_bought = [{**row(*players[p.id]), "alternative": alternative(p)} for p in top(lambda p: p.transfers_in_event)]
    most_sold = [row(*players[p.id]) for p in top(lambda p: p.transfers_out_event)]
    moving = [row(p, s, c) for p, s, c in rows]
    rising = sorted((r for r in moving if r["price_move"] and r["price_move"]["direction"] == "rise"),
                    key=lambda r: (r["price_move"]["offset"], -r["price_move"]["progress"]))[:SHOWN]
    falling = sorted((r for r in moving if r["price_move"] and r["price_move"]["direction"] == "fall"),
                     key=lambda r: (r["price_move"]["offset"], r["price_move"]["progress"]))[:SHOWN]
    return {
        "gameweek": {"id": target.id, "name": target.name},
        "horizon": len(gws),
        "most_bought": most_bought,
        "most_sold": most_sold,
        "rising": rising,
        "falling": falling,
    }
