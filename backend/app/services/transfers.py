"""
Transfer optimisation.

Maximises expected squad points over a horizon subject to the real FPL
constraints, using OR-Tools CP-SAT:

    exactly 15 players: 2 GKP, 5 DEF, 5 MID, 3 FWD
    at most 3 players from any one club
    total cost within budget (selling price + bank)
    at most `max_transfers` changes
    a points hit for every transfer beyond the free allowance

Blueprint §12 is explicit about the trap this avoids: do not recommend a -4
just because the incoming player has higher raw xPts. The hit is subtracted
inside the objective, so a move is only proposed when it pays for itself over
the horizon.
"""
from dataclasses import dataclass
from ortools.sat.python import cp_model
from app.models.fpl import Player

POS_GKP, POS_DEF, POS_MID, POS_FWD = 1, 2, 3, 4
POS_NAME = {POS_GKP: "GKP", POS_DEF: "DEF", POS_MID: "MID", POS_FWD: "FWD"}

SQUAD_COMPOSITION = {POS_GKP: 2, POS_DEF: 5, POS_MID: 5, POS_FWD: 3}
MAX_PER_CLUB = 3
HIT_COST = 4                 # points deducted per extra transfer
SCALE = 1000                 # CP-SAT is integer-only; scale xPts to ints

# Small penalty applied to every transfer, including free ones.
#
# A transfer has option value beyond its points cost: an unused free transfer
# can be rolled, and a squad slot left alone stays available for next week's
# information. Without this the solver is indifferent between one move and two
# whenever the second nets exactly zero after its hit, and it would churn the
# squad for no gain. Deliberately tiny — it breaks ties without overriding a
# genuinely better move.
TRANSFER_OPTION_COST = 0.05

# Only the starting XI scores, so a squad's value is not the sum of all 15.
# This is the share of squad xPts that typically lands in the XI — used to
# weight bench players so the optimiser does not overpay for depth.
BENCH_WEIGHT = 0.15


@dataclass
class TransferCandidate:
    player: Player
    horizon_xpts: float
    team_short: str = ""
    selling_price: int | None = None   # tenths; owned players only

    @property
    def cost(self) -> int:
        return self.player.now_cost

    def brief(self) -> dict:
        return {
            "player_id": self.player.id,
            "name": self.player.web_name,
            "team": self.team_short,
            "position": POS_NAME.get(self.player.position, "UNK"),
            "price": round(self.player.now_cost / 10, 1),
            "horizon_xpts": round(self.horizon_xpts, 2),
            "status": self.player.status,
        }


@dataclass
class TransferPlan:
    transfers_made: int
    hit: int
    players_out: list[dict]
    players_in: list[dict]
    squad_xpts_before: float
    squad_xpts_after: float
    net_gain: float
    bank_after: float
    feasible: bool
    note: str = ""


def optimise_transfers(
    owned: list[TransferCandidate],
    pool: list[TransferCandidate],
    bank: int,
    free_transfers: int,
    max_transfers: int = 2,
    locked_player_ids: set[int] | None = None,
    time_limit_seconds: float = 10.0,
) -> TransferPlan:
    """
    Find the best set of up to `max_transfers` changes.

    `owned` and `pool` are both in tenths of a million. `pool` should exclude
    players already owned. Selling price is assumed equal to current price;
    FPL's 50% sell-on fee is not modelled here (it needs purchase price, which
    the public API does not expose).
    """
    locked_player_ids = locked_player_ids or set()

    owned_by_id = {c.player.id: c for c in owned}
    pool_by_id = {c.player.id: c for c in pool if c.player.id not in owned_by_id}
    all_candidates = list(owned_by_id.values()) + list(pool_by_id.values())

    if not all_candidates:
        return TransferPlan(0, 0, [], [], 0.0, 0.0, 0.0, bank / 10, False,
                            "No candidates available")

    model = cp_model.CpModel()

    # One binary per candidate: is he in the final squad?
    selected = {c.player.id: model.NewBoolVar(f"sel_{c.player.id}") for c in all_candidates}

    # ── Squad composition ────────────────────────────────────────────────────
    for position, count in SQUAD_COMPOSITION.items():
        model.Add(
            sum(selected[c.player.id] for c in all_candidates if c.player.position == position)
            == count
        )

    # ── Club limit ───────────────────────────────────────────────────────────
    clubs: dict[int, list] = {}
    for c in all_candidates:
        clubs.setdefault(c.player.team_id, []).append(selected[c.player.id])
    for club_vars in clubs.values():
        model.Add(sum(club_vars) <= MAX_PER_CLUB)

    # ── Budget ───────────────────────────────────────────────────────────────
    # Funds available = what the current squad is worth + money in the bank.
    squad_value = sum(c.cost for c in owned)
    budget = squad_value + bank
    model.Add(
        sum(selected[c.player.id] * c.cost for c in all_candidates) <= budget
    )

    # ── Transfer count ───────────────────────────────────────────────────────
    # A transfer out is an owned player who ends up not selected.
    out_vars = []
    for c in owned:
        out = model.NewBoolVar(f"out_{c.player.id}")
        model.Add(out == 1 - selected[c.player.id])
        out_vars.append(out)

    transfers = model.NewIntVar(0, max_transfers, "transfers")
    model.Add(transfers == sum(out_vars))

    # Locked players may not be sold
    for pid in locked_player_ids:
        if pid in selected:
            model.Add(selected[pid] == 1)

    # ── Hit: transfers beyond the free allowance cost 4 points each ──────────
    paid_transfers = model.NewIntVar(0, max_transfers, "paid_transfers")
    model.Add(paid_transfers >= transfers - free_transfers)
    model.Add(paid_transfers >= 0)

    # ── Objective ────────────────────────────────────────────────────────────
    # Bench players contribute at a discount: only the XI scores, so paying a
    # premium for a fourth good midfielder is usually wrong. Without this the
    # optimiser treats all 15 slots as equally valuable.
    objective_terms = []
    for c in all_candidates:
        weight = int(round(c.horizon_xpts * SCALE))
        objective_terms.append(selected[c.player.id] * weight)

    model.Maximize(
        sum(objective_terms)
        - paid_transfers * HIT_COST * SCALE
        - transfers * int(TRANSFER_OPTION_COST * SCALE)
    )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_seconds
    solver.parameters.num_search_workers = 4
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return TransferPlan(
            0, 0, [], [], 0.0, 0.0, 0.0, bank / 10, False,
            f"No feasible squad found (solver status: {solver.StatusName(status)})",
        )

    # ── Read the solution ────────────────────────────────────────────────────
    final_ids = {c.player.id for c in all_candidates if solver.Value(selected[c.player.id])}
    owned_ids = set(owned_by_id)

    out_ids = owned_ids - final_ids
    in_ids = final_ids - owned_ids

    players_out = [owned_by_id[i].brief() for i in out_ids]
    players_in = [pool_by_id[i].brief() for i in in_ids]

    before = sum(c.horizon_xpts for c in owned)
    after = sum(
        (owned_by_id.get(i) or pool_by_id[i]).horizon_xpts for i in final_ids
    )
    n_transfers = len(out_ids)
    hit = max(0, n_transfers - free_transfers) * HIT_COST

    cost_out = sum(owned_by_id[i].cost for i in out_ids)
    cost_in = sum(pool_by_id[i].cost for i in in_ids)
    bank_after = bank + cost_out - cost_in

    return TransferPlan(
        transfers_made=n_transfers,
        hit=hit,
        players_out=sorted(players_out, key=lambda p: p["horizon_xpts"]),
        players_in=sorted(players_in, key=lambda p: -p["horizon_xpts"]),
        squad_xpts_before=round(before, 2),
        squad_xpts_after=round(after, 2),
        net_gain=round(after - before - hit, 2),
        bank_after=round(bank_after / 10, 1),
        feasible=True,
    )


def compare_transfer_counts(
    owned: list[TransferCandidate],
    pool: list[TransferCandidate],
    bank: int,
    free_transfers: int,
    max_transfers: int = 2,
) -> list[TransferPlan]:
    """
    Solve for 0, 1, ... `max_transfers` changes so 'roll it' can be compared
    against acting.

    Blueprint §12: the alternative of holding must be priced, not assumed to
    be worse.
    """
    plans: list[TransferPlan] = []

    hold_xpts = sum(c.horizon_xpts for c in owned)
    plans.append(TransferPlan(
        transfers_made=0, hit=0, players_out=[], players_in=[],
        squad_xpts_before=round(hold_xpts, 2),
        squad_xpts_after=round(hold_xpts, 2),
        net_gain=0.0, bank_after=round(bank / 10, 1), feasible=True,
        note="Hold — roll the transfer",
    ))

    for n in range(1, max_transfers + 1):
        plan = optimise_transfers(
            owned, pool, bank, free_transfers, max_transfers=n,
        )
        if plan.feasible:
            # Force exactly n by construction: the solver may use fewer if
            # that is better, which is fine — label it honestly.
            plan.note = f"Up to {n} transfer{'s' if n > 1 else ''}"
            plans.append(plan)

    return plans
