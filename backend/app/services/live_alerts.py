"""
Pushes while matches are on: your players' goals, assists, penalty saves and
misses, own goals and red cards as they happen, and at full time what the
match earned you.

An in-process loop (app/scheduler.py) calls tick() every minute while a match
window is open and every five minutes otherwise. Whether one is open is read
from the fixtures the refresh syncs, so FPL is only called while matches are
on, and then for the live data the live screen shares (services/live.py) and
each subscriber's picks, kept for ten minutes.

Nothing is remembered between ticks. Every event has a key, such as the
second goal by one player in one match, and push.py records each key it sends
and refuses it again, so a restart mid-match repeats nothing. Only matches
inside their window count, so a server that starts on Monday does not send
Saturday's goals.
"""
import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.accounts import FplAccount
from app.models.fpl import Fixture, Player, Team, utcnow
from app.models.notifications import Device, PushDelivery
from app.services import live, push
from app.services.entitlements import get_entitlement

logger = logging.getLogger("fpl_copilot.live_alerts")

POLL_SECONDS = 60
IDLE_SECONDS = 300
# From kick-off until FPL has confirmed the bonus, about an hour after full time.
WINDOW = timedelta(hours=3, minutes=30)
KIND = "live"

# FPL stat -> how the push names it.
EVENTS = {
    "goals_scored": "Goal",
    "assists": "Assist",
    "penalties_saved": "Penalty saved",
    "penalties_missed": "Penalty missed",
    "own_goals": "Own goal",
    "red_cards": "Red card",
}


@dataclass(frozen=True)
class LiveEvent:
    key: str
    title: str
    body: str


def _kickoff(f: dict) -> datetime | None:
    k = f.get("kickoff_time")
    return datetime.fromisoformat(k.replace("Z", "+00:00")) if k else None


def _score(f: dict, short: dict[int, str]) -> str:
    h, a = f.get("team_h_score"), f.get("team_a_score")
    home, away = short.get(f["team_h"], "?"), short.get(f["team_a"], "?")
    return f"{home} {h}-{a} {away}" if h is not None and a is not None else f"{home} v {away}"


def _signed(points: int) -> str:
    return f"+{points}" if points >= 0 else f"−{-points}"


def events_for(
    picks: dict,
    explain: dict[int, list[dict]],
    fixtures: dict[int, dict],
    bonus: dict[int, dict[int, int]],
    names: dict[int, str],
    team_of: dict[int, int],
    short: dict[int, str],
    gameweek: int,
) -> list[LiveEvent]:
    """
    What one manager should hear about the matches in `fixtures`: an event per
    goal, assist and the like by a player in their team, and one full-time
    summary per finished match they have players in. `bonus` is the
    provisional bonus by match, empty for matches FPL has confirmed.
    """
    chip = picks.get("active_chip")
    team = [p for p in picks.get("picks") or [] if p["position"] <= 11 or chip == "bboost"]
    armband = 3 if chip == "3xc" else 2

    out: list[LiveEvent] = []
    for p in team:
        e = p["element"]
        mult = armband if p.get("is_captain") else 1
        for appearance in explain.get(e, []):
            f = fixtures.get(appearance.get("fixture"))
            if f is None:
                continue
            for stat in appearance.get("stats") or []:
                label = EVENTS.get(stat.get("identifier"))
                value = int(stat.get("value") or 0)
                if not label or value <= 0:
                    continue
                each = int(stat.get("points") or 0) // value * mult
                for n in range(1, value + 1):
                    out.append(LiveEvent(
                        key=f"{gameweek}:{f['id']}:{e}:{stat['identifier']}:{n}",
                        title=f"{label}: {names.get(e, 'your player')}",
                        body=f"{_score(f, short)} · {_signed(each)} for you" + (" (captain)" if mult > 1 else ""),
                    ))

    for f in fixtures.values():
        if not (f.get("finished_provisional") or f.get("finished")):
            continue
        clubs = {f["team_h"], f["team_a"]}
        mine = [p for p in team if team_of.get(p["element"]) in clubs]
        if not mine:
            continue
        parts, provisional = [], 0
        for p in mine:
            e = p["element"]
            mult = armband if p.get("is_captain") else 1
            stats = [s for a in explain.get(e, []) if a.get("fixture") == f["id"] for s in a.get("stats") or []]
            played = any(s.get("identifier") == "minutes" and s.get("value") for s in stats)
            if not played:
                parts.append(f"{names.get(e, '?')} didn't play")
                continue
            extra = bonus.get(f["id"], {}).get(e, 0)
            provisional += extra
            points = (sum(int(s.get("points") or 0) for s in stats) + extra) * mult
            shown = str(points) if points >= 0 else f"−{-points}"
            parts.append(f"{names.get(e, '?')} {shown}" + (" (C)" if mult > 1 else ""))
        body = ", ".join(parts) + (" · bonus not yet confirmed" if provisional else "")
        out.append(LiveEvent(key=f"{gameweek}:{f['id']}:ft", title=f"Full time: {_score(f, short)}", body=body))
    return out


async def window_gameweek(db: AsyncSession, now: datetime) -> int | None:
    """The gameweek with a match between kick-off and confirmed bonus, if any."""
    return await db.scalar(
        select(Fixture.gameweek_id).where(
            Fixture.kickoff_time <= now,
            Fixture.kickoff_time > now - WINDOW,
            Fixture.gameweek_id.is_not(None),
        ).limit(1)
    )


async def tick(db: AsyncSession, now: datetime | None = None) -> dict:
    """Send whatever has happened since the last tick. Returns what it did."""
    now = now or utcnow()
    gameweek = await window_gameweek(db, now)
    if gameweek is None:
        return {"active": False}

    data, all_fixtures = await asyncio.gather(live._live(gameweek), live._fixtures(gameweek))
    fixtures = {
        f["id"]: f for f in all_fixtures
        if f.get("started") and (k := _kickoff(f)) is not None and k > now - WINDOW
    }
    if not fixtures:
        return {"active": True, "matches": 0, "sent": 0}

    explain = {e["id"]: e.get("explain") or [] for e in data.get("elements") or []}
    bonus = {fid: live.provisional_bonus([f]) for fid, f in fixtures.items()}
    names = dict((await db.execute(select(Player.id, Player.web_name))).all())
    team_of = dict((await db.execute(select(Player.id, Player.team_id))).all())
    short = dict((await db.execute(select(Team.id, Team.short_name))).all())

    devices: dict[uuid.UUID, list[str]] = {}
    for user_id, token in (await db.execute(select(Device.user_id, Device.token))).all():
        devices.setdefault(user_id, []).append(token)
    accounts = (await db.execute(select(FplAccount.user_id, FplAccount.fpl_entry_id))).all()

    queued: list[tuple[uuid.UUID, push.Message]] = []
    claims: list[PushDelivery] = []
    for user_id, entry in accounts:
        if not devices.get(user_id) or not await push._wants(db, user_id, KIND):
            continue
        if not (await get_entitlement(db, user_id)).premium:
            continue
        try:
            picks = await live._picks(entry, gameweek)
        except httpx.HTTPError:
            continue  # no squad this gameweek, or FPL hiccuped: next tick
        for event in events_for(picks, explain, fixtures, bonus, names, team_of, short, gameweek):
            row = await push._claim(db, user_id, KIND, event.key)
            if row is None:
                continue
            claims.append(row)
            queued.extend(
                (user_id, push.Message(t, event.title, event.body, {"type": "live"})) for t in devices[user_id]
            )

    result = await push._deliver(db, queued, claims)
    await db.commit()
    return {"active": True, "matches": len(fixtures), **result}
