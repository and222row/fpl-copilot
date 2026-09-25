"""
Skip the work when nothing has changed.

The refresh rewrites about four thousand rows to a remote Postgres — 612
players, 380 fixtures, 3,060 projections, 20 team strengths — and at ninety-six
runs a day that came to roughly 5 GB of egress in twenty-five days, which is the
entire free allowance. The service was suspended for it.

Almost all of that was waste. FPL prices move once a day and news a handful of
times; in between, every refresh recomputed identical projections and wrote them
over the wire again. The scheduler firing reliably is what exposed it — while
GitHub was dropping ninety-three percent of runs, the bill stayed small by
accident.

So: hash what FPL returned, and if it matches the last run, skip the rebuilds.
The fetch still happens (it is 0.16 MB gzipped, and it is the only way to know
whether anything moved) but nothing is written.

The hash lives in Redis rather than a table, which avoids a migration and suits
a value that is pure optimisation. If Redis is unreachable the lookup fails open
and the full refresh runs — the safe direction, since a missed skip costs
bandwidth while a wrongly-taken skip would mean stale data.
"""
import hashlib
import json
import logging
from typing import Any

from app.redis_client import get_redis

logger = logging.getLogger("fpl_copilot")

KEY = "fplc:v1:sync-hash"

# Kept well beyond any sane refresh interval; expiry here only stops an
# abandoned deployment's hash lingering for ever.
TTL_SECONDS = 7 * 24 * 3600


def content_hash(*parts: Any) -> str:
    """
    A stable digest of whatever actually drives the rebuilds.

    Deliberately narrow: hashing the whole bootstrap would include fields that
    churn every request — `now`-style timestamps and transfer counters — and
    the hash would never match, making the gate useless while looking like it
    worked.
    """
    digest = hashlib.sha256()
    for part in parts:
        digest.update(
            json.dumps(part, sort_keys=True, separators=(",", ":"), default=str).encode()
        )
    return digest.hexdigest()


def player_fingerprint(bootstrap: dict) -> list:
    """
    The fields a projection actually depends on.

    Ignores `transfers_in_event`, `selected_by_percent` and similar, which move
    constantly and change no projection. Including them would defeat the gate.
    """
    return [
        [
            p.get("id"),
            p.get("now_cost"),
            p.get("status"),
            p.get("chance_of_playing_next_round"),
            p.get("news"),
            p.get("minutes"),
            p.get("total_points"),
            p.get("form"),
            p.get("expected_goals_per_90"),
            p.get("expected_assists_per_90"),
            p.get("element_type"),
            p.get("team"),
        ]
        for p in sorted(bootstrap.get("elements", []), key=lambda x: x.get("id", 0))
    ]


async def unchanged_since_last_run(fingerprint: str) -> bool:
    """
    True when this fingerprint matches the previous refresh.

    Fails open: any Redis problem reports "changed", so the refresh does its
    full work. Spending bandwidth we did not need to is recoverable; skipping a
    rebuild that was needed leaves the app quietly wrong.
    """
    try:
        redis = await get_redis()
        previous = await redis.get(KEY)
        return previous == fingerprint
    except Exception:
        logger.debug("sync gate lookup failed, assuming changed", exc_info=True)
        return False


async def remember(fingerprint: str) -> None:
    try:
        redis = await get_redis()
        await redis.set(KEY, fingerprint, ex=TTL_SECONDS)
    except Exception:
        logger.debug("sync gate write failed", exc_info=True)
