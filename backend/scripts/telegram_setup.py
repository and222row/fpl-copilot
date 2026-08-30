"""
One-time Telegram bot wiring.

Telegram has to be told where to deliver updates, and that registration lives on
their side rather than in this repository — so it is easy to forget it was ever
done, or to leave it pointing at a URL that no longer exists. This script makes
it a command rather than a memory.

    python scripts/telegram_setup.py whoami        # verify the token
    python scripts/telegram_setup.py set-webhook   # point Telegram at the API
    python scripts/telegram_setup.py info          # what Telegram thinks
    python scripts/telegram_setup.py delete-webhook

Reads TELEGRAM_BOT_TOKEN, TELEGRAM_WEBHOOK_SECRET and API_BASE_URL from
backend/.env. Generates a webhook secret if one is missing, because an
unauthenticated webhook would let anyone bind their own Telegram chat to
someone else's squad.
"""
import argparse
import asyncio
import json
import re
import secrets
import sys
from pathlib import Path

from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(ENV_PATH)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings          # noqa: E402
from app.services import telegram        # noqa: E402

WEBHOOK_PATH = "/api/v1/telegram/webhook"


def _ensure_secret() -> str:
    """Return the webhook secret, writing a fresh one into .env if unset."""
    if settings.telegram_webhook_secret:
        return settings.telegram_webhook_secret

    generated = secrets.token_urlsafe(32)
    text = ENV_PATH.read_text(encoding="utf-8")
    if re.search(r"^TELEGRAM_WEBHOOK_SECRET=.*$", text, re.M):
        text = re.sub(
            r"^TELEGRAM_WEBHOOK_SECRET=.*$",
            f"TELEGRAM_WEBHOOK_SECRET={generated}",
            text,
            flags=re.M,
        )
    else:
        text = text.rstrip("\n") + f"\nTELEGRAM_WEBHOOK_SECRET={generated}\n"
    ENV_PATH.write_text(text, encoding="utf-8", newline="")

    settings.telegram_webhook_secret = generated
    print(f"generated a webhook secret ({len(generated)} chars) and wrote it to .env")
    print("remember to set the same value in the Render environment")
    return generated


async def _whoami() -> None:
    me = await telegram.get_me()
    if not me:
        sys.exit("Telegram did not accept the token. Check TELEGRAM_BOT_TOKEN.")
    print(json.dumps({k: me.get(k) for k in ("id", "username", "first_name")}, indent=2))
    print(f"\ndeep links will look like: https://t.me/{me.get('username')}?start=<code>")


async def _set_webhook() -> None:
    import os

    base = os.getenv("API_BASE_URL", "").rstrip("/")
    if not base:
        sys.exit("API_BASE_URL is not set in .env")
    if not base.startswith("https://"):
        sys.exit("Telegram only delivers webhooks over HTTPS.")

    secret = _ensure_secret()
    url = f"{base}{WEBHOOK_PATH}"

    if await telegram.set_webhook(url, secret):
        print(f"webhook registered: {url}")
    else:
        sys.exit("Telegram refused the webhook. Run `info` for its reason.")


async def _info() -> None:
    info = await telegram.webhook_info()
    if info is None:
        sys.exit("Could not reach Telegram.")
    print(json.dumps(info, indent=2))
    if info.get("last_error_message"):
        print(f"\nlast delivery error: {info['last_error_message']}")


async def _delete_webhook() -> None:
    print("deleted" if await telegram.delete_webhook() else "failed")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("    python")[0].strip())
    sub = p.add_subparsers(dest="command", required=True)
    for name, fn in (
        ("whoami", _whoami),
        ("set-webhook", _set_webhook),
        ("info", _info),
        ("delete-webhook", _delete_webhook),
    ):
        sub.add_parser(name).set_defaults(func=fn)

    args = p.parse_args()
    if not settings.telegram_bot_token:
        sys.exit(f"TELEGRAM_BOT_TOKEN is not set in {ENV_PATH}")

    # Command and cleanup share one event loop. Closing the httpx client from a
    # second asyncio.run() tears down a transport belonging to a loop that has
    # already closed, which raises "Event loop is closed" after the command has
    # in fact succeeded.
    async def run() -> None:
        try:
            await args.func()
        finally:
            await telegram.close_client()

    asyncio.run(run())


if __name__ == "__main__":
    main()
