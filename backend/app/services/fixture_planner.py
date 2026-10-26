"""
The fixture planner: every club's next few gameweeks, rated for attackers and
for defenders.

The difficulty comes from the same team-strength ratings the projections use,
not FPL's fixed 1-5 scale. For defenders it is the goals the club is expected
to concede (the model's custom FDR); for attackers, the goals it is expected
to score, on the same 1 (easiest) to 5 (hardest) scale. Overall is the mean.

Doubles and blanks are what a planner is for, so a club is ranked on the sum
of how easy each fixture is (6 minus its difficulty) across the window: a
double counts twice and a blank counts nothing, which is how they score.
Before any ratings exist, FPL's own difficulty stands in for all three.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fpl import Fixture, Gameweek, Team
from app.services.fpl_sync import get_next_open_gameweek
from app.services.team_strength import expected_goals_for_fixture, fdr_from_expected_goals, load_strength_map

VIEWS = ("overall", "attack", "defence")


def attack_difficulty(expected_scored: float) -> float:
    """Expected goals scored on the FDR scale: many goals is an easy fixture."""
    return round(6.0 - fdr_from_expected_goals(expected_scored), 2)


async def plan(db: AsyncSession, gameweeks: int = 6) -> dict:
    start = await get_next_open_gameweek(db)
    if start is None:
        return {"gameweeks": [], "teams": [], "source": None}
    gws = (await db.execute(
        select(Gameweek.id).where(Gameweek.id >= start.id).order_by(Gameweek.id).limit(gameweeks)
    )).scalars().all()
    fixtures = (await db.execute(
        select(Fixture).where(Fixture.gameweek_id.in_(gws)).order_by(Fixture.kickoff_time)
    )).scalars().all()
    teams = (await db.execute(select(Team))).scalars().all()
    short = {t.id: t.short_name for t in teams}
    strength = await load_strength_map(db)

    def rate(team: int, opponent: int, home: bool, fpl: int) -> dict:
        if not strength:
            return {"overall": float(fpl), "attack": float(fpl), "defence": float(fpl)}
        scored = expected_goals_for_fixture(strength, team, opponent, home)
        conceded = expected_goals_for_fixture(strength, opponent, team, not home)
        attack, defence = attack_difficulty(scored), fdr_from_expected_goals(conceded)
        return {"overall": round((attack + defence) / 2, 2), "attack": attack, "defence": defence}

    cells: dict[int, dict[int, list[dict]]] = {t.id: {gw: [] for gw in gws} for t in teams}
    for f in fixtures:
        for team, opponent, home, fpl in (
            (f.team_h, f.team_a, True, f.team_h_difficulty),
            (f.team_a, f.team_h, False, f.team_a_difficulty),
        ):
            if team in cells:
                cells[team][f.gameweek_id].append({
                    "opponent": short.get(opponent, "?"), "home": home, "fpl": fpl, **rate(team, opponent, home, fpl),
                })

    rows = []
    for t in teams:
        by_gw = cells[t.id]
        rows.append({
            "team_id": t.id,
            "team": t.short_name,
            "name": t.name,
            "fixtures": [{"gameweek": gw, "matches": by_gw[gw]} for gw in gws],
            "ease": {v: round(sum(6.0 - m[v] for gw in gws for m in by_gw[gw]), 2) for v in VIEWS},
            "doubles": [gw for gw in gws if len(by_gw[gw]) > 1],
            "blanks": [gw for gw in gws if not by_gw[gw]],
        })
    rows.sort(key=lambda r: -r["ease"]["overall"])
    return {"gameweeks": list(gws), "teams": rows, "source": "model" if strength else "fpl"}
