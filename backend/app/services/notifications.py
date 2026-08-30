"""
Opt-in Telegram delivery for alerts.

Linking without accounts
------------------------
The app has no user accounts — a manager is just an FPL entry id. So a Telegram
chat and a squad have to be introduced. The dashboard mints a single-use code,
hands back a `t.me/<bot>?start=<code>` deep link, and Telegram delivers that
code to our webhook when the manager presses Start. Resolving it tells us which
chat belongs to which squad.

Codes are single use and expire quickly because they travel through a URL. A
leaked live code would let someone point their own Telegram at another
manager's alerts. The blast radius is small — an FPL squad is public data and
the alerts say nothing the FPL website does not — but a code that never expires
is a needless standing invitation.

Consent is explicit and revocable in two degrees, which is the difference
between pausing and leaving:

    disable  -> keep the link, stop sending. Resume from the dashboard alone.
    unlink   -> forget the chat id entirely. Requires Telegram again to return.
"""
import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.news import Alert, TelegramLink, TrackedManager
from app.services import telegram
from app.services.fpl_sync import get_latest_started_gameweek, get_next_open_gameweek
from app.services.squad_state import resolve_squad

logger = logging.getLogger("fpl_copilot")

# Long enough to switch apps and press a button, short enough that a code
# scraped from a screenshot or a shoulder-surfed URL is already dead.
LINK_TTL_MINUTES = 15

# Ceiling on one refresh's worth of notifications per manager. A mass FPL data
# change — a status column shifting for hundreds of players — would otherwise
# arrive as hundreds of separate messages.
MAX_MESSAGES_PER_RUN = 6

SEVERITY_ICON = {"critical": "🔴", "warning": "⚠️", "info": "ℹ️"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Linking ───────────────────────────────────────────────────────────────────

async def create_link_code(db: AsyncSession, manager_id: int) -> TelegramLink:
    """Mint a fresh code, invalidating any earlier unused one for this manager."""
    await db.execute(
        update(TelegramLink)
        .where(
            TelegramLink.fpl_entry_id == manager_id,
            TelegramLink.used_at.is_(None),
        )
        .values(expires_at=_utcnow())
    )

    link = TelegramLink(
        code=secrets.token_urlsafe(24),
        fpl_entry_id=manager_id,
        expires_at=_utcnow() + timedelta(minutes=LINK_TTL_MINUTES),
    )
    db.add(link)
    await db.commit()
    await db.refresh(link)
    return link


async def redeem_link_code(
    db: AsyncSession, code: str, chat_id: str
) -> TrackedManager | None:
    """
    Attach a chat to a squad. Returns the manager, or None if the code is
    unusable — expired, already spent, or simply wrong.
    """
    link = (
        await db.execute(select(TelegramLink).where(TelegramLink.code == code))
    ).scalars().first()

    if link is None or link.used_at is not None:
        return None

    expires = link.expires_at
    if expires.tzinfo is None:            # SQLite hands back naive datetimes
        expires = expires.replace(tzinfo=timezone.utc)
    if expires <= _utcnow():
        return None

    manager = (
        await db.execute(
            select(TrackedManager).where(
                TrackedManager.fpl_entry_id == link.fpl_entry_id
            )
        )
    ).scalars().first()

    if manager is None:
        manager = TrackedManager(fpl_entry_id=link.fpl_entry_id)
        db.add(manager)

    manager.telegram_chat_id = str(chat_id)
    manager.telegram_enabled = True
    manager.telegram_linked_at = _utcnow()
    link.used_at = _utcnow()

    await db.commit()
    await db.refresh(manager)
    return manager


async def set_enabled(
    db: AsyncSession, manager_id: int, enabled: bool
) -> TrackedManager | None:
    """Pause or resume without discarding the link."""
    manager = (
        await db.execute(
            select(TrackedManager).where(TrackedManager.fpl_entry_id == manager_id)
        )
    ).scalars().first()
    if manager is None:
        return None
    manager.telegram_enabled = enabled
    await db.commit()
    await db.refresh(manager)
    return manager


async def unlink(db: AsyncSession, manager_id: int) -> bool:
    """Forget the chat entirely. Returns whether anything was linked."""
    manager = (
        await db.execute(
            select(TrackedManager).where(TrackedManager.fpl_entry_id == manager_id)
        )
    ).scalars().first()
    if manager is None or manager.telegram_chat_id is None:
        return False

    manager.telegram_chat_id = None
    manager.telegram_enabled = False
    manager.telegram_linked_at = None
    await db.commit()
    return True


async def status(db: AsyncSession, manager_id: int) -> dict:
    manager = (
        await db.execute(
            select(TrackedManager).where(TrackedManager.fpl_entry_id == manager_id)
        )
    ).scalars().first()

    return {
        "manager_id": manager_id,
        # False when no bot token is configured on the server, so the UI can
        # say "unavailable" rather than offering a button that cannot work.
        "available": telegram.configured(),
        "linked": bool(manager and manager.telegram_chat_id),
        "enabled": bool(manager and manager.telegram_enabled and manager.telegram_chat_id),
        "linked_at": manager.telegram_linked_at if manager else None,
        "severities": sorted(settings.telegram_severities),
    }


# ── Formatting ────────────────────────────────────────────────────────────────

def _escape(text: str) -> str:
    """Telegram's HTML mode needs these three escaped; nothing else."""
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def format_alert(alert: Alert) -> str:
    icon = SEVERITY_ICON.get(alert.severity, "•")
    lines = [f"{icon} <b>{_escape(alert.title)}</b>"]

    if alert.body:
        lines.append(_escape(alert.body))

    payload = alert.payload or {}
    back = payload.get("expected_return")
    if back:
        lines.append(f"<i>Expected back {_escape(str(back)[:10])}</i>")

    return "\n".join(lines)


# ── Dispatch ──────────────────────────────────────────────────────────────────

async def send_pending(db: AsyncSession, manager_id: int | None = None) -> dict:
    """
    Push alerts that have not been notified yet.

    Called at the end of every refresh. `notified_at` is what stops the same
    injury being re-sent on all ninety-six runs a day, and it is stamped even
    when Telegram rejects the message: retrying a permanently failing send
    every fifteen minutes forever is worse than dropping one notification that
    is still visible in the dashboard.
    """
    if not telegram.configured():
        return {"sent": 0, "skipped": "telegram not configured"}

    q = select(TrackedManager).where(
        TrackedManager.telegram_enabled.is_(True),
        TrackedManager.telegram_chat_id.is_not(None),
    )
    if manager_id is not None:
        q = q.where(TrackedManager.fpl_entry_id == manager_id)

    managers = (await db.execute(q)).scalars().all()

    severities = settings.telegram_severities
    total_sent = 0
    total_failed = 0
    total_skipped_sold = 0

    for manager in managers:
        owned = await _owned_player_ids(db, manager.fpl_entry_id)
        alerts = (
            await db.execute(
                select(Alert)
                .where(
                    Alert.fpl_entry_id == manager.fpl_entry_id,
                    Alert.notified_at.is_(None),
                    Alert.severity.in_(severities),
                )
                .order_by(Alert.created_at.desc())
                .limit(MAX_MESSAGES_PER_RUN)
            )
        ).scalars().all()

        if not alerts:
            continue

        for alert in alerts:
            # A player who has been sold is not news. The dashboard already
            # hides these; pushing them to a phone is worse, because there is
            # no context around the message to make the mistake obvious.
            if owned is not None and alert.player_id is not None \
                    and alert.player_id not in owned:
                alert.notified_at = _utcnow()   # settled, never send it
                total_skipped_sold += 1
                continue

            ok = await telegram.send_message(
                manager.telegram_chat_id, format_alert(alert)
            )
            alert.notified_at = _utcnow()
            if ok:
                total_sent += 1
            else:
                total_failed += 1

        # Say so rather than silently truncating.
        remaining = (
            await db.execute(
                select(Alert).where(
                    Alert.fpl_entry_id == manager.fpl_entry_id,
                    Alert.notified_at.is_(None),
                    Alert.severity.in_(severities),
                )
            )
        ).scalars().all()
        if remaining:
            await telegram.send_message(
                manager.telegram_chat_id,
                f"…and {len(remaining)} more. Open the dashboard for the full list.",
                disable_notification=True,
            )

    await db.commit()
    return {
        "sent": total_sent,
        "failed": total_failed,
        "skipped_sold": total_skipped_sold,
        "managers": len(managers),
    }


async def _owned_player_ids(db: AsyncSession, manager_id: int) -> set[int] | None:
    """
    The squad the manager holds now, or None if it cannot be determined.

    None means "do not filter": suppressing alerts on the strength of a failed
    lookup would be a worse failure than sending one about a sold player.

    Goes through `resolve_squad` rather than reading FPL picks directly. That
    rule exists because reading picks gives the squad locked at the last
    deadline, and this project has shipped that bug three separate times —
    every one of them ending with advice about a player already sold.
    """
    try:
        target = await get_next_open_gameweek(db)
        started = await get_latest_started_gameweek(db)
        if not (target and started):
            return None
        resolved = await resolve_squad(db, manager_id, target.id, started.id)
        return set(resolved.player_ids)
    except Exception:
        logger.debug("could not resolve squad for alert filtering", exc_info=True)
        return None
