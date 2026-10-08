"""
Push notifications through Expo's push service, which relays to APNs and FCM.

Three kinds, each off by user choice: availability alerts and price alerts
(both from the alerts the refresh already raises for a squad) and a deadline
reminder. Every push is recorded before it is sent, unique per user, kind and
subject, so the 30-minute refresh never repeats one.
"""
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.accounts import FplAccount
from app.models.fpl import utcnow
from app.models.news import Alert
from app.models.notifications import Device, NotificationPreference, PushDelivery
from app.services.fpl_sync import get_next_open_gameweek

logger = logging.getLogger("fpl_copilot.push")

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
BATCH_SIZE = 100
TOKEN_PATTERN = re.compile(r"^Expo(nent)?PushToken\[[A-Za-z0-9_-]{10,100}\]$")

KINDS = ("availability", "price", "deadline")
PRICE_EVENTS = {"price_change", "price_imminent"}
PUSHED_SEVERITIES = {"critical", "warning"}
# A device registered today should not receive yesterday's backlog.
ALERT_MAX_AGE = timedelta(hours=3)
DEADLINE_WARNING = timedelta(hours=2)


class PushUnavailable(Exception):
    pass


@dataclass
class Message:
    token: str
    title: str
    body: str
    data: dict = field(default_factory=dict)

    def as_expo(self) -> dict:
        return {
            "to": self.token,
            "title": self.title[:120],
            "body": self.body[:240],
            "data": self.data,
            "sound": "default",
            "channelId": "alerts",
            "priority": "high",
        }


async def send(messages: list[Message]) -> list[dict]:
    """Send in batches; returns one ticket per message, in order."""
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if settings.expo_access_token:
        headers["Authorization"] = f"Bearer {settings.expo_access_token}"
    tickets: list[dict] = []
    async with httpx.AsyncClient(timeout=15.0) as client:
        for i in range(0, len(messages), BATCH_SIZE):
            batch = messages[i:i + BATCH_SIZE]
            try:
                response = await client.post(
                    EXPO_PUSH_URL, json=[m.as_expo() for m in batch], headers=headers
                )
                response.raise_for_status()
                tickets.extend(response.json().get("data") or [])
            except (httpx.HTTPError, ValueError) as e:
                raise PushUnavailable(str(e)) from e
    return tickets


def kind_for(alert: Alert) -> str:
    return "price" if (alert.payload or {}).get("event_type") in PRICE_EVENTS else "availability"


async def _wants(db: AsyncSession, user_id: uuid.UUID, kind: str) -> bool:
    prefs = await db.get(NotificationPreference, user_id)
    return True if prefs is None else bool(getattr(prefs, kind))


async def _claim(db: AsyncSession, user_id: uuid.UUID, kind: str, key: str) -> PushDelivery | None:
    """Record the push before sending it; None if it was already sent."""
    exists = await db.scalar(select(PushDelivery.id).where(
        PushDelivery.user_id == user_id, PushDelivery.kind == kind, PushDelivery.dedupe_key == key
    ))
    if exists is not None:
        return None
    row = PushDelivery(user_id=user_id, kind=kind, dedupe_key=key)
    db.add(row)
    return row


async def _deliver(db: AsyncSession, queued: list[tuple[uuid.UUID, Message]], claims: list[PushDelivery]) -> dict:
    if not queued:
        return {"sent": 0, "pruned": 0}
    try:
        tickets = await send([m for _, m in queued])
    except PushUnavailable:
        # Un-record them so the next refresh tries again, instead of the
        # refresh committing "sent" for pushes that never left.
        for row in claims:
            await db.delete(row)
        await db.flush()
        raise
    pruned = 0
    for (_, message), ticket in zip(queued, tickets):
        if ticket.get("status") == "error" and (ticket.get("details") or {}).get("error") == "DeviceNotRegistered":
            await db.execute(delete(Device).where(Device.token == message.token))
            pruned += 1
    return {"sent": sum(1 for t in tickets if t.get("status") == "ok"), "pruned": pruned}


async def send_due(db: AsyncSession, now: datetime | None = None) -> dict:
    """Queue and send everything due: recent squad alerts and the deadline reminder."""
    now = now or utcnow()
    accounts = (await db.execute(select(FplAccount.user_id, FplAccount.fpl_entry_id))).all()
    devices: dict[uuid.UUID, list[str]] = {}
    for user_id, token in (await db.execute(select(Device.user_id, Device.token))).all():
        devices.setdefault(user_id, []).append(token)

    queued: list[tuple[uuid.UUID, Message]] = []
    claims: list[PushDelivery] = []

    async def queue(user_id, kind, key, title, body, data):
        if not devices.get(user_id) or not await _wants(db, user_id, kind):
            return
        row = await _claim(db, user_id, kind, key)
        if row is None:
            return
        claims.append(row)
        queued.extend((user_id, Message(t, title, body, data)) for t in devices[user_id])

    entry_owner = {entry: user_id for user_id, entry in accounts}
    if entry_owner:
        alerts = (await db.execute(
            select(Alert).where(
                Alert.fpl_entry_id.in_(entry_owner),
                Alert.created_at >= now - ALERT_MAX_AGE,
                Alert.severity.in_(PUSHED_SEVERITIES),
            ).order_by(Alert.created_at)
        )).scalars().all()
        for a in alerts:
            await queue(
                entry_owner[a.fpl_entry_id], kind_for(a), f"alert:{a.id}", a.title, a.body,
                {"type": "alert", "player_id": a.player_id},
            )

    gw = await get_next_open_gameweek(db)
    if gw is not None and gw.deadline_time is not None:
        deadline = gw.deadline_time if gw.deadline_time.tzinfo else gw.deadline_time.replace(tzinfo=now.tzinfo)
        remaining = deadline - now
        if timedelta(0) < remaining <= DEADLINE_WARNING:
            minutes = int(remaining.total_seconds() // 60)
            when = f"{minutes // 60}h {minutes % 60}m" if minutes >= 60 else f"{minutes} min"
            for user_id in {u for u, _ in accounts}:
                await queue(
                    user_id, "deadline", f"gw:{gw.id}", f"{gw.name} deadline in {when}",
                    "Last chance to make transfers and pick your captain.", {"type": "deadline"},
                )

    result = await _deliver(db, queued, claims)
    logger.info("push sent", extra=result)
    return result
