"""
Optimal squad from scratch — the "if I wildcarded today" answer.

Independent of any existing squad: it picks the best legal 15 from the whole
player pool for a given budget, then names the XI, captain and bench order.

Why this needs its own solver rather than reusing the transfer optimiser: the
transfer optimiser starts from a squad and limits how many players may change.
Here nothing is owned, the whole budget is in play, and — crucially — the
objective is different.

**Only the XI scores.** A solver that maximises the sum of all 15 will spend
real money on a strong bench that never plays. So squad membership and XI
selection are separate decisions in the same model:

    squad[p]    is this player in the 15?
    start[p]    is he in the XI?          (start <= squad)
    captain[p]  is he captain?            (captain <= start)

The objective weights the XI fully, the bench at a discount, and adds the
captain's points again because the armband doubles them. That is what pushes
the solver toward the shape real managers use: a strong XI and a deliberately
cheap bench.
"""
import logging
from dataclasses import dataclass, field
from ortools.sat.python import cp_model
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models.fpl import Player, Team, Gameweek
from app.models.projections import Projection
from app.services.projection import MODEL_VERSION
from app.services.lineup import FORMATIONS, POS_NAME

logger = logging.getLogger("fpl_copilot")

DREAM_VERSION = "dream-v1"

POS_GKP, POS_DEF, POS_MID, POS_FWD = 1, 2, 3, 4
SQUAD_COMPOSITION = {POS_GKP: 2, POS_DEF: 5, POS_MID: 5, POS_FWD: 3}
XI_LIMITS = {POS_GKP: (1, 1), POS_DEF: (3, 5), POS_MID: (2, 5), POS_FWD: (1, 3)}
MAX_PER_CLUB = 3
DEFAULT_BUDGET = 1000          # £100.0m in FPL tenths
SCALE = 1000                   # CP-SAT is integer-only

# A bench player only scores if a starter misses out. Low enough that the
# solver buys cheap cover, high enough that it does not pick someone projected
# at zero and risk an autosub gap.
BENCH_WEIGHT = 0.12


@dataclass
class Candidate:
    player: Player
    team_short: str
    xpts: float                 # over the horizon
    gw_xpts: float              # the first gameweek alone
    p_start: float
    custom_fdr: float
    components: dict = field(default_factory=dict)
    opponents: list = field(default_factory=list)

    @property
    def value(self) -> float:
        return self.xpts / (self.player.now_cost / 10) if self.player.now_cost else 0.0


@dataclass
class Pick:
    candidate: Candidate
    starting: bool
    is_captain: bool
    is_vice: bool
    bench_order: int | None
    reasons: list[str]


async def _load_candidates(
    db: AsyncSession, gw_ids: list[int]
) -> list[Candidate]:
    """Every available player with a projection over the horizon."""
    rows = (await db.execute(
        select(
            Player,
            Team.short_name,
            func.sum(Projection.xpts).label("total"),
            func.avg(Projection.p_start).label("p_start"),
            func.avg(Projection.custom_fdr).label("fdr"),
        )
        .join(Team, Team.id == Player.team_id)
        .join(Projection, Projection.player_id == Player.id)
        .where(
            Projection.gameweek_id.in_(gw_ids),
            Projection.model_version == MODEL_VERSION,
            # Unavailable players cannot be picked, however good their history
            Player.status == "a",
        )
        .group_by(Player.id, Team.short_name)
    )).all()

    # First-gameweek detail, for the explanations
    first_gw = min(gw_ids)
    detail = {
        p.player_id: p
        for p in (await db.execute(
            select(Projection).where(
                Projection.gameweek_id == first_gw,
                Projection.model_version == MODEL_VERSION,
            )
        )).scalars().all()
    }

    out = []
    for player, short, total, p_start, fdr in rows:
        d = detail.get(player.id)
        out.append(Candidate(
            player=player,
            team_short=short,
            xpts=float(total or 0.0),
            gw_xpts=d.xpts if d else 0.0,
            p_start=float(p_start or 0.0),
            custom_fdr=float(fdr or 3.0),
            components={
                "appearance": d.xpts_appearance,
                "goals": d.xpts_goals,
                "assists": d.xpts_assists,
                "clean_sheet": d.xpts_clean_sheet,
                "goals_conceded": d.xpts_goals_conceded,
                "saves": d.xpts_saves,
                "defensive_contribution": d.xpts_defensive_contribution,
                "bonus": d.xpts_bonus,
                "cards": d.xpts_cards,
            } if d else {},
            opponents=(d.opponents or []) if d else [],
        ))
    return out


def _solve(
    candidates: list[Candidate],
    budget: int,
    must_include: set[int],
    exclude: set[int],
    time_limit: float,
) -> tuple[list[int], list[int], int | None, str]:
    """
    Returns (squad_ids, starting_ids, captain_id, solver_status).

    Squad membership, XI selection and the captaincy are decided together —
    picking the 15 first and the XI afterwards produces a worse squad, because
    the value of a player depends on whether he is expected to start.
    """
    pool = [c for c in candidates if c.player.id not in exclude]
    by_id = {c.player.id: c for c in pool}

    missing = must_include - set(by_id)
    if missing:
        raise ValueError(
            f"Cannot force players not in the candidate pool: {sorted(missing)}. "
            f"They may be unavailable or have no projection."
        )

    model = cp_model.CpModel()
    squad, start, captain = {}, {}, {}
    for c in pool:
        pid = c.player.id
        squad[pid] = model.NewBoolVar(f"squad_{pid}")
        start[pid] = model.NewBoolVar(f"start_{pid}")
        captain[pid] = model.NewBoolVar(f"capt_{pid}")
        model.Add(start[pid] <= squad[pid])
        model.Add(captain[pid] <= start[pid])

    # ── Squad shape ──────────────────────────────────────────────────────────
    for position, count in SQUAD_COMPOSITION.items():
        model.Add(
            sum(squad[c.player.id] for c in pool if c.player.position == position)
            == count
        )

    # ── XI shape ─────────────────────────────────────────────────────────────
    model.Add(sum(start.values()) == 11)
    for position, (lo, hi) in XI_LIMITS.items():
        picked = sum(start[c.player.id] for c in pool if c.player.position == position)
        model.Add(picked >= lo)
        model.Add(picked <= hi)

    # ── Club limit ───────────────────────────────────────────────────────────
    clubs: dict[int, list] = {}
    for c in pool:
        clubs.setdefault(c.player.team_id, []).append(squad[c.player.id])
    for club_vars in clubs.values():
        model.Add(sum(club_vars) <= MAX_PER_CLUB)

    # ── Budget ───────────────────────────────────────────────────────────────
    model.Add(
        sum(squad[c.player.id] * c.player.now_cost for c in pool) <= budget
    )

    # ── Exactly one captain ──────────────────────────────────────────────────
    model.Add(sum(captain.values()) == 1)

    # ── Forced picks ─────────────────────────────────────────────────────────
    for pid in must_include:
        model.Add(squad[pid] == 1)

    # ── Objective ────────────────────────────────────────────────────────────
    terms = []
    for c in pool:
        pid = c.player.id
        full = int(round(c.xpts * SCALE))
        bench = int(round(c.xpts * BENCH_WEIGHT * SCALE))
        # squad membership pays the bench rate; starting adds the remainder,
        # so a starter is worth full value and a benched player the discount.
        terms.append(squad[pid] * bench)
        terms.append(start[pid] * (full - bench))
        # The armband doubles a player, so it is worth his points again.
        terms.append(captain[pid] * full)

    model.Maximize(sum(terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = 4
    # Fixed seed so repeated clicks give the same squad. Blueprint §29 requires
    # recommendations to be reproducible, and "best team" changing between two
    # identical requests destroys trust faster than a slightly worse pick.
    #
    # Caveat worth knowing: with several workers CP-SAT is not bit-for-bit
    # deterministic under a time limit, so on a problem where it cannot prove
    # optimality the answer may still vary. Where it proves OPTIMAL — which is
    # the normal case on real data — the objective value is unique and the
    # result is stable.
    solver.parameters.random_seed = 20260825
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise ValueError(
            f"No legal squad fits a £{budget / 10:.1f}m budget "
            f"(solver status: {solver.StatusName(status)})"
        )

    squad_ids = [c.player.id for c in pool if solver.Value(squad[c.player.id])]
    starting_ids = [c.player.id for c in pool if solver.Value(start[c.player.id])]
    captain_id = next(
        (c.player.id for c in pool if solver.Value(captain[c.player.id])), None
    )
    return squad_ids, starting_ids, captain_id, solver.StatusName(status)


# ── Explanations ──────────────────────────────────────────────────────────────
#
# Every reason is derived from a number the model actually produced. Nothing is
# generated prose: a claim the user can check against the data is worth more
# than a fluent sentence they cannot.

COMPONENT_LABEL = {
    "goals": "goal threat",
    "assists": "creativity",
    "clean_sheet": "clean-sheet odds",
    "saves": "save volume",
    "defensive_contribution": "defensive contributions",
    "bonus": "bonus potential",
    "appearance": "guaranteed minutes",
}


def _fixture_phrase(c: Candidate) -> str | None:
    """Describe the upcoming fixture in plain terms."""
    if not c.opponents:
        return None
    first = c.opponents[0]
    fdr = first.get("fdr", c.custom_fdr)
    where = "home" if first.get("is_home") else "away"
    if fdr <= 2.0:
        band = "Very favourable"
    elif fdr <= 2.75:
        band = "Favourable"
    elif fdr <= 3.5:
        band = "Average"
    elif fdr <= 4.25:
        band = "Tough"
    else:
        band = "Very tough"
    extra = f" ({len(c.opponents)} fixtures)" if len(c.opponents) > 1 else ""
    return f"{band} {where} fixture, FDR {fdr:.1f}{extra}"


def build_reasons(
    c: Candidate,
    *,
    starting: bool,
    is_captain: bool,
    position_rank: int,
    value_rank: int,
    position_count: int,
) -> list[str]:
    """Why this player is in the squad, ordered by what matters most."""
    reasons: list[str] = []
    pos = POS_NAME.get(c.player.position, "UNK")
    price = c.player.now_cost / 10

    # 1. Role in the squad
    if is_captain:
        reasons.append(
            f"Captain: highest projected return in the XI at {c.xpts:.1f} pts, "
            f"doubled to {c.xpts * 2:.1f}"
        )
    elif not starting:
        reasons.append(
            f"Bench cover at {price:.1f}m - keeps budget in the XI while still "
            f"providing an autosub option"
        )

    # 2. Rank within his position
    if starting:
        if position_rank == 1:
            reasons.append(f"Top-projected {pos} in the game ({c.xpts:.1f} pts)")
        elif position_rank <= 5:
            reasons.append(f"#{position_rank} projected {pos} ({c.xpts:.1f} pts)")
        else:
            reasons.append(
                f"Projected {c.xpts:.1f} pts, #{position_rank} of "
                f"{position_count} {pos}s"
            )

    # 3. What actually drives the projection
    scoring = {
        k: v for k, v in (c.components or {}).items()
        if v and v > 0 and k in COMPONENT_LABEL
    }
    if scoring:
        top_key, top_val = max(scoring.items(), key=lambda kv: kv[1])
        if top_val >= 0.4:
            reasons.append(
                f"Points come mainly from {COMPONENT_LABEL[top_key]} "
                f"({top_val:.1f} of {c.gw_xpts:.1f} next GW)"
            )

    # 4. Fixture
    fixture = _fixture_phrase(c)
    if fixture:
        reasons.append(fixture)

    # 5. Value, when that is why he was affordable
    if value_rank <= 10:
        reasons.append(
            f"Strong value: {c.value:.2f} pts per 1.0m (#{value_rank} in the pool)"
        )

    # 6. Set-piece duty - a real edge price does not always reflect
    if c.player.penalties_order == 1:
        reasons.append("First-choice penalty taker")
    elif c.player.corners_freekicks_order == 1:
        reasons.append("Takes corners and indirect free kicks")

    # 7. Honest risk flags
    if c.p_start < 0.7:
        reasons.append(
            f"Risk: only {c.p_start:.0%} likely to start - rotation or minutes doubt"
        )
    if c.player.price_change_percent >= 75:
        reasons.append(
            f"Price rise likely soon ({c.player.price_change_percent:.0f}% toward "
            f"the threshold) - buying now locks the price in"
        )
    elif c.player.price_change_percent <= -75:
        reasons.append(
            f"Price fall likely soon ({abs(c.player.price_change_percent):.0f}% "
            f"toward the threshold)"
        )

    return reasons


def _order_bench(bench: list[Candidate]) -> list[Candidate]:
    """
    Reserve keeper first - he can only replace the starting keeper, so he never
    competes with outfield players for an autosub slot.
    """
    keepers = [c for c in bench if c.player.position == POS_GKP]
    outfield = sorted(
        (c for c in bench if c.player.position != POS_GKP),
        key=lambda c: c.gw_xpts * max(c.p_start, 0.01),
        reverse=True,
    )
    return keepers + outfield


def _formation(starting: list[Candidate]) -> str:
    d = sum(1 for c in starting if c.player.position == POS_DEF)
    m = sum(1 for c in starting if c.player.position == POS_MID)
    f = sum(1 for c in starting if c.player.position == POS_FWD)
    return f"{d}-{m}-{f}"


async def build_dream_team(
    db: AsyncSession,
    *,
    budget: int = DEFAULT_BUDGET,
    horizon: int = 1,
    start_gw: int | None = None,
    must_include: list[int] | None = None,
    exclude: list[int] | None = None,
    time_limit: float = 10.0,
) -> dict:
    """
    Best legal 15 for the upcoming gameweek(s), from the whole player pool.

    `horizon=1` answers "best team for the next gameweek". A longer horizon
    favours players with a good run of fixtures rather than one strong match.
    """
    from app.services.fpl_sync import get_next_open_gameweek

    if start_gw is None:
        gw = await get_next_open_gameweek(db)
        if not gw:
            raise ValueError("No gameweek found - sync FPL data first.")
        start_gw = gw.id

    requested = (await db.execute(
        select(Gameweek.id).where(Gameweek.id >= start_gw)
        .order_by(Gameweek.id).limit(horizon)
    )).scalars().all()

    projected = set((await db.execute(
        select(Projection.gameweek_id)
        .where(
            Projection.gameweek_id.in_(requested),
            Projection.model_version == MODEL_VERSION,
        ).distinct()
    )).scalars().all())

    gw_ids = [g for g in requested if g in projected]
    if not gw_ids:
        raise ValueError(
            "No projections for the requested gameweeks. Run "
            "POST /api/v1/projections/rebuild first."
        )

    candidates = await _load_candidates(db, gw_ids)
    if len(candidates) < 15:
        raise ValueError(
            f"Only {len(candidates)} available players have projections - "
            f"not enough to build a squad."
        )

    squad_ids, starting_ids, captain_id, status = _solve(
        candidates,
        budget=budget,
        must_include=set(must_include or []),
        exclude=set(exclude or []),
        time_limit=time_limit,
    )

    by_id = {c.player.id: c for c in candidates}
    squad = [by_id[pid] for pid in squad_ids]
    starting = [by_id[pid] for pid in starting_ids]
    bench = _order_bench([c for c in squad if c.player.id not in set(starting_ids)])

    # Vice-captain: reliable, and from a different club to the captain so one
    # postponed match cannot remove both.
    captain = by_id.get(captain_id) if captain_id else None
    vice_pool = [
        c for c in starting
        if c.player.id != captain_id
        and (captain is None or c.player.team_id != captain.player.team_id)
    ] or [c for c in starting if c.player.id != captain_id]
    vice = max(vice_pool, key=lambda c: c.gw_xpts * c.p_start, default=None)

    # Ranks used by the explanations
    pos_ranks: dict[int, int] = {}
    pos_counts: dict[int, int] = {}
    for position in SQUAD_COMPOSITION:
        ranked = sorted(
            (c for c in candidates if c.player.position == position),
            key=lambda c: c.xpts, reverse=True,
        )
        pos_counts[position] = len(ranked)
        for i, c in enumerate(ranked, 1):
            pos_ranks[c.player.id] = i

    value_ranked = sorted(candidates, key=lambda c: c.value, reverse=True)
    value_ranks = {c.player.id: i for i, c in enumerate(value_ranked, 1)}

    def to_dict(c: Candidate, starting_flag: bool, bench_order: int | None) -> dict:
        is_capt = c.player.id == captain_id
        return {
            "player_id": c.player.id,
            "name": c.player.web_name,
            "full_name": f"{c.player.first_name} {c.player.second_name}".strip(),
            "team": c.team_short,
            "position": POS_NAME.get(c.player.position, "UNK"),
            "price": round(c.player.now_cost / 10, 1),
            "photo": (
                f"https://resources.premierleague.com/premierleague/photos/"
                f"players/110x140/p{c.player.code}.png"
                if c.player.code else None
            ),
            "xpts": round(c.xpts, 2),
            "gw_xpts": round(c.gw_xpts, 2),
            "value": round(c.value, 3),
            "p_start": round(c.p_start, 3),
            "custom_fdr": round(c.custom_fdr, 2),
            "is_starting": starting_flag,
            "is_captain": is_capt,
            "is_vice_captain": vice is not None and c.player.id == vice.player.id,
            "bench_order": bench_order,
            "position_rank": pos_ranks.get(c.player.id),
            "value_rank": value_ranks.get(c.player.id),
            "components": {k: round(v, 2) for k, v in (c.components or {}).items()},
            "reasons": build_reasons(
                c,
                starting=starting_flag,
                is_captain=is_capt,
                position_rank=pos_ranks.get(c.player.id, 999),
                value_rank=value_ranks.get(c.player.id, 999),
                position_count=pos_counts.get(c.player.position, 0),
            ),
        }

    xi_pts = sum(c.gw_xpts for c in starting)
    total_cost = sum(c.player.now_cost for c in squad)

    proven_optimal = status == "OPTIMAL"

    return {
        "version": DREAM_VERSION,
        "model_version": MODEL_VERSION,
        "solver_status": status,
        # CP-SAT returns FEASIBLE when it found a good squad but ran out of
        # time proving nothing better exists. Say so rather than implying a
        # guarantee — a plateau of near-identical squads makes this likely.
        "proven_optimal": proven_optimal,
        "optimality_note": None if proven_optimal else (
            "Best squad found within the time limit, but not proven optimal — "
            "many squads scored almost identically. Raising the time limit may "
            "find a marginally better one."
        ),
        "gameweeks": gw_ids,
        "horizon": len(gw_ids),
        "horizon_truncated": len(gw_ids) < horizon,
        "budget": round(budget / 10, 1),
        "squad_cost": round(total_cost / 10, 1),
        "money_left": round((budget - total_cost) / 10, 1),
        "formation": _formation(starting),
        "projected_next_gw": round(
            xi_pts + (captain.gw_xpts if captain else 0.0), 2
        ),
        "projected_horizon": round(sum(c.xpts for c in starting), 2),
        "candidates_considered": len(candidates),
        "captain": captain.player.web_name if captain else None,
        "vice_captain": vice.player.web_name if vice else None,
        "starting": [to_dict(c, True, None) for c in starting],
        "bench": [to_dict(c, False, i) for i, c in enumerate(bench)],
        "explanation_note": (
            "Reasons are derived from the projection model's own numbers - "
            "component breakdown, custom FDR, value rank and set-piece role - "
            "not generated prose. Every claim is checkable against the data."
        ),
    }
