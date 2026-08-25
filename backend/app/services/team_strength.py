"""
Custom Fixture Difficulty Rating.

FPL's built-in FDR is a coarse 1-5 integer set before the season and rarely
updated. This module derives continuous expected-goals ratings per team by
shrinking observed season results toward a prior built from FPL's own
strength numbers.

The shrinkage matters: early in a season a team with one 4-0 win is not a
4-goals-per-game team. `PRIOR_MATCHES` controls how many matches of real
data it takes for observation to outweigh the prior.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.fpl import Team, Fixture
from app.models.projections import TeamStrength
from app.models.fpl import utcnow

MODEL_VERSION = "fdr-v1"

# League-average goals per team per match, split by venue.
# Home teams score more; this is the baseline every team is measured against.
LEAGUE_HOME_GOALS = 1.50
LEAGUE_AWAY_GOALS = 1.20

# Effective number of "prior matches". With PRIOR_MATCHES = 6, after 6 real
# matches the prior and the observation carry equal weight.
PRIOR_MATCHES = 6.0

# FPL publishes strength_attack/defence on roughly a 1000-1400 scale.
# We map them to a multiplier around 1.0.
FPL_STRENGTH_MIDPOINT = 1150.0
FPL_STRENGTH_SPREAD = 300.0


def _strength_to_multiplier(value: int) -> float:
    """
    Map an FPL strength rating to a multiplier centred on 1.0.

    A team 1 spread above the midpoint gets ~1.3x, one below gets ~0.7x.
    Clamped so a bad rating can never produce a non-positive expectation.
    """
    if not value:
        return 1.0
    raw = 1.0 + (value - FPL_STRENGTH_MIDPOINT) / FPL_STRENGTH_SPREAD * 0.3
    return max(0.5, min(1.8, raw))


async def rebuild_team_strength(db: AsyncSession) -> dict:
    """
    Recompute attack/defence ratings for every team and upsert them.

    Uses only finished fixtures with recorded scores.
    """
    teams = (await db.execute(select(Team))).scalars().all()
    # `finished_provisional` is the flag that means "played". `finished` only
    # flips once FPL verifies the data, which can lag by days.
    fixtures = (await db.execute(
        select(Fixture).where(
            (Fixture.finished.is_(True)) | (Fixture.finished_provisional.is_(True)),
            Fixture.team_h_score.is_not(None),
            Fixture.team_a_score.is_not(None),
        )
    )).scalars().all()

    # Tally actual goals for and against, by venue
    tally: dict[int, dict[str, float]] = {
        t.id: {"gf_h": 0.0, "ga_h": 0.0, "n_h": 0.0, "gf_a": 0.0, "ga_a": 0.0, "n_a": 0.0}
        for t in teams
    }
    for f in fixtures:
        if f.team_h in tally:
            tally[f.team_h]["gf_h"] += f.team_h_score
            tally[f.team_h]["ga_h"] += f.team_a_score
            tally[f.team_h]["n_h"] += 1
        if f.team_a in tally:
            tally[f.team_a]["gf_a"] += f.team_a_score
            tally[f.team_a]["ga_a"] += f.team_h_score
            tally[f.team_a]["n_a"] += 1

    updated = 0
    for team in teams:
        t = tally[team.id]
        matches = t["n_h"] + t["n_a"]

        # Prior from FPL strength ratings
        prior_atk_h = LEAGUE_HOME_GOALS * _strength_to_multiplier(team.strength_attack_home)
        prior_atk_a = LEAGUE_AWAY_GOALS * _strength_to_multiplier(team.strength_attack_away)
        # A HIGH defence strength means hard to score against -> concede fewer.
        prior_def_h = LEAGUE_AWAY_GOALS / _strength_to_multiplier(team.strength_defence_home)
        prior_def_a = LEAGUE_HOME_GOALS / _strength_to_multiplier(team.strength_defence_away)

        # Observation, per venue, falling back to the other venue when a team
        # has not yet played at this one.
        obs_atk_h = t["gf_h"] / t["n_h"] if t["n_h"] else None
        obs_atk_a = t["gf_a"] / t["n_a"] if t["n_a"] else None
        obs_def_h = t["ga_h"] / t["n_h"] if t["n_h"] else None
        obs_def_a = t["ga_a"] / t["n_a"] if t["n_a"] else None

        def blend(prior: float, obs: float | None, n: float) -> float:
            """Weighted mean of prior and observation; n = matches observed."""
            if obs is None or n <= 0:
                return prior
            w = n / (n + PRIOR_MATCHES)
            return prior * (1 - w) + obs * w

        row = (await db.execute(
            select(TeamStrength).where(
                TeamStrength.team_id == team.id,
                TeamStrength.model_version == MODEL_VERSION,
            )
        )).scalars().first()
        if row is None:
            row = TeamStrength(team_id=team.id, model_version=MODEL_VERSION)
            db.add(row)

        row.matches_played = int(matches)
        row.attack_home = round(blend(prior_atk_h, obs_atk_h, t["n_h"]), 4)
        row.attack_away = round(blend(prior_atk_a, obs_atk_a, t["n_a"]), 4)
        row.defence_home = round(blend(prior_def_h, obs_def_h, t["n_h"]), 4)
        row.defence_away = round(blend(prior_def_a, obs_def_a, t["n_a"]), 4)
        row.observed_scored_per_match = round(
            (t["gf_h"] + t["gf_a"]) / matches, 4
        ) if matches else 0.0
        row.observed_conceded_per_match = round(
            (t["ga_h"] + t["ga_a"]) / matches, 4
        ) if matches else 0.0
        row.prior_weight = round(PRIOR_MATCHES / (matches + PRIOR_MATCHES), 4)
        row.updated_at = utcnow()
        updated += 1

    await db.commit()
    return {
        "teams_updated": updated,
        "fixtures_used": len(fixtures),
        "model_version": MODEL_VERSION,
    }


async def load_strength_map(db: AsyncSession) -> dict[int, TeamStrength]:
    rows = (await db.execute(
        select(TeamStrength).where(TeamStrength.model_version == MODEL_VERSION)
    )).scalars().all()
    return {r.team_id: r for r in rows}


def expected_goals_for_fixture(
    strength: dict[int, TeamStrength],
    attacking_team: int,
    defending_team: int,
    attacking_at_home: bool,
) -> float:
    """
    Expected goals for `attacking_team` against `defending_team`.

    Combines the attack rating with the opponent's defensive concession rate,
    normalised by the league baseline so the two signals multiply rather than
    double-count.
    """
    atk = strength.get(attacking_team)
    dfn = strength.get(defending_team)
    baseline = LEAGUE_HOME_GOALS if attacking_at_home else LEAGUE_AWAY_GOALS

    if atk is None or dfn is None:
        return baseline

    attack = atk.attack_home if attacking_at_home else atk.attack_away
    # Defence rating is goals the opponent concedes at THIS venue
    concede = dfn.defence_away if attacking_at_home else dfn.defence_home

    expected = attack * (concede / baseline)
    return max(0.15, min(5.0, expected))


def fdr_from_expected_goals(expected_conceded: float) -> float:
    """
    Map expected goals conceded to a 1-5 FDR-style scale for display.

    1 = easiest fixture (few goals expected against), 5 = hardest.
    """
    # ~0.7 xGC is a very easy fixture, ~2.4 is very hard
    scaled = 1.0 + (expected_conceded - 0.7) / (2.4 - 0.7) * 4.0
    return round(max(1.0, min(5.0, scaled)), 2)
