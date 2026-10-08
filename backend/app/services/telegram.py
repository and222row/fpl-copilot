"""
Telegram Bot API client.

The last mile for alerts. Everything upstream of this — change detection,
per-squad filtering, severity — already worked; the results just sat in a table
until someone opened the dashboard.

Chosen over email and push because it costs nothing and needs no infrastructure:
no SMTP credentials, no SendGrid account, no service worker, no VAPID keys. One
authenticated POST per message.

Delivery is best-effort by design. A Telegram outage, a revoked token or a
manager who blocked the bot must never fail the refresh that produced the
alert — the alert is already saved and visible in the UI, and a notification is
an enhancement to that, not the record of it.
"""
import logging
from typing import Any

import httpx

from app.config import settings
from app.services.upstreams import monitored

logger = logging.getLogger("fpl_copilot")

API_BASE = "https://api.telegram.org"

# Telegram rejects messages over 4096 characters outright.
MAX_MESSAGE_CHARS = 4096

_client: httpx.AsyncClient | None = None


def configured() -> bool:
    return bool(settings.telegram_bot_token)


async def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=15.0, transport=monitored("telegram"))
    return _client


async def close_client() -> None:
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()
    _client = None


async def _call(method: str, payload: dict) -> dict | None:
    """
    Invoke a Bot API method. Returns the `result` object, or None on failure.

    Never raises. Callers are refresh steps and request handlers where a
    notification problem is not worth propagating.
    """
    if not configured():
        logger.debug("telegram not configured, skipping %s", method)
        return None

    url = f"{API_BASE}/bot{settings.telegram_bot_token}/{method}"
    try:
        client = await _get_client()
        response = await client.post(url, json=payload)
        body = response.json()
    except Exception as e:
        logger.warning("telegram %s failed", method, extra={"error": str(e)})
        return None

    if not body.get("ok"):
        # 403 here usually means the manager blocked the bot or deleted the
        # chat. Logged rather than raised; the caller decides whether that
        # should unlink them.
        logger.warning(
            "telegram %s rejected",
            method,
            extra={
                "error_code": body.get("error_code"),
                "description": body.get("description"),
            },
        )
        return None

    return body.get("result")


def _truncate(text: str) -> str:
    """Trim to the API limit. The ellipsis is one character, so reserve one."""
    if len(text) <= MAX_MESSAGE_CHARS:
        return text
    return text[: MAX_MESSAGE_CHARS - 1] + "…"


async def send_message(
    chat_id: str,
    text: str,
    *,
    disable_notification: bool = False,
) -> bool:
    """
    Send one message. Returns whether Telegram accepted it.

    HTML rather than Markdown: player names contain underscores and asterisks
    often enough that Markdown parsing fails on real data, and a failed parse
    means the message is dropped entirely rather than rendered plainly.
    """
    result = await _call(
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": _truncate(text),
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
            "disable_notification": disable_notification,
        },
    )
    return result is not None


async def get_me() -> dict | None:
    """The bot's own identity. Used to build deep links and to verify a token."""
    return await _call("getMe", {})


async def set_webhook(url: str, secret_token: str) -> bool:
    """
    Point Telegram at our webhook.

    The secret token is echoed back in the X-Telegram-Bot-Api-Secret-Token
    header on every update, which is what lets the endpoint tell a real update
    from anyone who guessed the URL.
    """
    result = await _call(
        "setWebhook",
        {
            "url": url,
            "secret_token": secret_token,
            # We only care about messages; skip the rest of the firehose.
            "allowed_updates": ["message"],
            "drop_pending_updates": True,
        },
    )
    return result is not None


async def delete_webhook() -> bool:
    return await _call("deleteWebhook", {"drop_pending_updates": True}) is not None


async def webhook_info() -> dict | None:
    return await _call("getWebhookInfo", {})


def bot_username_from(me: dict[str, Any] | None) -> str | None:
    return (me or {}).get("username")
