"""
The article behind a squad warning or alert: what happened to a player, what
it means for this manager, and who could replace him.

FPL publishes one line of news per player, so there is no article to fetch;
this writes one from what we already hold. The status history comes from the
availability events change detection records; "what it means for you" from
the squad and the advice stored for this team (services/advice.py); the
replacements from the projections. Nothing is fetched from FPL beyond the
squad lookup every advice screen makes.
"""
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.feedback import AdviceCache
from app.models.fpl import Gameweek, Player, Team
from app.models.news import Alert, AvailabilityEvent
from app.models.projections import Projection
from app.services.fpl_sync import get_latest_started_gameweek, get_next_open_gameweek
from app.services.leagues import _fixtures, kit_url
from app.services.player_view import POSITION_NAMES, STATUS_NAMES, player_photo
from app.services.projection import MODEL_VERSION
from app.services.squad_state import resolve_squad

HISTORY_SHOWN = 8
REPLACEMENTS_SHOWN = 3
HORIZON = 5
FIXTURES_SHOWN = 3

HEADLINE = {
    "i": "{name} is injured",
    "d": "{name} is a doubt",
    "s": "{name} is suspended",
    "u": "{name} is unavailable",
    "n": "{name} is not in the squad",
    "a": "{name} is available",
}


class StoryNotFound(Exception):
    pass


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


async def player_story(db: AsyncSession, manager_id: int, player_id: int, alert_id: int | None = None) -> dict:
    row = (await db.execute(
        select(Player, Team).join(Team, Team.id == Player.team_id).where(Player.id == player_id)
    )).first()
    if row is None:
        raise StoryNotFound("No such player")
    p, team = row

    alert = None
    if alert_id is not None:
        alert = await db.scalar(select(Alert).where(Alert.id == alert_id, Alert.fpl_entry_id == manager_id))
        if alert is None:
            raise StoryNotFound("No such alert for this team")

    events = (await db.execute(
        select(AvailabilityEvent).where(AvailabilityEvent.player_id == player_id)
        .order_by(AvailabilityEvent.detected_at.desc()).limit(HISTORY_SHOWN)
    )).scalars().all()

    target = await get_next_open_gameweek(db)
    started = await get_latest_started_gameweek(db)
    gws = (await db.execute(
        select(Gameweek.id).where(Gameweek.id >= target.id).order_by(Gameweek.id).limit(HORIZON)
    )).scalars().all() if target else []
    xpts = dict((await db.execute(
        select(Projection.player_id, func.sum(Projection.xpts)).where(
            Projection.gameweek_id.in_(gws), Projection.model_version == MODEL_VERSION,
        ).group_by(Projection.player_id)
    )).all()) if gws else {}
    next_xpts = await db.scalar(select(Projection.xpts).where(
        Projection.player_id == player_id, Projection.gameweek_id == target.id, Projection.model_version == MODEL_VERSION,
    )) if target else None

    # What it means for you: the squad, and the advice already worked out.
    owned: set[int] = set()
    bank = 0
    if target and started:
        try:
            resolved = await resolve_squad(db, manager_id, target.id, started.id)
            owned, bank = set(resolved.player_ids), resolved.bank
        except Exception:
            pass
    advice = await db.get(AdviceCache, manager_id)
    body = advice.body if advice and target and advice.gameweek_id == target.id else None
    starting = captain = False
    plan_move = None
    if body:
        starting = any(x["player_id"] == player_id for x in body["lineup"]["starting"])
        captain = ((body.get("captain") or {}).get("pick") or {}).get("player_id") == player_id
        plan = (body.get("transfer") or {}).get("plan") or {}
        for out, inn in zip(plan.get("out") or [], plan.get("in") or []):
            if out.get("player_id") == player_id:
                plan_move = {"out": out.get("name"), "in": inn.get("name"), "in_player_id": inn.get("player_id")}

    # Replacements: his position, fit to play, affordable, not already yours.
    budget = p.now_cost + (bank if player_id in owned else 0)
    candidates = (await db.execute(
        select(Player, Team.short_name, Team.code).join(Team, Team.id == Player.team_id).where(
            Player.position == p.position, Player.status == "a", Player.id != player_id,
            Player.now_cost <= budget, Player.id.notin_(owned or {-1}),
        )
    )).all()
    replacements = sorted(candidates, key=lambda c: -float(xpts.get(c[0].id, 0.0)))[:REPLACEMENTS_SHOWN]

    upcoming = []
    for gw in gws[:FIXTURES_SHOWN]:
        upcoming.append({"gameweek": gw, "opponents": (await _fixtures(db, {team.id}, gw)).get(team.id, [])})

    name = p.web_name
    headline = alert.title if alert else HEADLINE.get(p.status, "{name}").format(name=name)
    # Dated by the latest status news, not a price move that came after it.
    status_events = [e for e in events if not e.event_type.startswith("price")]
    published = alert.created_at if alert else (status_events[0].detected_at if status_events else p.updated_at)
    return {
        "player": {
            "id": p.id, "name": name, "full_name": f"{p.first_name} {p.second_name}".strip(),
            "team": team.short_name, "team_name": team.name, "position": POSITION_NAMES.get(p.position, "UNK"),
            "price": round(p.now_cost / 10, 1), "photo": player_photo(p.code, large=True),
            "kit": kit_url(team.code, p.position), "status": p.status,
            "status_label": STATUS_NAMES.get(p.status, p.status), "news": p.news or None,
            "chance": p.chance_of_playing_next_round,
        },
        "headline": headline,
        "summary": (alert.body if alert else None) or p.news or STATUS_NAMES.get(p.status, ""),
        "severity": alert.severity if alert else ("critical" if p.status in ("i", "s", "u", "n") else "warning"),
        "published_at": _iso(published),
        "history": [
            {"at": _iso(e.detected_at), "event_type": e.event_type, "news": e.news_text or None,
             "status": STATUS_NAMES.get(e.status_after or "", None), "chance": e.availability_after}
            for e in events
        ],
        "you": {
            "owned": player_id in owned,
            "starting": starting,
            "captain": captain,
            "projected_next": round(float(next_xpts), 1) if next_xpts is not None else None,
            "gameweek": target.name if target else None,
            "plan": plan_move,
        },
        "replacements": [
            {"player_id": c.id, "name": c.web_name, "team": short, "price": round(c.now_cost / 10, 1),
             "photo": player_photo(c.code, large=True), "kit": kit_url(code, c.position),
             "xpts_horizon": round(float(xpts.get(c.id, 0.0)), 1)}
            for c, short, code in replacements
        ],
        "horizon": len(gws),
        "fixtures": upcoming,
    }
