import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthUser, current_user
from app.database import get_db
from app.models.accounts import FplAccount
from app.models.feedback import SquadOverride
from app.models.news import TrackedManager
from app.rate_limit import UPSTREAM, limiter
from app.services.fpl_client import fetch_manager_info
from app.services.jobs import register_manager

router = APIRouter(prefix="/me", tags=["me"])

# One team per account keeps onboarding simple and limits how many team IDs a
# single sign-up can claim.
MAX_FPL_ACCOUNTS = 1


class ConnectFplAccount(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fpl_entry_id: int = Field(ge=1, le=100_000_000)


def _account_dict(a: FplAccount) -> dict:
    return {
        "fpl_entry_id": a.fpl_entry_id,
        "team_name": a.team_name,
        "manager_name": a.manager_name,
        "connected_at": a.created_at,
    }


async def _accounts(db: AsyncSession, user: AuthUser) -> list[FplAccount]:
    return list((await db.execute(
        select(FplAccount).where(FplAccount.user_id == user.id).order_by(FplAccount.id)
    )).scalars())


@router.get("")
async def me(user: AuthUser = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return {
        "id": str(user.id),
        "email": user.email,
        "phone": user.phone,
        "providers": user.providers,
        "fpl_accounts": [_account_dict(a) for a in await _accounts(db, user)],
    }


@router.post("/fpl-accounts", status_code=201)
@limiter.limit(UPSTREAM)
async def connect_fpl_account(
    request: Request,
    response: Response,
    body: ConnectFplAccount,
    user: AuthUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """Connect an FPL team after confirming with FPL that it exists."""
    existing = await db.scalar(
        select(FplAccount).where(FplAccount.fpl_entry_id == body.fpl_entry_id)
    )
    if existing is not None:
        if existing.user_id == user.id:
            response.status_code = 200
            return _account_dict(existing)
        raise HTTPException(409, "This FPL team is already connected to another account")

    count = await db.scalar(
        select(func.count()).select_from(FplAccount).where(FplAccount.user_id == user.id)
    )
    if count >= MAX_FPL_ACCOUNTS:
        raise HTTPException(409, "Disconnect your current FPL team before connecting another")

    try:
        info = await fetch_manager_info(body.fpl_entry_id)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise HTTPException(404, f"No FPL team found with ID {body.fpl_entry_id}")
        raise HTTPException(502, "FPL returned an error. Please try again shortly.")
    except httpx.HTTPError:
        raise HTTPException(503, "FPL is unreachable right now. Please try again shortly.")

    team_name = str(info.get("name") or "")[:120]
    manager_name = " ".join(
        s for s in (info.get("player_first_name"), info.get("player_last_name")) if s
    )[:120]

    account = FplAccount(
        user_id=user.id,
        fpl_entry_id=body.fpl_entry_id,
        team_name=team_name,
        manager_name=manager_name,
    )
    db.add(account)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "This FPL team is already connected to another account")

    # register_manager commits, which also persists the account row.
    await register_manager(db, body.fpl_entry_id, team_name)
    return _account_dict(account)


@router.delete("/fpl-accounts/{fpl_entry_id}", status_code=204)
async def disconnect_fpl_account(
    fpl_entry_id: int,
    user: AuthUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Disconnect a team and drop the private state attached to it, so whoever
    connects it next does not inherit pending transfers or Telegram delivery.
    """
    account = await db.scalar(
        select(FplAccount).where(
            FplAccount.user_id == user.id, FplAccount.fpl_entry_id == fpl_entry_id
        )
    )
    if account is None:
        raise HTTPException(404, "That FPL team is not connected to your account")

    await db.delete(account)
    await db.execute(delete(SquadOverride).where(SquadOverride.fpl_entry_id == fpl_entry_id))
    tracked = await db.get(TrackedManager, fpl_entry_id)
    if tracked is not None:
        tracked.alerts_enabled = False
        tracked.telegram_chat_id = None
        tracked.telegram_enabled = False
        tracked.telegram_linked_at = None
    return Response(status_code=204)
