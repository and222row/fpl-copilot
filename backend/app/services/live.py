"""
The live gameweek: your points as matches are played, and your mini-league
re-ranked by them.

What FPL publishes while a gameweek is in play, and what is added here:

- `/event/{gw}/live/` has each player's points so far. Bonus is missing from
  them until FPL confirms it, about an hour after full time. Until then it is
  worked out here from the match's BPS, the way FPL awards it.
- FPL makes automatic substitutions, and moves the armband to the vice-captain,
  only as matches finish. Those still to come are projected here from who has
  and hasn't played, keeping the formation legal, and reported as projections.

Everything is public FPL data, and nothing is stored. Live points and fixtures
are the same for every user, so they are kept in this process's memory for a
minute rather than in Redis: a matchday of polling would spend Redis's 10k
daily commands on its own. A squad is fixed once the deadline passes, so picks
are kept for ten minutes; FPL's own automatic substitutions show up in them
within that, and are projected here until then.

A manager's live squad is read straight from FPL rather than through
resolve_squad: this is what they actually fielded, not the squad advice is
built on, the same exception as feedback.fetch_actual_squad.
"""
import asyncio
import logging
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fpl import Gameweek, Player
from app.services.fpl_client import fetch_event_fixtures, fetch_event_picks, fetch_live_points
from app.services.fpl_sync import get_latest_started_gameweek
from app.services.leagues import _membership, _player_rows, _standings

logger = logging.getLogger("fpl_copilot.live")

LIVE_TTL_SECONDS = 60
PICKS_TTL_SECONDS = 600
# Managers re-ranked live in a league: the top of the table, plus you.
LIVE_LEAGUE_SAMPLE = 30

TO_PLAY, PLAYING, DONE = "to_play", "playing", "done"
# Fewest of each position (GKP, DEF, MID, FWD) an XI may have after substitutions.
MIN_IN_XI = {1: 1, 2: 3, 3: 2, 4: 1}
BONUS_FOR_RANK = {1: 3, 2: 2, 3: 1}


class LiveUnavailable(Exception):
    """No gameweek has started, or FPL has no squad for this manager in it."""


# ── A small in-memory cache ──────────────────────────────────────────────────

_MEMO: dict[str, tuple[float, Any]] = {}
MEMO_MAX = 2000


async def _memo(key: str, ttl: float, loader: Callable[[], Awaitable[Any]]) -> Any:
    now = time.monotonic()
    hit = _MEMO.get(key)
    if hit and hit[0] > now:
        return hit[1]
    value = await loader()
    if len(_MEMO) >= MEMO_MAX:
        for k in [k for k, (expires, _) in _MEMO.items() if expires <= now]:
            del _MEMO[k]
        while len(_MEMO) >= MEMO_MAX:
            _MEMO.pop(next(iter(_MEMO)))
    _MEMO[key] = (now + ttl, value)
    return value


def clear_memo() -> None:
    _MEMO.clear()


async def _live(gameweek: int) -> dict:
    return await _memo(f"live:{gameweek}", LIVE_TTL_SECONDS, lambda: fetch_live_points(gameweek))


async def _fixtures(gameweek: int) -> list[dict]:
    return await _memo(f"fixtures:{gameweek}", LIVE_TTL_SECONDS, lambda: fetch_event_fixtures(gameweek))


async def _picks(manager_id: int, gameweek: int) -> dict:
    return await _memo(f"picks:{manager_id}:{gameweek}", PICKS_TTL_SECONDS, lambda: fetch_event_picks(manager_id, gameweek))


# ── Players ──────────────────────────────────────────────────────────────────

def fixture_state(fixture: dict) -> str:
    # finished_provisional is full time; finished waits days for FPL's checks.
    if fixture.get("finished_provisional") or fixture.get("finished"):
        return DONE
    return PLAYING if fixture.get("started") else TO_PLAY


def bonus_from_bps(bps: list[tuple[int, int]]) -> dict[int, int]:
    """
    FPL's bonus: 3, 2 and 1 to the three highest BPS in a match. Tied players
    share the higher award and the next one is skipped, so a tie for first
    pays 3, 3, 1 and a tie for second pays 3, 2, 2.
    """
    out = {}
    for element, value in sorted(bps, key=lambda r: -r[1]):
        rank = 1 + sum(1 for _, v in bps if v > value)
        if rank > 3:
            break
        out[element] = BONUS_FOR_RANK[rank]
    return out


def provisional_bonus(fixtures: list[dict]) -> dict[int, int]:
    """Bonus earned on BPS in matches whose bonus FPL has not yet confirmed."""
    out: Counter = Counter()
    for f in fixtures:
        if fixture_state(f) == TO_PLAY:
            continue
        stats = {s["identifier"]: s for s in f.get("stats") or []}
        confirmed = stats.get("bonus") or {}
        if confirmed.get("a") or confirmed.get("h"):
            continue  # already in the players' live points
        bps = stats.get("bps") or {}
        rows = [(r["element"], r["value"]) for side in ("a", "h") for r in bps.get(side) or []]
        out.update(bonus_from_bps(rows))
    return dict(out)


@dataclass(frozen=True)
class PlayerLive:
    points: int  # FPL's live points, confirmed bonus included
    bonus: int  # provisional bonus, not yet in points
    minutes: int
    state: str  # TO_PLAY, PLAYING or DONE: across all the club's matches this gameweek


NOT_YET = PlayerLive(0, 0, 0, TO_PLAY)


def players_live(live: dict, fixtures: list[dict], team_of: dict[int, int]) -> dict[int, PlayerLive]:
    states: dict[int, list[str]] = {}
    for f in fixtures:
        for team in (f.get("team_h"), f.get("team_a")):
            states.setdefault(team, []).append(fixture_state(f))
    all_done = all(fixture_state(f) == DONE for f in fixtures)
    bonus = provisional_bonus(fixtures)

    def state(team: int | None) -> str:
        if team is None:  # not synced yet: only certain once everything is over
            return DONE if all_done else TO_PLAY
        mine = states.get(team)
        if not mine:
            return DONE  # a blank: no match this gameweek
        if PLAYING in mine:
            return PLAYING
        return TO_PLAY if TO_PLAY in mine else DONE

    out = {}
    for e in live.get("elements") or []:
        stats = e.get("stats") or {}
        out[e["id"]] = PlayerLive(
            points=int(stats.get("total_points") or 0),
            bonus=bonus.get(e["id"], 0),
            minutes=int(stats.get("minutes") or 0),
            state=state(team_of.get(e["id"])),
        )
    return out


# ── A team ───────────────────────────────────────────────────────────────────

@dataclass
class TeamLive:
    points: int  # after any transfer hit
    provisional_bonus: int
    players_left: int  # counting players with a match still to finish
    transfer_cost: int
    chip: str | None
    armband: int | None  # who the multiplier applies to now
    captain: int | None
    auto_subs: list[tuple[int, int]]  # (out, in) projected here
    rows: list[dict]


def _legal(xi: list[dict]) -> bool:
    counts = Counter(p["element_type"] for p in xi)
    return all(counts[pos] >= n for pos, n in MIN_IN_XI.items())


def team_live(picks: dict, players: dict[int, PlayerLive]) -> TeamLive:
    chip = picks.get("active_chip")
    ordered = sorted(picks.get("picks") or [], key=lambda p: p["position"])
    xi = [p for p in ordered if p["position"] <= 11]
    bench = [p for p in ordered if p["position"] > 11]

    def of(p: dict) -> PlayerLive:
        return players.get(p["element"], NOT_YET)

    def out_of_it(p: dict) -> bool:
        s = of(p)
        return s.state == DONE and s.minutes == 0

    counting = xi + bench if chip == "bboost" else list(xi)
    subs: list[tuple[int, int]] = []
    if chip != "bboost":
        # FPL's order: each starter who didn't play, in turn, takes the first
        # bench player who did, goalkeeper for goalkeeper, if the formation
        # stays legal. Bench players yet to play are passed over: whether they
        # will is unknown, so the projection is only as good as the matches so far.
        used: set[int] = set()
        for starter in xi:
            if not out_of_it(starter):
                continue
            for b in bench:
                if b["element"] in used or of(b).minutes == 0:
                    continue
                if (starter["element_type"] == 1) != (b["element_type"] == 1):
                    continue
                trial = [p for p in counting if p is not starter] + [b]
                if _legal(trial):
                    counting = trial
                    used.add(b["element"])
                    subs.append((starter["element"], b["element"]))
                    break

    captain = next((p for p in ordered if p.get("is_captain")), None)
    vice = next((p for p in ordered if p.get("is_vice_captain")), None)
    armband = captain
    if captain is not None and out_of_it(captain):
        # The vice takes it, unless they didn't play either; one yet to play holds it for now.
        armband = vice if vice is not None and not out_of_it(vice) else None
    counting_ids = {p["element"] for p in counting}
    if armband is not None and armband["element"] not in counting_ids:
        armband = None  # the vice didn't play either: nobody's points are doubled
    multiplier = 3 if chip == "3xc" else 2

    subbed_out = {o for o, _ in subs}
    subbed_in = {i for _, i in subs}
    total = bonus_total = left = 0
    rows = []
    for p in ordered:
        e = p["element"]
        s = of(p)
        mult = 0
        if e in counting_ids:
            mult = multiplier if armband is not None and e == armband["element"] else 1
        total += (s.points + s.bonus) * mult
        bonus_total += s.bonus * mult
        if mult and s.state != DONE:
            left += 1
        rows.append({
            "element": e,
            "slot": p["position"],
            "starting": (p["position"] <= 11 and e not in subbed_out) or e in subbed_in,
            "is_captain": bool(p.get("is_captain")),
            "is_vice_captain": bool(p.get("is_vice_captain")),
            "multiplier": mult,
            "points": s.points + s.bonus,
            "provisional_bonus": s.bonus,
            "minutes": s.minutes,
            "state": s.state,
            "subbed_in": e in subbed_in,
            "subbed_out": e in subbed_out,
        })

    cost = int((picks.get("entry_history") or {}).get("event_transfers_cost") or 0)
    return TeamLive(
        points=total - cost,
        provisional_bonus=bonus_total,
        players_left=left,
        transfer_cost=cost,
        chip=chip,
        armband=armband["element"] if armband else None,
        captain=captain["element"] if captain else None,
        auto_subs=subs,
        rows=rows,
    )


def total_before(picks: dict) -> int:
    """The manager's season total before this gameweek, from FPL's entry history."""
    h = picks.get("entry_history") or {}
    return int(h.get("total_points") or 0) - int(h.get("points") or 0) + int(h.get("event_transfers_cost") or 0)


# ── Views ────────────────────────────────────────────────────────────────────

async def _gameweek(db: AsyncSession) -> Gameweek:
    gw = await get_latest_started_gameweek(db)
    if gw is None:
        raise LiveUnavailable("No gameweek has started yet.")
    return gw


async def _world(db: AsyncSession, gameweek: int) -> tuple[dict[int, PlayerLive], list[dict]]:
    live, fixtures = await asyncio.gather(_live(gameweek), _fixtures(gameweek))
    team_of = dict((await db.execute(select(Player.id, Player.team_id))).all())
    return players_live(live, fixtures, team_of), fixtures


def _status(fixtures: list[dict]) -> dict:
    states = [fixture_state(f) for f in fixtures]
    upcoming = sorted(f["kickoff_time"] for f in fixtures if fixture_state(f) == TO_PLAY and f.get("kickoff_time"))
    return {
        "in_play": PLAYING in states,
        "finished": bool(states) and all(s == DONE for s in states),
        "matches_done": states.count(DONE),
        "matches_total": len(states),
        "next_kickoff": upcoming[0] if upcoming else None,
    }


async def live_view(db: AsyncSession, manager_id: int) -> dict:
    gw = await _gameweek(db)
    players, fixtures = await _world(db, gw.id)
    try:
        picks = await _picks(manager_id, gw.id)
    except httpx.HTTPStatusError as e:
        if e.response is not None and e.response.status_code == 404:
            raise LiveUnavailable("FPL has no squad for you this gameweek: the team was created after its deadline.")
        raise
    team = team_live(picks, players)
    info = await _player_rows(db, {r["element"] for r in team.rows}, gw.id)

    def name(pid: int | None) -> str | None:
        return info.get(pid, {}).get("name") if pid else None

    squad = [
        {
            **info.get(r["element"], {"player_id": r["element"], "name": f"#{r['element']}", "team": "", "position": "UNK", "price": 0, "xpts": 0}),
            **{k: v for k, v in r.items() if k != "element"},
            "you_own": False,
        }
        for r in team.rows
    ]
    return {
        "gameweek": {"id": gw.id, "name": gw.name, "average": gw.average_entry_score or None, "highest": gw.highest_score or None},
        **_status(fixtures),
        "points": team.points,
        "provisional_bonus": team.provisional_bonus,
        "transfer_cost": team.transfer_cost,
        "players_left": team.players_left,
        "chip": team.chip,
        "captain": name(team.captain),
        "armband": name(team.armband),
        "auto_subs": [{"out": name(o), "in": name(i)} for o, i in team.auto_subs],
        "total": total_before(picks) + team.points,
        "squad": squad,
    }


async def league_live(db: AsyncSession, manager_id: int, league_id: int) -> dict:
    membership = await _membership(manager_id, league_id)
    gw = await _gameweek(db)
    league, rows = await _standings(league_id, membership["rank"])
    ordered = sorted(rows, key=lambda r: r["rank_sort"])
    sample = ordered[:LIVE_LEAGUE_SAMPLE]
    you = next((r for r in ordered if r["entry"] == manager_id), None)
    members = sample + ([you] if you and you not in sample else [])

    players, fixtures = await _world(db, gw.id)
    semaphore = asyncio.Semaphore(4)

    async def picks_for(entry: int) -> dict | None:
        async with semaphore:
            try:
                return await _picks(entry, gw.id)
            except httpx.HTTPError:
                # Joined after the deadline (404), or FPL hiccuped: they keep
                # FPL's own figures rather than failing the table.
                logger.info("live picks unavailable", extra={"gameweek": gw.id})
                return None

    all_picks = await asyncio.gather(*(picks_for(r["entry"]) for r in members))
    teams = {r["entry"]: (team_live(p, players), total_before(p)) if p else None for r, p in zip(members, all_picks)}
    captains = {t[0].armband for t in teams.values() if t and t[0].armband}
    names = {pid: row["name"] for pid, row in (await _player_rows(db, captains, gw.id)).items()}

    table = []
    for r in members:
        t = teams[r["entry"]]
        team = t[0] if t else None
        table.append({
            "entry": r["entry"],
            "team_name": r["entry_name"],
            "manager_name": r["player_name"],
            "rank": r["rank"],
            "last_rank": r["last_rank"],
            "gameweek_points": team.points if team else r["event_total"],
            "total": t[1] + team.points if t else r["total"],
            "players_left": team.players_left if team else None,
            "captain": names.get(team.armband) if team else None,
            "chip": team.chip if team else None,
            "is_you": r["entry"] == manager_id,
            "in_sample": r in sample,
        })

    # Live ranks among the managers read: the top of the table. Someone below
    # it could overtake them, so a large league says how many were read.
    ranked = sorted((row for row in table if row["in_sample"]), key=lambda row: -row["total"])
    for row in ranked:
        row["live_rank"] = 1 + sum(1 for other in ranked if other["total"] > row["total"])
    for row in table:
        row.setdefault("live_rank", None)
    table.sort(key=lambda row: (row["live_rank"] is None, row["live_rank"] or 0, row["rank"]))

    me = next((row for row in table if row["is_you"]), None)
    above = [row for row in table if me and row["live_rank"] and me["live_rank"] and row["total"] > me["total"]]
    return {
        "league": {"id": league["id"], "name": league["name"], "size": membership["size"]},
        "gameweek": {"id": gw.id, "name": gw.name},
        **_status(fixtures),
        "managers_read": len(sample),
        "partial": (membership["size"] or 0) > len(sample),
        "your_live_rank": me["live_rank"] if me else None,
        "gap_to_leader": (ranked[0]["total"] - me["total"]) if me and ranked and me["live_rank"] else None,
        "gap_to_next": (min(row["total"] for row in above) - me["total"]) if above else None,
        "standings": [{k: v for k, v in row.items() if k != "in_sample"} for row in table],
    }
