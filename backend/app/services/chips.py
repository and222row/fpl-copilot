"""
Chip timing.

The framing matters more than the arithmetic. "Is this a good week to Triple
Captain?" is the wrong question — a twelve-point captain is a poor use in GW5
and an obvious one in GW18, and the number is identical. FPL issues each chip
with an expiry (two sets, one per half of the season, unused ones simply lost),
which makes this a *bounded optimal-stopping* problem: take the current
opportunity, or gamble that a better one arrives before the window shuts.

So every recommendation here is built from three quantities, not one:

    value now        what the chip is worth this gameweek, for this squad
    best in view     the best it reaches inside the projection horizon
    weeks remaining  how many chances are left before it expires

Layered by how much they can be trusted:

    fixture shape    pure counting. Doubles and blanks are facts, and this is
                     the only part that cannot be wrong the way a projection
                     can. It is also the part you cannot work out by eye.
    availability     pure fact, from FPL's own record of what you have played.
    valuation        the projection model, with all of its uncertainty.
    the verdict      a heuristic on top of the valuation, so the least
                     trustworthy thing here.

That ordering is deliberate and is surfaced in the output, because chip advice
*compounds* model error: a transfer risks one projection being wrong, a
wildcard stakes fifteen at once, and a triple captain triples the error on one.
"""
import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fpl import Fixture, Gameweek, Player, Team
from app.models.projections import ChipWindow, Projection
from app.services.dream_team import build_dream_team
from app.services.projection import MODEL_VERSION
from app.services.fpl_client import fetch_manager_history
from app.services.fpl_sync import get_latest_started_gameweek, get_next_open_gameweek
from app.services.lineup import SquadEntry, best_starting_xi
from app.services.squad_state import resolve_squad

logger = logging.getLogger("fpl_copilot")

# FPL's internal names, and what a human calls them.
CHIP_LABELS = {
    "wildcard": "Wildcard",
    "freehit": "Free Hit",
    "bboost": "Bench Boost",
    "3xc": "Triple Captain",
}

# A chip is worth playing when it clears its ordinary week by this much. Set
# from what the chips are actually for: a bench boost in a normal week returns
# a bench, in a double gameweek it returns a second bench, so 1.8x is roughly
# "something unusual is happening". Deliberately not tuned to backtests, which
# do not exist yet — these are stated assumptions, not fitted parameters.
STRONG_MULTIPLE = 1.8
DECENT_MULTIPLE = 1.4

# Below this the chip is not worth a slot in a normal week whatever the ratio.
MIN_ABSOLUTE_GAIN = {
    "bboost": 12.0,      # a bench worth less than this is just a bench
    "3xc": 10.0,         # the extra multiple, not the captain's total
    "freehit": 15.0,     # one week of squad, so it has to be a big week
    "wildcard": 8.0,     # per gameweek, and it persists — see value_wildcard
}

# Inside this many gameweeks of expiry, holding out for better stops being a
# strategy and starts being a way to lose the chip.
URGENT_WEEKS = 3


@dataclass
class ChipAdvice:
    name: str
    label: str
    available: bool
    used_in_gameweek: int | None
    window_start: int
    window_end: int
    weeks_remaining: int
    value_now: float | None = None
    best_value: float | None = None
    best_gameweek: int | None = None
    baseline: float | None = None
    verdict: str = "unknown"
    confidence: str = "low"
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "label": self.label,
            "available": self.available,
            "used_in_gameweek": self.used_in_gameweek,
            "window": {"start": self.window_start, "end": self.window_end},
            "weeks_remaining": self.weeks_remaining,
            "value_now": None if self.value_now is None else round(self.value_now, 1),
            "best_value": None if self.best_value is None else round(self.best_value, 1),
            "best_gameweek": self.best_gameweek,
            "baseline": None if self.baseline is None else round(self.baseline, 1),
            "verdict": self.verdict,
            "confidence": self.confidence,
            "reasons": self.reasons,
        }


# ── Layer 1: fixture shape. Counting, not modelling. ─────────────────────────

async def fixture_shape(db: AsyncSession, from_gameweek: int = 1) -> dict:
    """
    How many fixtures each team has in each gameweek.

    A team with two is a double gameweek, with none a blank. Early in a season
    neither exists — the published schedule gives everyone exactly one — and
    they only appear once fixtures are postponed for cup rounds and
    rescheduled. That is precisely why this is worth watching automatically:
    the information arrives without announcement, months after anyone stopped
    looking for it.
    """
    rows = (await db.execute(
        select(Fixture.gameweek_id, Fixture.team_h, Fixture.team_a)
        .where(Fixture.gameweek_id.is_not(None), Fixture.gameweek_id >= from_gameweek)
    )).all()

    counts: dict[int, dict[int, int]] = {}
    for gw, home, away in rows:
        per_team = counts.setdefault(gw, {})
        per_team[home] = per_team.get(home, 0) + 1
        per_team[away] = per_team.get(away, 0) + 1

    teams = {t.id: t.short_name for t in (await db.execute(select(Team))).scalars().all()}
    all_team_ids = set(teams)

    doubles: dict[int, list[str]] = {}
    blanks: dict[int, list[str]] = {}
    for gw, per_team in counts.items():
        d = [teams.get(t, str(t)) for t, n in per_team.items() if n > 1]
        b = [teams.get(t, str(t)) for t in all_team_ids - set(per_team)]
        if d:
            doubles[gw] = sorted(d)
        if b:
            blanks[gw] = sorted(b)

    return {
        "doubles": doubles,
        "blanks": blanks,
        "gameweeks_scheduled": len(counts),
        "note": (
            "No doubles or blanks are scheduled. They appear later in the "
            "season, when postponed fixtures are rearranged."
            if not doubles and not blanks else None
        ),
    }


async def squad_fixture_counts(
    db: AsyncSession, player_ids: list[int], gameweek: int
) -> dict[str, int]:
    """How many of a squad play once, twice, or not at all in a gameweek."""
    if not player_ids:
        return {"playing": 0, "doubling": 0, "blank": 0}

    team_of = dict((await db.execute(
        select(Player.id, Player.team_id).where(Player.id.in_(player_ids))
    )).all())

    rows = (await db.execute(
        select(Fixture.team_h, Fixture.team_a).where(Fixture.gameweek_id == gameweek)
    )).all()
    per_team: dict[int, int] = {}
    for home, away in rows:
        per_team[home] = per_team.get(home, 0) + 1
        per_team[away] = per_team.get(away, 0) + 1

    out = {"playing": 0, "doubling": 0, "blank": 0}
    for pid in player_ids:
        n = per_team.get(team_of.get(pid), 0)
        if n == 0:
            out["blank"] += 1
        elif n > 1:
            out["doubling"] += 1
            out["playing"] += 1
        else:
            out["playing"] += 1
    return out


# ── Layer 2: availability. Also fact. ────────────────────────────────────────

async def chip_state(db: AsyncSession, manager_id: int) -> list[dict]:
    """
    Which chips remain, and when each expires.

    Windows come from FPL's bootstrap and usage from the manager's own history.
    Recommending a chip already spent is worse than saying nothing, so a failure
    to read the history is reported rather than assumed away.
    """
    windows = (await db.execute(
        select(ChipWindow).order_by(ChipWindow.start_event, ChipWindow.name)
    )).scalars().all()

    used: list[dict] = []
    history_ok = True
    try:
        history = await fetch_manager_history(manager_id)
        used = history.get("chips") or []
    except Exception:
        history_ok = False
        logger.warning("could not read chip history", extra={"manager_id": manager_id})

    used_by_window: dict[tuple[str, int], int] = {}
    for entry in used:
        name, event = entry.get("name"), entry.get("event")
        if name is None or event is None:
            continue
        for w in windows:
            if w.name == name and w.start_event <= event <= w.stop_event:
                used_by_window[(w.name, w.start_event)] = event

    return [
        {
            "name": w.name,
            "label": CHIP_LABELS.get(w.name, w.name),
            "start_event": w.start_event,
            "stop_event": w.stop_event,
            "used_in_gameweek": used_by_window.get((w.name, w.start_event)),
            "history_available": history_ok,
        }
        for w in windows
    ]


# ── Layer 3: valuation. The model, with all its uncertainty. ─────────────────

async def _squad_entries(
    db: AsyncSession, player_ids: list[int], gameweek: int
) -> list[SquadEntry]:
    """The squad paired with its projections for one gameweek."""
    if not player_ids:
        return []
    rows = (await db.execute(
        select(Player, Team.short_name, Projection)
        .join(Team, Team.id == Player.team_id)
        .outerjoin(
            Projection,
            (Projection.player_id == Player.id)
            & (Projection.gameweek_id == gameweek)
            & (Projection.model_version == MODEL_VERSION),
        )
        .where(Player.id.in_(player_ids))
    )).all()
    return [SquadEntry(player=p, projection=proj, team_short=short)
            for p, short, proj in rows]


def _has_projections(entries: list[SquadEntry]) -> bool:
    """A squad with no projections yields zeros, which would read as real."""
    return sum(1 for e in entries if e.projection is not None) >= 11


def _my_xi_with_captain(entries: list[SquadEntry]) -> float:
    """
    The manager's XI scored the same way the solver scores its own.

    `build_dream_team` reports `xi_pts + captain.gw_xpts`, so comparing raw
    `starting_xpts` against it subtracts a captain from one side only and
    inflates every gap by roughly a premium's score — measured here at 13.8
    pts/GW for a wildcard whose true gap was 4.1.
    """
    xi = best_starting_xi(entries)
    captain = max((e.xpts for e in xi.starting), default=0.0)
    return xi.starting_xpts + captain


async def value_bench_boost(
    db: AsyncSession, player_ids: list[int], gameweek: int
) -> float | None:
    """
    What the bench would contribute — exactly what the chip pays out.

    `best_starting_xi` already separates the four who miss out, so this is the
    figure it computes rather than a reconstruction of it.
    """
    entries = await _squad_entries(db, player_ids, gameweek)
    if not _has_projections(entries):
        return None
    return best_starting_xi(entries).bench_xpts


async def value_triple_captain(
    db: AsyncSession, player_ids: list[int], gameweek: int
) -> float | None:
    """
    The *extra* multiple, not the captain's total.

    The chip turns a double into a treble, so what it buys is one further copy
    of that player's score. Comparing the doubled figure across weeks would
    overstate every one of them equally and mislead about the gap.

    Taken from the starting XI, since a captain must be in it.
    """
    entries = await _squad_entries(db, player_ids, gameweek)
    if not _has_projections(entries):
        return None
    xi = best_starting_xi(entries)
    return max((e.xpts for e in xi.starting), default=None)


async def _best_possible_xi(
    db: AsyncSession, gameweek: int, budget: float
) -> float | None:
    try:
        best = await build_dream_team(
            db,
            budget=int(round(budget * 10)),
            horizon=1,
            start_gw=gameweek,
            time_limit=8.0,
        )
        return best.get("projected_next_gw")
    except Exception:
        logger.debug("dream team solve failed for chip valuation", exc_info=True)
        return None


async def value_free_hit(
    db: AsyncSession, player_ids: list[int], gameweek: int, budget: float
) -> float | None:
    """
    One week of any squad, minus the week you would have had.

    Solved at the manager's own budget: a free hit grants a different squad,
    not more money, so comparing against an unconstrained ideal would overstate
    it.
    """
    entries = await _squad_entries(db, player_ids, gameweek)
    if not _has_projections(entries):
        return None
    mine = _my_xi_with_captain(entries)
    best = await _best_possible_xi(db, gameweek, budget)
    return None if best is None else max(0.0, best - mine)


async def value_wildcard(
    db: AsyncSession, player_ids: list[int], gameweek: int,
    budget: float, horizon: int = 5,
) -> float | None:
    """
    Per-gameweek gap between the squad held and the best affordable one,
    where "best" is chosen for a run of gameweeks rather than for one.

    The horizon is the whole difference between this and a free hit. Solving at
    horizon=1 picks the squad that maximises a single week — a squad nobody
    would keep — and valuing a permanent chip that way overstates it roughly
    fourfold. Measured here: 15.9 pts/GW at horizon=1 against 4.1 at horizon=5.

    Reported per gameweek rather than summed, because a wildcard persists and
    the honest horizon is "the rest of the season", which the projections do
    not reach. A per-gameweek figure stays meaningful whatever horizon the
    reader has in mind, where a total silently depends on one this function
    had to invent.

    The number still flatters the chip, and `advise` says so: the optimal squad
    is chosen using the same projections that scored the current one, so part
    of any gap is the model preferring its own noise rather than real edge.
    """
    entries = await _squad_entries(db, player_ids, gameweek)
    if not _has_projections(entries):
        return None
    mine = _my_xi_with_captain(entries)

    try:
        best = await build_dream_team(
            db,
            budget=int(round(budget * 10)),
            horizon=horizon,
            start_gw=gameweek,
            time_limit=8.0,
        )
    except Exception:
        logger.debug("wildcard solve failed", exc_info=True)
        return None
    return max(0.0, best.get("projected_next_gw", 0.0) - mine)


# ── Layer 4: the verdict. A heuristic, and labelled as one. ──────────────────

def decide(
    name: str,
    value_now: float | None,
    best_value: float | None,
    best_gameweek: int | None,
    baseline: float | None,
    weeks_remaining: int,
    has_double: bool,
) -> tuple[str, str, list[str]]:
    """
    Turn the numbers into a verdict, a confidence, and the reasoning.

    The rule is deliberately simple and stated rather than fitted: there is no
    backtest behind it, and a more elaborate rule would only disguise that.
    """
    reasons: list[str] = []

    if value_now is None:
        return "unknown", "none", ["No projection available for this gameweek."]

    floor = MIN_ABSOLUTE_GAIN.get(name, 0.0)
    ratio = (value_now / baseline) if baseline else None

    if weeks_remaining <= 0:
        return "expired", "high", ["The window for this chip has closed."]

    # Running out of gameweeks turns holding into losing.
    if weeks_remaining <= URGENT_WEEKS:
        reasons.append(
            f"Only {weeks_remaining} gameweek{'s' if weeks_remaining != 1 else ''} "
            f"left before it expires — an unused chip scores nothing."
        )
        if best_gameweek is not None and best_value and best_value > value_now * 1.1:
            return "use_soon", "medium", reasons + [
                f"GW{best_gameweek} looks better ({best_value:.1f} vs {value_now:.1f}); "
                f"wait for it, but do not let the window close."
            ]
        return "use_now", "medium", reasons + [
            f"Worth about {value_now:.1f} pts now, and time has run out to do better."
        ]

    if has_double:
        reasons.append("A double gameweek is in range, which is what this chip is for.")

    if value_now < floor:
        reasons.append(
            f"Worth about {value_now:.1f} pts — below the {floor:.0f} that makes it "
            f"worth spending a chip in an ordinary week."
        )
        return "hold", "medium", reasons

    if ratio and ratio >= STRONG_MULTIPLE:
        return "use_now", "medium", reasons + [
            f"{value_now:.1f} pts against a typical {baseline:.1f} — "
            f"{ratio:.1f}× an ordinary week."
        ]

    if ratio and ratio >= DECENT_MULTIPLE:
        return "consider", "low", reasons + [
            f"{value_now:.1f} pts, {ratio:.1f}× a typical week. Above average, but "
            f"{weeks_remaining} gameweeks remain to find better."
        ]

    if baseline is None:
        # The solver-backed chips are priced for one gameweek only, because a
        # dream-team solve per week is too expensive to run across a horizon.
        # That leaves nothing to compare against, and inventing a comparison
        # would be worse than admitting there is none.
        return "hold", "low", reasons + [
            f"Worth about {value_now:.1f} pts, above the {floor:.0f} floor, but "
            f"only this gameweek could be priced — there is no comparison week "
            f"to say whether {weeks_remaining} gameweeks from now looks better.",
            "Holding is the default when the alternative is unmeasured.",
        ]

    reasons.append(
        f"{value_now:.1f} pts is close to an ordinary week ({baseline:.1f}), "
        f"and {weeks_remaining} gameweeks remain."
    )
    if best_gameweek is not None and best_value and best_value > value_now:
        reasons.append(
            f"Best in view is GW{best_gameweek} at {best_value:.1f} pts."
        )
    return "hold", "medium", reasons


async def advise(db: AsyncSession, manager_id: int, horizon: int = 5) -> dict:
    """
    Full chip picture: what is left, what each is worth, and what to do.

    Structured so the trustworthy parts stand on their own. Fixture shape and
    availability are facts and stay useful even if the projection model turns
    out to be poor; the valuations and verdicts are explicitly marked as
    resting on it.
    """
    target = await get_next_open_gameweek(db)
    if target is None:
        return {"manager_id": manager_id, "error": "No open gameweek."}

    # Picks come from the last gameweek that started, not the one being
    # targeted: FPL publishes no picks for a gameweek whose deadline has not
    # passed, and asking for them is a 404. The two are different questions and
    # conflating them is the recurring mistake in this codebase.
    started = await get_latest_started_gameweek(db)
    resolved = await resolve_squad(
        db, manager_id, target.id, started.id if started else target.id
    )
    player_ids = list(resolved.player_ids)
    budget = 100.0
    try:
        prices = (await db.execute(
            select(Player.now_cost).where(Player.id.in_(player_ids))
        )).scalars().all()
        budget = round(sum(prices) / 10.0 + (resolved.bank or 0.0), 1)
    except Exception:
        logger.debug("could not price the squad; assuming 100.0m", exc_info=True)

    shape = await fixture_shape(db, from_gameweek=target.id)
    state = await chip_state(db, manager_id)

    last_gw = (await db.execute(
        select(Gameweek.id).order_by(Gameweek.id.desc()).limit(1)
    )).scalar() or 38
    horizon_gws = [gw for gw in range(target.id, min(target.id + horizon, last_gw + 1))]

    # Value each chip across the horizon once, then reuse per window.
    per_gw: dict[str, dict[int, float]] = {k: {} for k in CHIP_LABELS}
    for gw in horizon_gws:
        bb = await value_bench_boost(db, player_ids, gw)
        if bb is not None:
            per_gw["bboost"][gw] = bb
        tc = await value_triple_captain(db, player_ids, gw)
        if tc is not None:
            per_gw["3xc"][gw] = tc

    # The solver-backed ones are expensive, so only for the target gameweek.
    fh = await value_free_hit(db, player_ids, target.id, budget)
    if fh is not None:
        per_gw["freehit"][target.id] = fh
    wc = await value_wildcard(db, player_ids, target.id, budget, horizon=horizon)
    if wc is not None:
        per_gw["wildcard"][target.id] = wc

    advice: list[dict] = []
    for chip in state:
        name = chip["name"]
        in_window = chip["start_event"] <= target.id <= chip["stop_event"]
        used = chip["used_in_gameweek"] is not None
        weeks_remaining = max(0, chip["stop_event"] - target.id + 1) if in_window else 0

        item = ChipAdvice(
            name=name,
            label=chip["label"],
            available=not used and in_window,
            used_in_gameweek=chip["used_in_gameweek"],
            window_start=chip["start_event"],
            window_end=chip["stop_event"],
            weeks_remaining=weeks_remaining,
        )

        if used:
            item.verdict = "used"
            item.confidence = "high"
            item.reasons = [f"Played in GW{chip['used_in_gameweek']}."]
        elif not in_window:
            item.verdict = "not_yet"
            item.confidence = "high"
            item.reasons = [
                f"Available from GW{chip['start_event']} to GW{chip['stop_event']}."
            ]
        else:
            values = per_gw.get(name, {})
            item.value_now = values.get(target.id)
            if values:
                item.best_gameweek = max(values, key=values.get)
                item.best_value = values[item.best_gameweek]
                # A mean over one observation equals that observation, making
                # every ratio exactly 1.0 and the reasoning circular
                # ("15.9 is close to a typical 15.9"). With one data point
                # there is no typical week to compare against, so say nothing
                # rather than something meaningless.
                if len(values) > 1:
                    item.baseline = sum(values.values()) / len(values)
            has_double = any(
                gw in shape["doubles"] for gw in horizon_gws
            )
            item.verdict, item.confidence, item.reasons = decide(
                name, item.value_now, item.best_value, item.best_gameweek,
                item.baseline, weeks_remaining, has_double,
            )

        advice.append(item.as_dict())

    return {
        "manager_id": manager_id,
        "target_gameweek": target.id,
        "budget": budget,
        "horizon": horizon_gws,
        "fixture_shape": shape,
        "squad_this_gameweek": await squad_fixture_counts(db, player_ids, target.id),
        "chips": advice,
        "history_available": all(c["history_available"] for c in state) if state else False,
        "caveat": (
            "Fixture shape and chip availability are facts. The valuations come "
            "from the projection model and inherit its uncertainty, amplified: a "
            "wildcard stakes fifteen projections at once and a triple captain "
            "triples the error on one. The verdicts are a stated heuristic, not "
            "a backtested rule."
        ),
    }


# ── Watching for the shape to change ─────────────────────────────────────────

async def alert_on_shape_changes(db: AsyncSession) -> dict:
    """
    Raise an alert the first time a double or blank gameweek appears.

    This is the one genuinely scarce piece of chip information. Doubles are
    created months after the fixture list is published, when postponed matches
    are rearranged, and nobody is checking a schedule they read in July. It is
    also the only part of chip advice that involves no model at all — a count
    of fixtures cannot be wrong the way a projection can.

    Deduplicated on the alert payload rather than a table of its own: the same
    gameweek shape must not be announced on all ninety-six refreshes a day.
    """
    from app.models.news import Alert, TrackedManager

    target = await get_next_open_gameweek(db)
    shape = await fixture_shape(db, from_gameweek=target.id if target else 1)
    if not shape["doubles"] and not shape["blanks"]:
        return {"doubles": 0, "blanks": 0, "alerts_created": 0}

    managers = (await db.execute(
        select(TrackedManager).where(TrackedManager.alerts_enabled.is_(True))
    )).scalars().all()

    created = 0
    for gw, teams in sorted(shape["doubles"].items()):
        title = f"GW{gw} is now a double gameweek"
        for m in managers:
            # Deduplicated on the title, which is stable per gameweek and works
            # the same on Postgres and SQLite. Querying inside the JSON payload
            # would need dialect-specific syntax for no gain.
            already = (await db.execute(
                select(Alert).where(
                    Alert.fpl_entry_id == m.fpl_entry_id,
                    Alert.title == title,
                )
            )).scalars().first()
            if already:
                continue
            db.add(Alert(
                fpl_entry_id=m.fpl_entry_id,
                severity="warning",
                title=title,
                body=(
                    f"{len(teams)} team{'s' if len(teams) != 1 else ''} play twice: "
                    f"{', '.join(teams[:8])}"
                    + (" and others." if len(teams) > 8 else ".")
                    + " Worth checking your chips."
                ),
                payload={"gameweek": gw, "teams": teams, "kind": "double_gameweek"},
            ))
            created += 1

    if created:
        await db.commit()
    return {
        "doubles": len(shape["doubles"]),
        "blanks": len(shape["blanks"]),
        "alerts_created": created,
    }
