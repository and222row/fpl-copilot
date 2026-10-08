"""
Multi-gameweek transfer planner.

Blueprint §12: "model transfers as state transitions. Compare 'transfer now'
against 'roll' and against alternative paths." Blueprint §15 asks for the
result as a branching decision tree rather than a flat table.

Why a search rather than one big optimisation: the true problem is choosing a
squad for every gameweek in the horizon at once, and its state space is
astronomically large — 15 players drawn from ~600, times bank, times banked
free transfers, times horizon length. What actually matters to a manager is
narrower and answerable: *when* to spend transfers, and whether a hit is worth
taking. So the search branches on that decision (roll / one transfer / two with
a hit), solves the single-gameweek optimiser at each node, and keeps the most
promising states via beam search.

The result is a genuine tree the UI can draw, with squad state and cumulative
points at every node, and the pruned branches retained so a user can see what
was considered and rejected.
"""
import logging
from dataclasses import dataclass, field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models.fpl import Player, Team, Gameweek
from app.models.projections import Projection
from app.services.projection import MODEL_VERSION
from app.services.lineup import best_xi_total
from app.services.transfers import (
    TransferCandidate, optimise_transfers, HIT_COST, MAX_PER_CLUB,
    SQUAD_COMPOSITION,
)

logger = logging.getLogger("fpl_copilot")

PLANNER_VERSION = "plan-v1"

# Verified against bootstrap-static `game_config.rules`:
# max_extra_free_transfers = 4, so one per gameweek plus four banked.
MAX_FREE_TRANSFERS = 5

# Actions branched on at each gameweek. Two transfers is the practical ceiling
# for a planner — beyond that a wildcard is the better instrument, and the
# branching factor makes the search unusable.
ACTIONS = (0, 1, 2)


def next_free_transfers(current: int, used: int) -> int:
    """
    Free transfers carried into the following gameweek.

    Unused transfers roll over and one is added each week, capped at five.
    Transfers taken as a hit do not consume banked ones, so the floor is what
    remains after spending at most `current`.
    """
    remaining = max(0, current - used)
    return min(MAX_FREE_TRANSFERS, remaining + 1)


@dataclass
class PlanNode:
    """One decision point in the tree."""
    id: int
    parent_id: int | None
    gameweek: int
    depth: int

    # The decision taken to arrive here
    transfers: int
    hit: int
    players_in: list[dict] = field(default_factory=list)
    players_out: list[dict] = field(default_factory=list)

    # Resulting state
    squad_ids: frozenset[int] = frozenset()
    bank: int = 0
    free_transfers: int = 1

    # Value
    gw_xpts: float = 0.0            # best XI this gameweek
    cumulative_xpts: float = 0.0    # net of hits, from the start of the horizon
    remaining_value: float = 0.0    # squad value over the rest of the horizon

    pruned: bool = False
    on_best_path: bool = False

    @property
    def action_label(self) -> str:
        if self.transfers == 0:
            return "Roll"
        if self.hit > 0:
            return f"{self.transfers} transfers (−{self.hit})"
        return "1 transfer" if self.transfers == 1 else f"{self.transfers} transfers"


@dataclass
class PlannerResult:
    horizon: list[int]
    nodes: list[PlanNode]
    best_path: list[PlanNode]
    beam_width: int
    solves: int
    requested_horizon: int = 0


async def _load_horizon(
    db: AsyncSession, start_gw: int, horizon: int
) -> tuple[list[int], dict[tuple[int, int], float], dict[int, Player], dict[int, str]]:
    """
    Projections for every player across the horizon, keyed by (player, gw).

    The horizon is truncated to gameweeks that actually have projections.
    Without this the search happily plans into gameweeks with no data, which
    contributes zero points per node and quietly wastes a level of the tree
    while making the totals look complete.
    """
    requested = (await db.execute(
        select(Gameweek.id).where(Gameweek.id >= start_gw)
        .order_by(Gameweek.id).limit(horizon)
    )).scalars().all()

    if not requested:
        return [], {}, {}, {}

    projected = set((await db.execute(
        select(Projection.gameweek_id)
        .where(
            Projection.gameweek_id.in_(requested),
            Projection.model_version == MODEL_VERSION,
        )
        .distinct()
    )).scalars().all())

    # Keep the leading run that has data; a gap ends the horizon rather than
    # producing a plan with a hole in it.
    gw_ids: list[int] = []
    for gw_id in requested:
        if gw_id not in projected:
            break
        gw_ids.append(gw_id)

    if not gw_ids:
        return [], {}, {}, {}

    rows = (await db.execute(
        select(Projection.player_id, Projection.gameweek_id, Projection.xpts)
        .where(
            Projection.gameweek_id.in_(gw_ids),
            Projection.model_version == MODEL_VERSION,
        )
    )).all()
    xpts = {(pid, gw): float(v) for pid, gw, v in rows}

    player_rows = (await db.execute(
        select(Player, Team.short_name).join(Team, Team.id == Player.team_id)
    )).all()
    players = {p.id: p for p, _ in player_rows}
    teams = {p.id: short for p, short in player_rows}

    return list(gw_ids), xpts, players, teams


def _squad_gw_points(
    squad_ids: frozenset[int],
    gw: int,
    xpts: dict[tuple[int, int], float],
    players: dict[int, Player],
) -> float:
    """Best legal XI from this squad for one gameweek."""
    entries = [
        (pid, players[pid].position, xpts.get((pid, gw), 0.0))
        for pid in squad_ids
        if pid in players
    ]
    total, _ = best_xi_total(entries)
    return total


def _remaining_value(
    squad_ids: frozenset[int],
    from_gw_index: int,
    gw_ids: list[int],
    xpts: dict[tuple[int, int], float],
    players: dict[int, Player],
) -> float:
    """
    What this squad is worth over the rest of the horizon if left alone.

    Used to rank beam candidates: a state that looks good this week but leaves
    a weak squad for the next four should not survive pruning.
    """
    return sum(
        _squad_gw_points(squad_ids, gw_ids[i], xpts, players)
        for i in range(from_gw_index, len(gw_ids))
    )


async def plan_horizon(
    db: AsyncSession,
    *,
    squad_ids: list[int],
    bank: int,
    free_transfers: int,
    start_gw: int,
    horizon: int = 5,
    beam_width: int = 3,
    max_transfers_per_gw: int = 2,
    pool_per_position: int = 30,
) -> PlannerResult:
    """
    Search transfer paths across the horizon and return the tree.

    Beam search: at each gameweek every surviving state branches on how many
    transfers to make, the single-gameweek optimiser picks *which* players, and
    only the best `beam_width` states continue. Without pruning the tree is
    3^horizon paths, each needing a solver run.
    """
    gw_ids, xpts, players, teams = await _load_horizon(db, start_gw, horizon)
    if not gw_ids:
        raise ValueError("No gameweeks in horizon")
    if not xpts:
        raise ValueError(
            "No projections for the horizon. Run POST /api/v1/projections/rebuild first."
        )

    owned = frozenset(pid for pid in squad_ids if pid in players)
    if len(owned) < 15:
        raise ValueError(
            f"Only {len(owned)} of {len(squad_ids)} squad players are in our "
            f"database. Re-sync FPL data."
        )

    # Candidate pool: strongest projected players per position over the horizon.
    # Deliberately small — the planner runs one solve per node, so pool size is
    # the dominant cost.
    horizon_total: dict[int, float] = {}
    for (pid, gw), v in xpts.items():
        horizon_total[pid] = horizon_total.get(pid, 0.0) + v

    pool_by_pos: dict[int, list[int]] = {}
    for pid, total in sorted(horizon_total.items(), key=lambda kv: -kv[1]):
        p = players.get(pid)
        if p is None or pid in owned or p.status != "a":
            continue
        bucket = pool_by_pos.setdefault(p.position, [])
        if len(bucket) < pool_per_position:
            bucket.append(pid)
    pool_ids = [pid for ids in pool_by_pos.values() for pid in ids]

    def brief(pid: int) -> dict:
        p = players[pid]
        return {
            "player_id": pid,
            "name": p.web_name,
            "team": teams.get(pid, ""),
            "position": p.position,
            "price": round(p.now_cost / 10, 1),
            # The plan holds prices fixed. This lets the app warn that a buy
            # planned for a later gameweek may cost more by then.
            "price_change_percent": p.price_change_percent,
        }

    nodes: list[PlanNode] = []
    counter = 0
    solves = 0

    def new_node(**kwargs) -> PlanNode:
        nonlocal counter
        node = PlanNode(id=counter, **kwargs)
        counter += 1
        nodes.append(node)
        return node

    # Root: the squad as it stands, before any decision.
    root = new_node(
        parent_id=None,
        gameweek=gw_ids[0],
        depth=0,
        transfers=0,
        hit=0,
        squad_ids=owned,
        bank=bank,
        free_transfers=free_transfers,
        gw_xpts=0.0,
        cumulative_xpts=0.0,
        remaining_value=_remaining_value(owned, 0, gw_ids, xpts, players),
    )

    beam: list[PlanNode] = [root]

    for depth, gw in enumerate(gw_ids):
        candidates: list[PlanNode] = []

        for state in beam:
            # Value of each player from this gameweek to the end of the horizon
            def horizon_value(pid: int) -> float:
                return sum(xpts.get((pid, g), 0.0) for g in gw_ids[depth:])

            owned_candidates = [
                TransferCandidate(
                    player=players[pid],
                    horizon_xpts=horizon_value(pid),
                    team_short=teams.get(pid, ""),
                )
                for pid in state.squad_ids
            ]
            pool_candidates = [
                TransferCandidate(
                    player=players[pid],
                    horizon_xpts=horizon_value(pid),
                    team_short=teams.get(pid, ""),
                )
                for pid in pool_ids
                if pid not in state.squad_ids
            ]

            for n_transfers in ACTIONS:
                if n_transfers > max_transfers_per_gw:
                    continue

                if n_transfers == 0:
                    new_squad = state.squad_ids
                    new_bank = state.bank
                    hit = 0
                    ins: list[dict] = []
                    outs: list[dict] = []
                else:
                    plan = optimise_transfers(
                        owned_candidates,
                        pool_candidates,
                        bank=state.bank,
                        free_transfers=state.free_transfers,
                        max_transfers=n_transfers,
                        time_limit_seconds=3.0,
                    )
                    solves += 1
                    if not plan.feasible or plan.transfers_made == 0:
                        # Nothing better available; identical to rolling, so
                        # skip rather than duplicating the branch.
                        continue

                    out_ids = {p["player_id"] for p in plan.players_out}
                    in_ids = {p["player_id"] for p in plan.players_in}
                    new_squad = (state.squad_ids - out_ids) | in_ids
                    new_bank = int(round(plan.bank_after * 10))
                    hit = plan.hit
                    ins = [brief(pid) for pid in in_ids]
                    outs = [brief(pid) for pid in out_ids]
                    n_transfers = plan.transfers_made

                gw_points = _squad_gw_points(new_squad, gw, xpts, players)
                node = new_node(
                    parent_id=state.id,
                    gameweek=gw,
                    depth=depth + 1,
                    transfers=n_transfers,
                    hit=hit,
                    players_in=ins,
                    players_out=outs,
                    squad_ids=new_squad,
                    bank=new_bank,
                    free_transfers=next_free_transfers(state.free_transfers, n_transfers),
                    gw_xpts=round(gw_points, 2),
                    cumulative_xpts=round(
                        state.cumulative_xpts + gw_points - hit, 2
                    ),
                    remaining_value=round(
                        _remaining_value(new_squad, depth + 1, gw_ids, xpts, players), 2
                    ),
                )
                candidates.append(node)

        if not candidates:
            break

        # Rank on points banked so far plus what the squad is still worth.
        # Ranking on cumulative points alone would favour hoarding transfers.
        candidates.sort(
            key=lambda n: n.cumulative_xpts + n.remaining_value, reverse=True
        )
        beam = candidates[:beam_width]
        for n in candidates[beam_width:]:
            n.pruned = True

    # Walk back from the best leaf
    leaves = [n for n in nodes if n.depth == len(gw_ids)] or beam
    best_leaf = max(leaves, key=lambda n: n.cumulative_xpts, default=root)

    by_id = {n.id: n for n in nodes}
    path: list[PlanNode] = []
    cursor: PlanNode | None = best_leaf
    while cursor is not None:
        cursor.on_best_path = True
        path.append(cursor)
        cursor = by_id.get(cursor.parent_id) if cursor.parent_id is not None else None
    path.reverse()

    return PlannerResult(
        horizon=gw_ids,
        nodes=nodes,
        best_path=path,
        beam_width=beam_width,
        solves=solves,
        requested_horizon=horizon,
    )


def serialise(result: PlannerResult, players: dict[int, Player] | None = None) -> dict:
    """Shape the tree for the UI."""
    def node_dict(n: PlanNode) -> dict:
        return {
            "id": n.id,
            "parent_id": n.parent_id,
            "gameweek": n.gameweek,
            "depth": n.depth,
            "action": n.action_label,
            "transfers": n.transfers,
            "hit": n.hit,
            "in": n.players_in,
            "out": n.players_out,
            "bank": round(n.bank / 10, 1),
            "free_transfers": n.free_transfers,
            "gw_xpts": n.gw_xpts,
            "cumulative_xpts": n.cumulative_xpts,
            "remaining_value": n.remaining_value,
            "pruned": n.pruned,
            "on_best_path": n.on_best_path,
        }

    best = result.best_path
    total_hits = sum(n.hit for n in best)
    total_transfers = sum(n.transfers for n in best)

    truncated = (
        result.requested_horizon > len(result.horizon) if result.requested_horizon else False
    )

    return {
        "planner_version": PLANNER_VERSION,
        "horizon": result.horizon,
        "requested_horizon": result.requested_horizon,
        "horizon_truncated": truncated,
        "truncation_note": (
            f"Only {len(result.horizon)} of {result.requested_horizon} requested "
            f"gameweeks have projections. Rebuild with a longer horizon to plan "
            f"further ahead."
        ) if truncated else None,
        "beam_width": result.beam_width,
        "optimiser_solves": result.solves,
        "best_path": {
            "total_xpts": best[-1].cumulative_xpts if best else 0.0,
            "total_hits": total_hits,
            "total_transfers": total_transfers,
            "steps": [node_dict(n) for n in best if n.depth > 0],
        },
        "tree": [node_dict(n) for n in result.nodes],
    }
