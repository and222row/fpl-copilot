"""
Resolving a manager's *current* squad.

The problem this exists to solve: FPL's public API cannot show transfers made
for a gameweek that has not started yet.

    /entry/{id}/event/{gw}/picks/   404 until the deadline passes
    /entry/{id}/transfers/          omits pending moves
    /my-team/{id}/                  403 without the manager's own login

So the freshest squad available publicly is the one locked at the *last*
deadline. The moment a manager makes a transfer, every recommendation we
produce is about a squad they no longer own — and it will happily re-suggest a
transfer they have already made.

The fix is not technical, because the data simply is not exposed. It is to let
the manager tell us, and to be explicit about which source is in use so a stale
squad is never presented as current.
"""
import logging
from collections import Counter
from dataclasses import dataclass
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from app.models.fpl import Gameweek, Player, Team, utcnow
from app.models.feedback import SquadOverride
from app.services.fpl_client import fetch_manager_picks
from app.services.fpl_sync import deadline_has_passed

logger = logging.getLogger("fpl_copilot")

SOURCE_FPL = "fpl_api"
SOURCE_OVERRIDE = "manager_override"


@dataclass
class ResolvedSquad:
    player_ids: list[int]
    bank: int
    free_transfers: int
    source: str
    picks_gameweek: int
    # Populated only when an override is in effect
    transfers_applied: list | None = None
    stale_warning: str | None = None

    @property
    def is_override(self) -> bool:
        return self.source == SOURCE_OVERRIDE

    def meta(self) -> dict:
        return {
            "squad_source": self.source,
            "picks_gameweek": self.picks_gameweek,
            "transfers_applied": self.transfers_applied,
            "stale_warning": self.stale_warning,
        }


async def prune_stale_overrides(db: AsyncSession) -> int:
    """
    Drop overrides for gameweeks that have started.

    Once a deadline passes FPL reports the real squad, so keeping an override
    would shadow the truth indefinitely — the worst outcome, because it would
    look authoritative.
    """
    gameweeks = (await db.execute(select(Gameweek))).scalars().all()
    started = [g.id for g in gameweeks if deadline_has_passed(g)]
    if not started:
        return 0

    result = await db.execute(
        delete(SquadOverride).where(SquadOverride.gameweek_id.in_(started))
    )
    await db.commit()
    if result.rowcount:
        logger.info("pruned stale squad overrides", extra={"count": result.rowcount})
    return result.rowcount or 0


async def resolve_squad(
    db: AsyncSession,
    manager_id: int,
    target_gw: int,
    picks_gw: int,
) -> ResolvedSquad:
    """
    Best available view of what the manager holds for `target_gw`.

    Prefers a manager-supplied override; otherwise falls back to the last locked
    squad from FPL and attaches a warning saying so.
    """
    await prune_stale_overrides(db)

    override = (await db.execute(
        select(SquadOverride).where(
            SquadOverride.fpl_entry_id == manager_id,
            SquadOverride.gameweek_id == target_gw,
        )
    )).scalars().first()

    if override and override.player_ids:
        return ResolvedSquad(
            player_ids=list(override.player_ids),
            bank=override.bank,
            free_transfers=override.free_transfers,
            source=SOURCE_OVERRIDE,
            picks_gameweek=picks_gw,
            transfers_applied=override.transfers_applied or [],
        )

    picks_data = await fetch_manager_picks(manager_id, picks_gw)
    picks = picks_data.get("picks", [])
    history = picks_data.get("entry_history", {}) or {}
    transfers_block = picks_data.get("transfers", {}) or {}

    free = transfers_block.get("limit")
    free = 1 if free is None else int(free)

    warning = None
    if target_gw != picks_gw:
        warning = (
            f"This is your GW{picks_gw} squad — the newest one FPL exposes "
            f"publicly. If you have already made transfers for GW{target_gw}, "
            f"they are not visible to us until the deadline passes. Record them "
            f"so the advice matches your actual squad."
        )

    return ResolvedSquad(
        player_ids=[p["element"] for p in picks],
        bank=int(history.get("bank") or 0),
        free_transfers=free,
        source=SOURCE_FPL,
        picks_gameweek=picks_gw,
        stale_warning=warning,
    )


async def save_override(
    db: AsyncSession,
    *,
    manager_id: int,
    gameweek_id: int,
    player_ids: list[int],
    bank: int,
    free_transfers: int,
    transfers_applied: list | None = None,
) -> SquadOverride:
    """Record the squad a manager actually holds. Upserts per gameweek."""
    existing = (await db.execute(
        select(SquadOverride).where(
            SquadOverride.fpl_entry_id == manager_id,
            SquadOverride.gameweek_id == gameweek_id,
        )
    )).scalars().first()

    if existing:
        existing.player_ids = player_ids
        existing.bank = bank
        existing.free_transfers = free_transfers
        existing.transfers_applied = transfers_applied
        existing.updated_at = utcnow()
        await db.commit()
        return existing

    row = SquadOverride(
        fpl_entry_id=manager_id,
        gameweek_id=gameweek_id,
        player_ids=player_ids,
        bank=bank,
        free_transfers=free_transfers,
        transfers_applied=transfers_applied,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


# FPL's squad rule; checked again here because recorded transfers are free-form.
MAX_PER_CLUB = 3


async def apply_transfers(
    db: AsyncSession,
    *,
    manager_id: int,
    gameweek_id: int,
    picks_gw: int,
    moves: list[dict],
    player_costs: dict[int, int],
) -> ResolvedSquad:
    """
    Record transfers the manager has already made.

    `moves` is a list of {"out": player_id, "in": player_id}. Bank is adjusted
    by the price difference, and free transfers reduced accordingly — an
    override is only useful if the money and transfer count move with it.
    """
    current = await resolve_squad(db, manager_id, gameweek_id, picks_gw)
    squad = list(current.player_ids)
    bank = current.bank
    free = current.free_transfers

    # Position and club for every player involved. Rows can be missing only
    # for players FPL has removed; those are not checked rather than refused.
    ids = set(squad) | {m.get("out") for m in moves} | {m.get("in") for m in moves}
    meta = {
        pid: (position, team_id, name)
        for pid, position, team_id, name in (await db.execute(
            select(Player.id, Player.position, Player.team_id, Player.web_name).where(Player.id.in_(ids))
        )).all()
    }

    applied = []
    for move in moves:
        out_id, in_id = move.get("out"), move.get("in")
        if out_id not in squad:
            raise ValueError(f"Player {out_id} is not in the squad")
        if in_id in squad:
            raise ValueError(f"Player {in_id} is already in the squad")
        if out_id in meta and in_id in meta and meta[out_id][0] != meta[in_id][0]:
            raise ValueError(
                f"{meta[out_id][2]} and {meta[in_id][2]} play different positions. "
                f"A transfer swaps like for like."
            )

        squad.remove(out_id)
        squad.append(in_id)
        # Selling price is assumed to be current price: FPL's 50% sell-on fee
        # needs the purchase price, which the public API does not expose.
        bank += player_costs.get(out_id, 0) - player_costs.get(in_id, 0)
        free = max(0, free - 1)
        applied.append({"out": out_id, "in": in_id})

    if bank < 0:
        raise ValueError(
            f"Those transfers leave the bank at £{bank / 10:.1f}m. Check the "
            f"players — selling prices may differ from current prices."
        )

    # Only clubs a recorded transfer brought players from: FPL's own squad is
    # legal by definition, and judging it again would only add false alarms.
    clubs = Counter(meta[pid][1] for pid in squad if pid in meta)
    incoming = {meta[m["in"]][1] for m in applied if m["in"] in meta}
    over = [team_id for team_id in incoming if clubs[team_id] > MAX_PER_CLUB]
    if over:
        club = await db.get(Team, over[0])
        raise ValueError(
            f"That gives you {clubs[over[0]]} players from {club.name if club else 'one club'}. "
            f"FPL allows {MAX_PER_CLUB} per club."
        )

    existing = (current.transfers_applied or []) + applied
    await save_override(
        db,
        manager_id=manager_id,
        gameweek_id=gameweek_id,
        player_ids=squad,
        bank=bank,
        free_transfers=free,
        transfers_applied=existing,
    )
    return await resolve_squad(db, manager_id, gameweek_id, picks_gw)


async def clear_override(db: AsyncSession, manager_id: int, gameweek_id: int) -> bool:
    result = await db.execute(
        delete(SquadOverride).where(
            SquadOverride.fpl_entry_id == manager_id,
            SquadOverride.gameweek_id == gameweek_id,
        )
    )
    await db.commit()
    return bool(result.rowcount)
