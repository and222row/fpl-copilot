"""
Player projection model v1.

Deliberately a transparent statistical model, not ML: every number can be
traced to an input, which makes it debuggable and gives the backtest harness
something to beat (blueprint §11).

Structure per player per gameweek:
    1. availability      -> multiplier on minutes
    2. expected minutes  -> p_start, p_appear, p_60
    3. fixture context   -> expected team goals for/against (custom FDR)
    4. scoring components-> goals, assists, CS, saves, DC, bonus, cards
    5. sum + variance

Rates are shrunk toward position baselines, weighted by minutes played, so a
player with 20 minutes of data does not get a projection built on noise.
"""
import math
from dataclasses import dataclass, field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func
from app.models.fpl import Player, Fixture, Gameweek, utcnow
from app.models.projections import Projection, ScoringRules, TeamStrength
from app.services.team_strength import (
    load_strength_map, expected_goals_for_fixture, fdr_from_expected_goals,
)
from app.services.news_parser import resolve_availability

MODEL_VERSION = "proj-v1"

POS_GKP, POS_DEF, POS_MID, POS_FWD = 1, 2, 3, 4
POS_KEY = {POS_GKP: "GKP", POS_DEF: "DEF", POS_MID: "MID", POS_FWD: "FWD"}

# ── Shrinkage ────────────────────────────────────────────────────────────────
# Minutes of real data needed before a player's own rate carries as much weight
# as the prior. ~7 full matches.
#
# This is deliberately high. FPL publishes per-90 rates computed from whatever
# minutes a player has played, so a defender who scores once in 77 minutes gets
# an xG/90 of 1.7 — Haaland territory, from a single shot. Without heavy
# shrinkage the model ranks one-game outliers above genuine elite players.
SHRINK_MINUTES = 600.0

# A shrunk rate may not exceed this multiple of the price-implied prior.
# Stops a single hot gameweek from dominating while still letting a genuinely
# underpriced player through (his price, and so his prior, rises over time).
MAX_RATE_VS_PRIOR = 3.0

# Position baselines per 90 for a player priced at his position's median.
BASELINE = {
    POS_GKP: {"xg": 0.00, "xa": 0.01, "dc": 1.0, "bonus": 0.35, "yellow": 0.05},
    POS_DEF: {"xg": 0.06, "xa": 0.06, "dc": 6.5, "bonus": 0.30, "yellow": 0.18},
    POS_MID: {"xg": 0.16, "xa": 0.16, "dc": 5.0, "bonus": 0.28, "yellow": 0.15},
    POS_FWD: {"xg": 0.35, "xa": 0.14, "dc": 2.5, "bonus": 0.30, "yellow": 0.12},
}

# Median price per position, in FPL tenths. Recomputed from live data each
# rebuild; these are only the fallback.
DEFAULT_MEDIAN_COST = {POS_GKP: 45, POS_DEF: 45, POS_MID: 55, POS_FWD: 55}

# How strongly price scales the attacking prior. 1.0 = linear in price ratio,
# which lines up well with observed elite rates (Haaland ~0.95 xG90 at £15.5m
# against a £5.5m forward baseline of 0.35).
PRICE_PRIOR_EXPONENT = 1.0

# Minutes assumptions
STARTER_MINUTES = 82.0        # average for a player who starts
SUB_MINUTES = 22.0            # average for a player who comes off the bench
P_SUB_IF_NOT_START = 0.35     # chance a non-starter appears at all

# Penalties: a designated taker's share of his team's expected pens
TEAM_PENS_PER_MATCH = 0.13    # ~5 pens per team per season
PEN_CONVERSION = 0.79


# ── Availability ─────────────────────────────────────────────────────────────

def availability_multiplier(player: Player) -> float:
    """
    Convert FPL availability signals into a minutes multiplier.

    Delegates to `resolve_availability`, which prefers the percentage in the
    news text over `chance_of_playing_this_round`. That ordering is not
    cosmetic: the field is per-round and goes null or stale between gameweeks,
    and 14 of 22 doubtful players had a usable percentage in the text that the
    field either lacked or contradicted (e.g. Pedro Porro, field 0% vs text
    75%). Reading the field first under-projected every one of them.

    Blueprint §11: availability scales expected minutes rather than deleting
    the player.
    """
    multiplier, _source, _parsed = resolve_availability(
        status=player.status,
        chance_field=player.chance_of_playing_this_round,
        news=player.news,
    )
    return multiplier


# ── Minutes ──────────────────────────────────────────────────────────────────

@dataclass
class MinutesEstimate:
    p_start: float
    p_appear: float
    p_60: float
    expected_minutes: float
    availability: float


NEUTRAL_P_START = 0.55   # used before any match has been played


def estimate_minutes(player: Player, matches_played: int) -> MinutesEstimate:
    """
    Expected minutes for one fixture.

    p_start blends the player's observed start rate with his share of available
    minutes, weighted by sample size. Before any match has been played there is
    no signal at all, so it falls back to a neutral assumption.
    """
    avail = availability_multiplier(player)
    if avail <= 0.0:
        return MinutesEstimate(0.0, 0.0, 0.0, 0.0, 0.0)

    if matches_played <= 0:
        # Pre-season: no minutes data exists. Anything derived from
        # player.minutes here would divide by a meaningless denominator.
        base_start_rate = NEUTRAL_P_START
    else:
        available_minutes = matches_played * 90.0
        minutes_share = min(1.0, player.minutes / available_minutes)
        observed_start_rate = min(1.0, player.starts / matches_played)
        # Trust the observed start rate more as matches accumulate
        w = matches_played / (matches_played + 3.0)
        base_start_rate = max(
            0.0, min(1.0, observed_start_rate * w + minutes_share * (1 - w))
        )

    # Availability is P(fit enough to feature); the start/sub split is
    # conditional on being fit. Both terms therefore scale by `avail`, and the
    # substitute term uses the UNSCALED start rate — deriving it from the
    # already-scaled p_start let total appearance probability exceed
    # availability (a 50%-available nailed starter came out at 59% to appear).
    p_start = base_start_rate * avail
    p_sub = avail * (1.0 - base_start_rate) * P_SUB_IF_NOT_START

    expected_minutes = p_start * STARTER_MINUTES + p_sub * SUB_MINUTES
    p_appear = min(avail, p_start + p_sub)

    # A starter almost always reaches 60'; a sub rarely does.
    p_60 = p_start * 0.88 + p_sub * 0.10

    return MinutesEstimate(
        p_start=round(p_start, 4),
        p_appear=round(p_appear, 4),
        p_60=round(p_60, 4),
        expected_minutes=round(expected_minutes, 2),
        availability=round(avail, 4),
    )


# ── Rate shrinkage ───────────────────────────────────────────────────────────

def price_scaled_prior(baseline: float, cost: int, median_cost: int) -> float:
    """
    Scale a positional baseline by the player's price.

    FPL price is the market's aggregate judgement of a player's output, and
    it is by far the best prior available before a season has any data. A
    £15.5m forward and a £4.5m forward are not the same player, and giving
    them the same starting assumption is what lets one-game noise dominate.
    """
    if baseline <= 0 or not cost or not median_cost:
        return baseline
    ratio = cost / median_cost
    return baseline * (ratio ** PRICE_PRIOR_EXPONENT)


def shrink(observed_per_90: float, prior: float, minutes: int) -> float:
    """
    Blend a player's own per-90 rate toward his prior, then cap it.

    The cap matters more than the blend early in a season: with a handful of
    minutes played, FPL's per-90 figures are near-meaningless and a blend alone
    still lets them through.
    """
    w = minutes / (minutes + SHRINK_MINUTES)
    blended = observed_per_90 * w + prior * (1 - w)
    if prior > 0:
        return min(blended, prior * MAX_RATE_VS_PRIOR)
    return blended


# ── Scoring rules access ─────────────────────────────────────────────────────

@dataclass
class Rules:
    """Flattened view of the synced FPL scoring table."""
    long_play: int = 2
    short_play: int = 1
    assists: int = 3
    yellow: int = -1
    red: int = -3
    own_goal: int = -2
    pen_missed: int = -2
    pen_saved: int = 5
    saves_pts: int = 1
    bonus_mult: int = 1
    goals: dict = field(default_factory=lambda: {"GKP": 10, "DEF": 6, "MID": 5, "FWD": 4})
    clean_sheets: dict = field(default_factory=lambda: {"GKP": 4, "DEF": 4, "MID": 1, "FWD": 0})
    goals_conceded: dict = field(default_factory=lambda: {"GKP": -1, "DEF": -1, "MID": 0, "FWD": 0})
    defensive_contribution: dict = field(default_factory=lambda: {"GKP": 0, "DEF": 2, "MID": 2, "FWD": 2})
    dc_threshold_def: int = 10
    dc_threshold_mid_fwd: int = 12
    saves_per_point: int = 3
    conceded_per_penalty: int = 2


async def load_rules(db: AsyncSession) -> Rules:
    """Load active scoring rules from the DB, falling back to defaults."""
    row = (await db.execute(
        select(ScoringRules).where(ScoringRules.is_active.is_(True))
    )).scalars().first()

    if row is None:
        return Rules()

    s = row.rules or {}
    r = Rules()
    r.long_play = s.get("long_play", r.long_play)
    r.short_play = s.get("short_play", r.short_play)
    r.assists = s.get("assists", r.assists)
    r.yellow = s.get("yellow_cards", r.yellow)
    r.red = s.get("red_cards", r.red)
    r.own_goal = s.get("own_goals", r.own_goal)
    r.pen_missed = s.get("penalties_missed", r.pen_missed)
    r.pen_saved = s.get("penalties_saved", r.pen_saved)
    r.saves_pts = s.get("saves", r.saves_pts)
    r.bonus_mult = s.get("bonus", r.bonus_mult)
    if isinstance(s.get("goals_scored"), dict):
        r.goals = s["goals_scored"]
    if isinstance(s.get("clean_sheets"), dict):
        r.clean_sheets = s["clean_sheets"]
    if isinstance(s.get("goals_conceded"), dict):
        r.goals_conceded = s["goals_conceded"]
    if isinstance(s.get("defensive_contribution"), dict):
        r.defensive_contribution = s["defensive_contribution"]
    r.dc_threshold_def = row.dc_threshold_def
    r.dc_threshold_mid_fwd = row.dc_threshold_mid_fwd
    r.saves_per_point = row.saves_per_point
    r.conceded_per_penalty = row.goals_conceded_per_penalty
    return r


# ── Probability helpers ──────────────────────────────────────────────────────

def poisson_zero(mean: float) -> float:
    """P(X = 0) for Poisson(mean) — used for clean sheets."""
    return math.exp(-max(0.0, mean))


def poisson_at_least(mean: float, k: int) -> float:
    """P(X >= k) for Poisson(mean) — used for defensive-contribution points."""
    if k <= 0:
        return 1.0
    mean = max(1e-9, mean)
    # P(X < k) = sum_{i=0}^{k-1} e^-m m^i / i!
    cum = 0.0
    term = math.exp(-mean)
    cum += term
    for i in range(1, k):
        term *= mean / i
        cum += term
    return max(0.0, min(1.0, 1.0 - cum))


def expected_conceded_penalty(xgc: float, per_penalty: int) -> float:
    """
    Expected count of the "-1 per N goals conceded" penalty.

    E[floor(X/N)] for X ~ Poisson(xgc), truncated at a sane upper bound.
    """
    total = 0.0
    p = math.exp(-xgc)
    for k in range(0, 12):
        if k > 0:
            p *= xgc / k
        total += p * (k // per_penalty)
    return total


# ── The model ────────────────────────────────────────────────────────────────

@dataclass
class ProjectionResult:
    player_id: int
    gameweek_id: int
    xpts: float
    variance: float
    minutes: MinutesEstimate
    fixture_count: int
    expected_team_goals: float
    expected_team_conceded: float
    custom_fdr: float
    opponents: list
    components: dict


def project_player_gameweek(
    player: Player,
    fixtures: list[tuple[Fixture, bool]],   # (fixture, is_home)
    strength: dict[int, TeamStrength],
    rules: Rules,
    matches_played: int,
    median_cost: dict[int, int] | None = None,
) -> ProjectionResult:
    """
    Project one player for one gameweek across all his fixtures.

    A blank gameweek yields zero; a double gameweek sums both fixtures.
    """
    pos = player.position
    pos_key = POS_KEY.get(pos, "MID")
    base = BASELINE.get(pos, BASELINE[POS_MID])

    mins = estimate_minutes(player, matches_played)

    comp = {
        "appearance": 0.0, "goals": 0.0, "assists": 0.0, "clean_sheet": 0.0,
        "goals_conceded": 0.0, "saves": 0.0, "defensive_contribution": 0.0,
        "bonus": 0.0, "cards": 0.0, "penalties": 0.0,
    }

    if not fixtures or mins.expected_minutes <= 0:
        return ProjectionResult(
            player_id=player.id, gameweek_id=0, xpts=0.0, variance=0.0,
            minutes=mins, fixture_count=len(fixtures),
            expected_team_goals=0.0, expected_team_conceded=0.0,
            custom_fdr=3.0, opponents=[], components=comp,
        )

    # Priors: positional baseline scaled by price for the attacking rates.
    # Defensive-contribution and card rates are role-driven, not price-driven,
    # so they keep the flat positional baseline.
    medians = median_cost or DEFAULT_MEDIAN_COST
    med = medians.get(pos, DEFAULT_MEDIAN_COST.get(pos, 50))
    prior_xg = price_scaled_prior(base["xg"], player.now_cost, med)
    prior_xa = price_scaled_prior(base["xa"], player.now_cost, med)
    prior_bonus = price_scaled_prior(base["bonus"], player.now_cost, med)

    # Shrunk per-90 rates
    xg90 = shrink(player.expected_goals_per_90, prior_xg, player.minutes)
    xa90 = shrink(player.expected_assists_per_90, prior_xa, player.minutes)
    dc90 = shrink(player.defensive_contribution_per_90, base["dc"], player.minutes)
    saves90 = player.saves_per_90 if pos == POS_GKP else 0.0

    # Bonus and cards per 90 from season totals
    bonus90 = shrink(
        player.bonus / (player.minutes / 90.0) if player.minutes >= 90 else prior_bonus,
        prior_bonus, player.minutes,
    )
    yellow90 = shrink(
        player.yellow_cards / (player.minutes / 90.0) if player.minutes >= 90 else base["yellow"],
        base["yellow"], player.minutes,
    )

    total_team_goals = 0.0
    total_team_conceded = 0.0
    opponents: list = []

    for fixture, is_home in fixtures:
        own_team = fixture.team_h if is_home else fixture.team_a
        opp_team = fixture.team_a if is_home else fixture.team_h

        team_goals = expected_goals_for_fixture(strength, own_team, opp_team, is_home)
        team_conceded = expected_goals_for_fixture(strength, opp_team, own_team, not is_home)
        total_team_goals += team_goals
        total_team_conceded += team_conceded

        opponents.append({
            "fixture_id": fixture.id,
            "opponent": opp_team,
            "is_home": is_home,
            "expected_team_goals": round(team_goals, 3),
            "expected_conceded": round(team_conceded, 3),
            "fdr": fdr_from_expected_goals(team_conceded),
        })

        minutes_frac = mins.expected_minutes / 90.0

        # ── Appearance ───────────────────────────────────────────────────────
        p_short = max(0.0, mins.p_appear - mins.p_60)
        comp["appearance"] += p_short * rules.short_play + mins.p_60 * rules.long_play

        # ── Goals ────────────────────────────────────────────────────────────
        # Scale the player's rate by how good this fixture is for his team
        # relative to a league-average fixture.
        goal_scale = team_goals / 1.35
        e_goals = xg90 * minutes_frac * goal_scale

        # Penalties: a first-choice taker gets extra expected goals
        if player.penalties_order == 1:
            e_pens = TEAM_PENS_PER_MATCH * goal_scale * (mins.expected_minutes / 90.0)
            e_goals += e_pens * PEN_CONVERSION
            comp["penalties"] += e_pens * (1 - PEN_CONVERSION) * rules.pen_missed

        comp["goals"] += e_goals * rules.goals.get(pos_key, 4)

        # ── Assists ──────────────────────────────────────────────────────────
        comp["assists"] += xa90 * minutes_frac * goal_scale * rules.assists

        # ── Clean sheet (needs 60+ minutes) ──────────────────────────────────
        cs_pts = rules.clean_sheets.get(pos_key, 0)
        if cs_pts:
            p_cs = poisson_zero(team_conceded)
            comp["clean_sheet"] += p_cs * mins.p_60 * cs_pts

        # ── Goals conceded penalty (GK/DEF) ─────────────────────────────────
        gc_pts = rules.goals_conceded.get(pos_key, 0)
        if gc_pts:
            e_penalty_count = expected_conceded_penalty(
                team_conceded, rules.conceded_per_penalty
            )
            # Only counts while on the pitch
            comp["goals_conceded"] += e_penalty_count * gc_pts * mins.p_appear

        # ── Saves (GK) ───────────────────────────────────────────────────────
        if pos == POS_GKP and saves90 > 0:
            # More saves expected in a harder fixture
            e_saves = saves90 * minutes_frac * (team_conceded / 1.35)
            comp["saves"] += (e_saves / rules.saves_per_point) * rules.saves_pts

        # ── Defensive contribution ───────────────────────────────────────────
        dc_pts = rules.defensive_contribution.get(pos_key, 0)
        if dc_pts:
            threshold = (
                rules.dc_threshold_def if pos == POS_DEF else rules.dc_threshold_mid_fwd
            )
            e_dc = dc90 * minutes_frac
            p_dc = poisson_at_least(e_dc, threshold)
            comp["defensive_contribution"] += p_dc * dc_pts

        # ── Bonus ────────────────────────────────────────────────────────────
        comp["bonus"] += bonus90 * minutes_frac * rules.bonus_mult

        # ── Cards ────────────────────────────────────────────────────────────
        comp["cards"] += yellow90 * minutes_frac * rules.yellow

    xpts = sum(comp.values())

    # Variance: dominated by whether he plays, plus goal-scoring randomness.
    # Used by the captain engine to trade off ceiling against certainty.
    appearance_var = mins.p_appear * (1 - mins.p_appear) * (rules.long_play ** 2)
    goal_var = comp["goals"] * rules.goals.get(pos_key, 4) * 0.5
    variance = appearance_var + max(0.0, goal_var)

    return ProjectionResult(
        player_id=player.id,
        gameweek_id=0,
        xpts=round(xpts, 3),
        variance=round(variance, 3),
        minutes=mins,
        fixture_count=len(fixtures),
        expected_team_goals=round(total_team_goals, 3),
        expected_team_conceded=round(total_team_conceded, 3),
        custom_fdr=fdr_from_expected_goals(
            total_team_conceded / max(1, len(fixtures))
        ),
        opponents=opponents,
        components={k: round(v, 3) for k, v in comp.items()},
    )


# ── Orchestration ────────────────────────────────────────────────────────────

async def rebuild_projections(
    db: AsyncSession,
    gameweeks: list[int] | None = None,
    horizon: int = 5,
) -> dict:
    """
    Rebuild projections for every player across a horizon of gameweeks.

    Defaults to the next `horizon` unfinished gameweeks.
    """
    rules = await load_rules(db)
    strength = await load_strength_map(db)

    # Which gameweeks?
    if gameweeks:
        gw_rows = (await db.execute(
            select(Gameweek).where(Gameweek.id.in_(gameweeks)).order_by(Gameweek.id)
        )).scalars().all()
    else:
        gw_rows = (await db.execute(
            select(Gameweek).where(Gameweek.finished.is_(False)).order_by(Gameweek.id).limit(horizon)
        )).scalars().all()

    if not gw_rows:
        return {"error": "no gameweeks to project", "written": 0}

    gw_ids = [g.id for g in gw_rows]

    # How many rounds of football have actually been played? Drives both
    # shrinkage and the minutes estimate.
    #
    # NOT the count of finished gameweeks: FPL only sets `finished` once bonus
    # points are verified, so a fully-played GW1 still reports finished=False
    # and every rate would be built on a zero denominator.
    matches_played = (await db.execute(
        select(func.count(func.distinct(Fixture.gameweek_id)))
        .where((Fixture.finished.is_(True)) | (Fixture.finished_provisional.is_(True)))
    )).scalar() or 0

    players = (await db.execute(select(Player))).scalars().all()

    # Median price per position, for the price-scaled priors
    median_cost: dict[int, int] = {}
    for position in (POS_GKP, POS_DEF, POS_MID, POS_FWD):
        costs = sorted(p.now_cost for p in players if p.position == position and p.now_cost)
        if costs:
            median_cost[position] = costs[len(costs) // 2]

    # All fixtures in the horizon, grouped by (gameweek, team)
    fixtures = (await db.execute(
        select(Fixture).where(Fixture.gameweek_id.in_(gw_ids))
    )).scalars().all()

    by_gw_team: dict[tuple[int, int], list[tuple[Fixture, bool]]] = {}
    for f in fixtures:
        if f.gameweek_id is None:
            continue
        by_gw_team.setdefault((f.gameweek_id, f.team_h), []).append((f, True))
        by_gw_team.setdefault((f.gameweek_id, f.team_a), []).append((f, False))

    # Replace this model version's projections for these gameweeks
    await db.execute(
        delete(Projection).where(
            Projection.gameweek_id.in_(gw_ids),
            Projection.model_version == MODEL_VERSION,
        )
    )

    written = 0
    for gw in gw_rows:
        for player in players:
            player_fixtures = by_gw_team.get((gw.id, player.team_id), [])
            result = project_player_gameweek(
                player, player_fixtures, strength, rules, matches_played,
                median_cost=median_cost,
            )
            c = result.components
            db.add(Projection(
                player_id=player.id,
                gameweek_id=gw.id,
                model_version=MODEL_VERSION,
                xpts=result.xpts,
                variance=result.variance,
                expected_minutes=result.minutes.expected_minutes,
                p_start=result.minutes.p_start,
                p_appear=result.minutes.p_appear,
                p_60_plus=result.minutes.p_60,
                availability_multiplier=result.minutes.availability,
                xpts_appearance=c["appearance"],
                xpts_goals=c["goals"],
                xpts_assists=c["assists"],
                xpts_clean_sheet=c["clean_sheet"],
                xpts_goals_conceded=c["goals_conceded"],
                xpts_saves=c["saves"],
                xpts_defensive_contribution=c["defensive_contribution"],
                xpts_bonus=c["bonus"],
                xpts_cards=c["cards"],
                xpts_penalties=c["penalties"],
                fixture_count=result.fixture_count,
                expected_team_goals=result.expected_team_goals,
                expected_team_conceded=result.expected_team_conceded,
                custom_fdr=result.custom_fdr,
                opponents=result.opponents,
                updated_at=utcnow(),
            ))
            written += 1

    await db.commit()
    return {
        "model_version": MODEL_VERSION,
        "gameweeks": gw_ids,
        "players": len(players),
        "written": written,
        "matches_played": matches_played,
    }
