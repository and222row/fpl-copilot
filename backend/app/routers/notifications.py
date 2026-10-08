"""
Per-manager notification settings, and the Telegram webhook.

Consent lives here. Nothing is sent to anyone who has not completed the link
from the dashboard, and it can be paused or revoked from the same place.
"""
import logging
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.auth import ManagerAccess
from app.database import get_db
from app.rate_limit import limiter, READ, UPSTREAM
from app.services import notifications, telegram

logger = logging.getLogger("fpl_copilot")

router = APIRouter(tags=["notifications"])


# ── Settings, driven from the dashboard ───────────────────────────────────────

@router.get("/notifications/{manager_id}", dependencies=[ManagerAccess])
@limiter.limit(READ)
async def get_status(
    request: Request, manager_id: int, db: AsyncSession = Depends(get_db)
):
    """Whether this manager has Telegram linked, and whether it is active."""
    return await notifications.status(db, manager_id)


@router.post("/notifications/{manager_id}/telegram/link", dependencies=[ManagerAccess])
@limiter.limit(UPSTREAM)
async def create_link(
    request: Request, manager_id: int, db: AsyncSession = Depends(get_db)
):
    """
    Mint a single-use deep link that connects a Telegram chat to this squad.

    The manager opens it, presses Start, and Telegram delivers the code to our
    webhook — which is the only way to learn a chat id without an account
    system to hang it from.
    """
    if not telegram.configured():
        raise HTTPException(
            503, "Telegram is not configured on the server (TELEGRAM_BOT_TOKEN unset)."
        )

    me = await telegram.get_me()
    username = telegram.bot_username_from(me)
    if not username:
        raise HTTPException(502, "Could not reach Telegram to identify the bot.")

    link = await notifications.create_link_code(db, manager_id)
    return {
        "deep_link": f"https://t.me/{username}?start={link.code}",
        "bot_username": username,
        "expires_at": link.expires_at,
        "expires_in_minutes": notifications.LINK_TTL_MINUTES,
    }


@router.post("/notifications/{manager_id}/telegram/enabled", dependencies=[ManagerAccess])
@limiter.limit(UPSTREAM)
async def set_enabled(
    request: Request,
    manager_id: int,
    enabled: bool,
    db: AsyncSession = Depends(get_db),
):
    """Pause or resume delivery without discarding the link."""
    manager = await notifications.set_enabled(db, manager_id, enabled)
    if manager is None:
        raise HTTPException(404, "No such manager. Load your squad first.")
    return await notifications.status(db, manager_id)


@router.delete("/notifications/{manager_id}/telegram", dependencies=[ManagerAccess])
@limiter.limit(UPSTREAM)
async def unlink(
    request: Request, manager_id: int, db: AsyncSession = Depends(get_db)
):
    """Forget the chat entirely. Re-linking requires Telegram again."""
    removed = await notifications.unlink(db, manager_id)
    return {"unlinked": removed, **await notifications.status(db, manager_id)}


@router.post("/notifications/{manager_id}/telegram/test", dependencies=[ManagerAccess])
@limiter.limit(UPSTREAM)
async def send_test(
    request: Request, manager_id: int, db: AsyncSession = Depends(get_db)
):
    """Prove the link works, rather than waiting for a player to get injured."""
    state = await notifications.status(db, manager_id)
    if not state["linked"]:
        raise HTTPException(400, "Telegram is not linked for this manager.")

    from sqlalchemy import select
    from app.models.news import TrackedManager

    manager = (
        await db.execute(
            select(TrackedManager).where(TrackedManager.fpl_entry_id == manager_id)
        )
    ).scalars().first()

    ok = await telegram.send_message(
        manager.telegram_chat_id,
        "✅ <b>FPL Copilot is connected.</b>\n"
        "Injury, availability and price alerts for your squad will arrive here.\n"
        "<i>You can pause or disconnect this from the dashboard at any time.</i>",
    )
    if not ok:
        raise HTTPException(502, "Telegram rejected the message. Try re-linking.")
    return {"sent": True}


# ── Telegram's side ───────────────────────────────────────────────────────────

@router.post("/telegram/webhook", include_in_schema=False)
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """
    Receive updates from Telegram.

    Only `/start <code>` is acted on. The secret token is the whole of the
    authentication: the URL is public, so without checking it anyone could post
    a forged update and bind their own chat to another manager's squad.

    Always answers 200. Telegram retries non-2xx responses, and there is nothing
    to gain from having it retry an update we have deliberately ignored.
    """
    expected = settings.telegram_webhook_secret
    if not expected or not x_telegram_bot_api_secret_token or not secrets.compare_digest(
        x_telegram_bot_api_secret_token, expected
    ):
        logger.warning("rejected telegram webhook with a bad secret token")
        return Response(status_code=200)

    try:
        update = await request.json()
    except Exception:
        return Response(status_code=200)

    message = (update or {}).get("message") or {}
    text = (message.get("text") or "").strip()
    chat_id = ((message.get("chat") or {}).get("id"))

    if not chat_id or not text.startswith("/start"):
        return Response(status_code=200)

    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        await telegram.send_message(
            str(chat_id),
            "Open <b>FPL Copilot</b> in your browser and press "
            "<b>Connect Telegram</b> — that link is what tells me which squad "
            "is yours.",
        )
        return Response(status_code=200)

    manager = await notifications.redeem_link_code(db, parts[1].strip(), str(chat_id))
    if manager is None:
        await telegram.send_message(
            str(chat_id),
            "That link has expired or was already used. Generate a fresh one "
            f"from the dashboard — they last {notifications.LINK_TTL_MINUTES} minutes.",
        )
        return Response(status_code=200)

    await telegram.send_message(
        str(chat_id),
        "✅ <b>Connected.</b>\n"
        f"Alerts for entry <code>{manager.fpl_entry_id}</code> will arrive here — "
        "injuries, availability changes and price moves affecting your squad.\n"
        "<i>Pause or disconnect any time from the dashboard.</i>",
    )
    return Response(status_code=200)
