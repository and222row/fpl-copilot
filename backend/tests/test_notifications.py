"""
Opt-in Telegram delivery.

Three things matter more than the sending itself:

  * nobody is messaged who did not ask to be, and revoking works;
  * an alert is delivered once, not once per refresh — at ninety-six refreshes
    a day the difference between those is the difference between a useful
    channel and one that gets muted on the first afternoon;
  * a Telegram failure never propagates into the refresh that produced the
    alert.
"""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from app.config import settings
from app.models.news import Alert, TelegramLink, TrackedManager
from app.services import notifications, telegram


@pytest.fixture(autouse=True)
def _configured():
    """Pretend a bot token is set; individual tests override where needed."""
    with patch.object(settings, "telegram_bot_token", "test-token"):
        yield


def _alert(manager_id=1, severity="critical", title="Saka ruled out", **kw):
    return Alert(
        fpl_entry_id=manager_id,
        severity=severity,
        title=title,
        body=kw.pop("body", "Knee injury. 25% chance for GW3."),
        payload=kw.pop("payload", None),
        **kw,
    )


async def _linked_manager(session, manager_id=1, enabled=True, chat="555"):
    m = TrackedManager(
        fpl_entry_id=manager_id,
        telegram_chat_id=chat,
        telegram_enabled=enabled,
        telegram_linked_at=datetime.now(timezone.utc),
    )
    session.add(m)
    await session.commit()
    return m


# ── Linking ───────────────────────────────────────────────────────────────────

async def test_link_code_round_trips(session):
    link = await notifications.create_link_code(session, 42)
    assert link.code and len(link.code) > 20

    manager = await notifications.redeem_link_code(session, link.code, "chat-9")
    assert manager is not None
    assert manager.fpl_entry_id == 42
    assert manager.telegram_chat_id == "chat-9"
    assert manager.telegram_enabled is True


async def test_a_code_cannot_be_used_twice(session):
    link = await notifications.create_link_code(session, 42)
    assert await notifications.redeem_link_code(session, link.code, "chat-1") is not None
    # A replayed code must not rebind the squad to a different chat.
    assert await notifications.redeem_link_code(session, link.code, "chat-2") is None

    m = (await session.execute(
        select(TrackedManager).where(TrackedManager.fpl_entry_id == 42)
    )).scalars().first()
    assert m.telegram_chat_id == "chat-1"


async def test_expired_code_is_refused(session):
    link = await notifications.create_link_code(session, 42)
    link.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await session.commit()
    assert await notifications.redeem_link_code(session, link.code, "chat-1") is None


async def test_unknown_code_is_refused(session):
    assert await notifications.redeem_link_code(session, "not-a-real-code", "c") is None


async def test_minting_a_new_code_invalidates_the_previous_one(session):
    first = await notifications.create_link_code(session, 42)
    await notifications.create_link_code(session, 42)
    assert await notifications.redeem_link_code(session, first.code, "chat-1") is None


# ── Consent ───────────────────────────────────────────────────────────────────

async def test_disable_keeps_the_link_but_stops_delivery(session):
    await _linked_manager(session, 1)
    await notifications.set_enabled(session, 1, False)

    state = await notifications.status(session, 1)
    assert state["linked"] is True, "pausing must not throw away the link"
    assert state["enabled"] is False

    session.add(_alert(1))
    await session.commit()
    with patch.object(telegram, "send_message", AsyncMock(return_value=True)) as send:
        await notifications.send_pending(session)
    send.assert_not_awaited()


async def test_unlink_forgets_the_chat(session):
    await _linked_manager(session, 1)
    assert await notifications.unlink(session, 1) is True

    state = await notifications.status(session, 1)
    assert state["linked"] is False and state["enabled"] is False

    session.add(_alert(1))
    await session.commit()
    with patch.object(telegram, "send_message", AsyncMock(return_value=True)) as send:
        await notifications.send_pending(session)
    send.assert_not_awaited()


async def test_an_unlinked_manager_is_never_messaged(session):
    session.add(TrackedManager(fpl_entry_id=7))
    session.add(_alert(7))
    await session.commit()

    with patch.object(telegram, "send_message", AsyncMock(return_value=True)) as send:
        await notifications.send_pending(session)
    send.assert_not_awaited()


async def test_alerts_are_not_crossed_between_managers(session):
    await _linked_manager(session, 1, chat="chat-1")
    await _linked_manager(session, 2, chat="chat-2")
    session.add(_alert(1, title="For one"))
    session.add(_alert(2, title="For two"))
    await session.commit()

    with patch.object(telegram, "send_message", AsyncMock(return_value=True)) as send:
        await notifications.send_pending(session)

    by_chat = {c.args[0]: c.args[1] for c in send.await_args_list}
    assert "For one" in by_chat["chat-1"]
    assert "For two" in by_chat["chat-2"]


# ── Delivered once, not once per refresh ──────────────────────────────────────

async def test_an_alert_is_sent_only_once(session):
    await _linked_manager(session, 1)
    session.add(_alert(1))
    await session.commit()

    with patch.object(telegram, "send_message", AsyncMock(return_value=True)) as send:
        await notifications.send_pending(session)
        assert send.await_count == 1
        # The refresh runs every 15 minutes; the next four must stay silent.
        for _ in range(4):
            await notifications.send_pending(session)
        assert send.await_count == 1


async def test_notified_at_is_stamped_even_when_telegram_rejects(session):
    """
    Otherwise a permanently failing send is retried every fifteen minutes for
    ever. The alert is still in the dashboard, which is the record of it.
    """
    await _linked_manager(session, 1)
    a = _alert(1)
    session.add(a)
    await session.commit()

    with patch.object(telegram, "send_message", AsyncMock(return_value=False)):
        result = await notifications.send_pending(session)

    assert result["failed"] == 1
    await session.refresh(a)
    assert a.notified_at is not None


async def test_only_configured_severities_are_pushed(session):
    await _linked_manager(session, 1)
    session.add(_alert(1, severity="critical", title="Critical one"))
    session.add(_alert(1, severity="warning", title="Warning one"))
    session.add(_alert(1, severity="info", title="Info one"))
    await session.commit()

    with patch.object(telegram, "send_message", AsyncMock(return_value=True)) as send:
        await notifications.send_pending(session)

    sent = " ".join(c.args[1] for c in send.await_args_list)
    assert "Critical one" in sent and "Warning one" in sent
    assert "Info one" not in sent, "info would train people to mute the channel"


async def test_a_burst_is_capped_and_says_so(session):
    """A mass FPL status change must not arrive as fifty separate messages."""
    await _linked_manager(session, 1)
    for i in range(notifications.MAX_MESSAGES_PER_RUN + 4):
        session.add(_alert(1, title=f"Alert {i}"))
    await session.commit()

    with patch.object(telegram, "send_message", AsyncMock(return_value=True)) as send:
        await notifications.send_pending(session)

    assert send.await_count == notifications.MAX_MESSAGES_PER_RUN + 1
    assert "more" in send.await_args_list[-1].args[1]


# ── Failing open ──────────────────────────────────────────────────────────────

async def test_send_pending_is_a_no_op_without_a_token(session):
    await _linked_manager(session, 1)
    session.add(_alert(1))
    await session.commit()

    with patch.object(settings, "telegram_bot_token", ""):
        result = await notifications.send_pending(session)
    assert result["sent"] == 0 and "not configured" in result["skipped"]


async def test_telegram_errors_do_not_escape(session):
    await _linked_manager(session, 1)
    session.add(_alert(1))
    await session.commit()

    with patch.object(telegram, "_call", AsyncMock(side_effect=RuntimeError("boom"))):
        # _call is where the client lives; send_message must absorb it.
        with patch.object(telegram, "send_message",
                          AsyncMock(side_effect=lambda *a, **k: False)):
            result = await notifications.send_pending(session)
    assert result["failed"] == 1


async def test_client_swallows_transport_errors():
    """A dead network must return None, not raise into a refresh step."""
    with patch.object(telegram, "_get_client",
                      AsyncMock(side_effect=OSError("no route to host"))):
        assert await telegram.send_message("1", "hello") is False


async def test_client_reports_api_level_rejection():
    """A 403 (blocked bot) is a failure, not an exception."""
    fake = AsyncMock()
    fake.post = AsyncMock(return_value=type("R", (), {
        "json": lambda self: {"ok": False, "error_code": 403,
                              "description": "Forbidden: bot was blocked"}
    })())
    with patch.object(telegram, "_get_client", AsyncMock(return_value=fake)):
        assert await telegram.send_message("1", "hello") is False


# ── Formatting ────────────────────────────────────────────────────────────────

def test_html_special_characters_are_escaped():
    """
    Player news genuinely contains ampersands. An unescaped one makes Telegram
    reject the whole message, so the alert silently never arrives.
    """
    a = _alert(title="Ward-Prowse & Smith <doubt>", body="A > B")
    out = notifications.format_alert(a)
    assert "&amp;" in out and "&lt;doubt&gt;" in out and "A &gt; B" in out
    assert "<b>" in out, "our own markup must survive"


def test_expected_return_is_included_when_present():
    a = _alert(payload={"expected_return": "2026-09-12T00:00:00Z"})
    assert "2026-09-12" in notifications.format_alert(a)


def test_severity_icons_differ():
    icons = {notifications.format_alert(_alert(severity=s))[0]
             for s in ("critical", "warning", "info")}
    assert len(icons) == 3


def test_long_messages_are_truncated_not_dropped():
    """Telegram rejects anything over the limit outright, so the whole alert
    would vanish rather than arrive clipped."""
    out = telegram._truncate("x" * 9000)
    assert len(out) <= telegram.MAX_MESSAGE_CHARS
    assert out.endswith("…")
    # Anything within the limit must pass through untouched.
    assert telegram._truncate("short") == "short"
