"""
Manage the QStash schedule that keeps the data fresh.

Why this exists
---------------
GitHub Actions was the original scheduler and it does not keep time. Measured
over four days on this repo: 100 runs a day configured, 7.1 actually delivered,
a median gap of 157 minutes and a worst gap of 9.5 hours. GitHub's scheduler is
explicitly best-effort and it drops missed slots rather than queuing them, so
raising the frequency does not help — it just raises the number of slots that
get dropped.

QStash runs an actual schedule, retries a failed delivery, and is already part
of the Upstash account this project uses for Redis. The GitHub workflow stays in
place as a backup: two unreliable-in-different-ways schedulers hitting an
idempotent endpoint is strictly better than one.

The endpoint is protected by X-Job-Token, which QStash forwards. QStash also
signs its requests, and verifying that signature would be the belt to this
braces — worth adding if the token ever leaks, but the token alone already
means an attacker needs a secret rather than just the URL.

Usage
-----
    python scripts/qstash_schedule.py list
    python scripts/qstash_schedule.py create --cron "*/15 * * * *"
    python scripts/qstash_schedule.py delete scd_xxx
    python scripts/qstash_schedule.py test          # deliver once, now

Reads QSTASH_TOKEN, JOB_TOKEN and API_BASE_URL from backend/.env. Nothing is
printed that could expose a secret.
"""
import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import quote

import httpx
from dotenv import load_dotenv

QSTASH_BASE = "https://qstash.upstash.io/v2"

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(ENV_PATH)

# The refresh takes about a minute on a free instance, and longer from cold.
# QStash's default timeout is far shorter than that, and a timeout is treated
# as a failed delivery — so it would retry, and every run would be a duplicate.
TIMEOUT = "5m"

# QStash retries a failed delivery with backoff. The refresh is idempotent
# (upserts of the same FPL data), so a retry is safe.
RETRIES = 3

DEFAULT_CRON = "*/15 * * * *"
DEFAULT_HORIZON = 5


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        sys.exit(
            f"{name} is not set in {ENV_PATH}.\n"
            f"Add it there rather than passing it on the command line, so it "
            f"does not end up in your shell history."
        )
    return value


def _destination(horizon: int) -> str:
    base = _require("API_BASE_URL").rstrip("/")
    return f"{base}/api/v1/jobs/refresh?horizon={horizon}"


def _auth() -> dict:
    return {"Authorization": f"Bearer {_require('QSTASH_TOKEN')}"}


def _delivery_headers(horizon: int) -> dict:
    """Headers that control the delivery, plus the ones forwarded onward."""
    return {
        **_auth(),
        "Upstash-Method": "POST",
        "Upstash-Retries": str(RETRIES),
        "Upstash-Timeout": TIMEOUT,
        # Upstash-Forward-* is stripped of its prefix and sent to the
        # destination, which is how the job token reaches our endpoint.
        "Upstash-Forward-X-Job-Token": _require("JOB_TOKEN"),
    }


def cmd_list(_args) -> None:
    r = httpx.get(f"{QSTASH_BASE}/schedules", headers=_auth(), timeout=30)
    r.raise_for_status()
    schedules = r.json()
    if not schedules:
        print("No schedules. Create one with:  qstash_schedule.py create")
        return
    for s in schedules:
        print(f"{s.get('scheduleId')}  cron={s.get('cron')!r}")
        print(f"    -> {s.get('destination')}")
        print(f"    retries={s.get('retries')}  created={s.get('createdAt')}")


def cmd_create(args) -> None:
    destination = _destination(args.horizon)

    existing = httpx.get(f"{QSTASH_BASE}/schedules", headers=_auth(), timeout=30)
    existing.raise_for_status()
    clashes = [
        s for s in existing.json()
        if (s.get("destination") or "").split("?")[0] == destination.split("?")[0]
    ]
    if clashes and not args.replace:
        print("A schedule already points at this endpoint:")
        for s in clashes:
            print(f"  {s.get('scheduleId')}  cron={s.get('cron')!r}")
        sys.exit("Re-run with --replace to swap it, or delete it first.")

    for s in clashes:
        httpx.delete(
            f"{QSTASH_BASE}/schedules/{s['scheduleId']}", headers=_auth(), timeout=30
        )
        print(f"removed {s['scheduleId']}")

    r = httpx.post(
        f"{QSTASH_BASE}/schedules/{quote(destination, safe=':/?=&')}",
        headers={**_delivery_headers(args.horizon), "Upstash-Cron": args.cron},
        timeout=30,
    )
    if r.status_code >= 400:
        sys.exit(f"QStash refused the schedule: HTTP {r.status_code}\n{r.text}")

    print(json.dumps(r.json(), indent=2))
    print(f"\nScheduled {args.cron} -> {destination}")


def cmd_delete(args) -> None:
    r = httpx.delete(
        f"{QSTASH_BASE}/schedules/{args.schedule_id}", headers=_auth(), timeout=30
    )
    if r.status_code >= 400:
        sys.exit(f"HTTP {r.status_code}: {r.text}")
    print(f"deleted {args.schedule_id}")


def cmd_test(args) -> None:
    """Publish one message immediately — proves the whole path before waiting."""
    destination = _destination(args.horizon)
    r = httpx.post(
        f"{QSTASH_BASE}/publish/{quote(destination, safe=':/?=&')}",
        headers=_delivery_headers(args.horizon),
        timeout=30,
    )
    if r.status_code >= 400:
        sys.exit(f"HTTP {r.status_code}: {r.text}")
    print(json.dumps(r.json(), indent=2))
    print("\nQueued. Check delivery in the Upstash console under QStash -> Logs.")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("Usage")[0].strip())
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="show existing schedules").set_defaults(func=cmd_list)

    c = sub.add_parser("create", help="create or replace the refresh schedule")
    c.add_argument("--cron", default=DEFAULT_CRON)
    c.add_argument("--horizon", type=int, default=DEFAULT_HORIZON)
    c.add_argument("--replace", action="store_true",
                   help="delete any existing schedule for this endpoint first")
    c.set_defaults(func=cmd_create)

    d = sub.add_parser("delete", help="delete a schedule by id")
    d.add_argument("schedule_id")
    d.set_defaults(func=cmd_delete)

    t = sub.add_parser("test", help="deliver one refresh immediately")
    t.add_argument("--horizon", type=int, default=DEFAULT_HORIZON)
    t.set_defaults(func=cmd_test)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
