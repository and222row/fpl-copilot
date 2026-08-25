"""
Starting XI, bench order and captaincy.

These are small enough to solve exactly by enumeration — there are only eight
legal formations — so no solver is involved and the answer is provably optimal
rather than heuristic.

Squad rules (verified against bootstrap-static `element_types`):
    squad     2 GKP, 5 DEF, 5 MID, 3 FWD  = 15
    XI        1 GKP, 3-5 DEF, 2-5 MID, 1-3 FWD = 11
"""
from dataclasses import dataclass, field
from app.models.fpl import Player
from app.models.projections import Projection

POS_GKP, POS_DEF, POS_MID, POS_FWD = 1, 2, 3, 4
POS_NAME = {POS_GKP: "GKP", POS_DEF: "DEF", POS_MID: "MID", POS_FWD: "FWD"}

# Legal outfield shapes as (DEF, MID, FWD). Derived from the position
# min/max play limits; all sum to 10 outfield players.
FORMATIONS: list[tuple[int, int, int]] = [
    (3, 4, 3), (3, 5, 2),
    (4, 3, 3), (4, 4, 2), (4, 5, 1),
    (5, 2, 3), (5, 3, 2), (5, 4, 1),
]


@dataclass
class SquadEntry:
    """One owned player, paired with his projection for the target gameweek."""
    player: Player
    projection: Projection | None
    team_short: str = ""

    @property
    def xpts(self) -> float:
        return self.projection.xpts if self.projection else 0.0

    @property
    def variance(self) -> float:
        return self.projection.variance if self.projection else 0.0

    @property
    def p_start(self) -> float:
        return self.projection.p_start if self.projection else 0.0

    @property
    def p_appear(self) -> float:
        return self.projection.p_appear if self.projection else 0.0

    @property
    def position(self) -> int:
        return self.player.position

    def brief(self) -> dict:
        p = self.player
        return {
            "player_id": p.id,
            "name": p.web_name,
            "team": self.team_short,
            "position": POS_NAME.get(p.position, "UNK"),
            "price": round(p.now_cost / 10, 1),
            "xpts": round(self.xpts, 2),
            "p_start": round(self.p_start, 3),
            "status": p.status,
        }


@dataclass
class LineupResult:
    formation: str
    starting: list[SquadEntry]
    bench: list[SquadEntry]
    starting_xpts: float
    bench_xpts: float
    captain: SquadEntry | None = None
    vice_captain: SquadEntry | None = None
    considered: list[dict] = field(default_factory=list)


def best_starting_xi(squad: list[SquadEntry]) -> LineupResult:
    """
    Pick the highest-xPts legal XI.

    Enumerates all eight formations; within a formation the best choice is
    simply the top-N by xPts per position, so the overall result is exact.
    """
    by_pos: dict[int, list[SquadEntry]] = {POS_GKP: [], POS_DEF: [], POS_MID: [], POS_FWD: []}
    for entry in squad:
        by_pos.setdefault(entry.position, []).append(entry)
    for entries in by_pos.values():
        entries.sort(key=lambda e: e.xpts, reverse=True)

    if not by_pos[POS_GKP]:
        raise ValueError("Squad has no goalkeeper")

    best: LineupResult | None = None
    considered: list[dict] = []

    for n_def, n_mid, n_fwd in FORMATIONS:
        if (len(by_pos[POS_DEF]) < n_def or len(by_pos[POS_MID]) < n_mid
                or len(by_pos[POS_FWD]) < n_fwd):
            continue

        starting = (
            by_pos[POS_GKP][:1]
            + by_pos[POS_DEF][:n_def]
            + by_pos[POS_MID][:n_mid]
            + by_pos[POS_FWD][:n_fwd]
        )
        total = sum(e.xpts for e in starting)
        considered.append({
            "formation": f"{n_def}-{n_mid}-{n_fwd}",
            "xpts": round(total, 2),
        })

        if best is None or total > best.starting_xpts:
            starting_ids = {e.player.id for e in starting}
            bench = [e for e in squad if e.player.id not in starting_ids]
            best = LineupResult(
                formation=f"{n_def}-{n_mid}-{n_fwd}",
                starting=starting,
                bench=bench,
                starting_xpts=round(total, 2),
                bench_xpts=round(sum(e.xpts for e in bench), 2),
            )

    if best is None:
        raise ValueError("No legal formation possible from this squad")

    best.bench = order_bench(best.bench)
    best.considered = sorted(considered, key=lambda c: c["xpts"], reverse=True)
    return best


def order_bench(bench: list[SquadEntry]) -> list[SquadEntry]:
    """
    Order the bench for autosubs.

    The reserve keeper is separated out: he can only ever replace the starting
    keeper, so he does not compete with outfield players for a slot. Outfield
    subs are ranked by expected contribution if called upon — xPts weighted by
    the chance the player actually appears, since a sub who is himself doubtful
    is worth little as cover.
    """
    keepers = [e for e in bench if e.position == POS_GKP]
    outfield = [e for e in bench if e.position != POS_GKP]
    outfield.sort(key=lambda e: e.xpts * max(e.p_appear, 0.01), reverse=True)
    return keepers + outfield


def best_xi_total(players: list[tuple[int, int, float]]) -> tuple[float, list[int]]:
    """
    Highest-scoring legal XI from raw (player_id, position, xpts) tuples.

    A lightweight twin of `best_starting_xi` for callers that have plain
    numbers rather than SquadEntry objects — the planner evaluates thousands of
    candidate squads and building ORM-backed entries for each would dominate
    its runtime.
    """
    by_pos: dict[int, list[tuple[int, float]]] = {
        POS_GKP: [], POS_DEF: [], POS_MID: [], POS_FWD: []
    }
    for pid, position, xpts in players:
        by_pos.setdefault(position, []).append((pid, xpts))
    for entries in by_pos.values():
        entries.sort(key=lambda e: e[1], reverse=True)

    if not by_pos[POS_GKP]:
        return 0.0, []

    best_total = -1.0
    best_ids: list[int] = []

    for n_def, n_mid, n_fwd in FORMATIONS:
        if (len(by_pos[POS_DEF]) < n_def or len(by_pos[POS_MID]) < n_mid
                or len(by_pos[POS_FWD]) < n_fwd):
            continue
        picked = (
            by_pos[POS_GKP][:1]
            + by_pos[POS_DEF][:n_def]
            + by_pos[POS_MID][:n_mid]
            + by_pos[POS_FWD][:n_fwd]
        )
        total = sum(x for _, x in picked)
        if total > best_total:
            best_total = total
            best_ids = [pid for pid, _ in picked]

    return (round(best_total, 3), best_ids) if best_total >= 0 else (0.0, [])


# ── Captaincy ────────────────────────────────────────────────────────────────

def captain_candidates(
    starting: list[SquadEntry],
    mode: str = "balanced",
    top_n: int = 5,
) -> list[dict]:
    """
    Rank captain options.

    The captain doubles a player's score, which doubles his variance too. The
    three modes trade expected points against certainty:

      safe         penalise variance and rotation risk — protect a good rank
      balanced     rank on expected captain points alone
      differential reward low ownership — chase rank rather than protect it
    """
    scored: list[dict] = []

    for entry in starting:
        expected = entry.xpts * 2.0
        ownership = entry.player.selected_by_percent or 0.0

        if mode == "safe":
            # Penalise uncertainty: a doubled blank is the worst outcome.
            score = expected - entry.variance * 0.45 - (1.0 - entry.p_start) * 4.0
            rationale = "expected points, penalised for variance and rotation risk"
        elif mode == "differential":
            # Captaining a widely-owned player gains nothing on the field.
            score = expected + (100.0 - ownership) / 100.0 * 2.2
            rationale = "expected points, rewarded for low ownership"
        else:
            score = expected
            rationale = "expected captain points"

        scored.append({
            **entry.brief(),
            "expected_captain_points": round(expected, 2),
            "score": round(score, 3),
            "variance": round(entry.variance, 2),
            "ownership": ownership,
            "mode": mode,
            "rationale": rationale,
        })

    scored.sort(key=lambda c: c["score"], reverse=True)
    return scored[:top_n]


def pick_captain_and_vice(
    starting: list[SquadEntry],
    mode: str = "balanced",
) -> tuple[SquadEntry | None, SquadEntry | None, list[dict]]:
    """
    Choose captain and vice.

    The vice only scores when the captain does not appear, so he is picked for
    reliability first — a high-ceiling vice who is himself a rotation risk
    defeats the purpose of having one.
    """
    ranked = captain_candidates(starting, mode=mode, top_n=len(starting))
    if not ranked:
        return None, None, []

    by_id = {e.player.id: e for e in starting}
    captain = by_id[ranked[0]["player_id"]]

    vice_pool = [
        e for e in starting
        if e.player.id != captain.player.id and e.player.team_id != captain.player.team_id
    ]
    # Falling back to same-club is better than having no vice at all.
    if not vice_pool:
        vice_pool = [e for e in starting if e.player.id != captain.player.id]

    vice = max(vice_pool, key=lambda e: e.xpts * e.p_start, default=None) if vice_pool else None
    return captain, vice, ranked[:5]
