import secrets
import httpx
from typing import Any

from app.services import cache
from app.services.cache import cached_json

FPL_BASE = "https://fantasy.premierleague.com/api"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; FPLCopilot/1.0)",
}

# Shared async client — reused across requests
_client: httpx.AsyncClient | None = None


async def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            base_url=FPL_BASE,
            headers=HEADERS,
            timeout=30.0,
            follow_redirects=True,
        )
    return _client


async def close_client() -> None:
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()
    _client = None


async def _get(path: str) -> Any:
    client = await get_client()
    response = await client.get(path)
    response.raise_for_status()
    return response.json()


async def fetch_bootstrap() -> dict:
    """
    Returns all players, teams, gameweeks and season metadata.
    This is the main FPL data endpoint — call it on every sync.

    Never cached. It is only read by the sync, and the sync's job is to spot
    what changed since the last one; a cached snapshot would report that
    nothing did. See services/cache.py.
    """
    return await _get("/bootstrap-static/")


async def fetch_fixtures() -> list[dict]:
    """Returns all fixtures for the season. Never cached, as above."""
    return await _get("/fixtures/")


async def fetch_manager_picks(manager_id: int, gameweek: int) -> dict:
    """
    Returns a manager's picks for a given gameweek.

    Cached briefly. One dashboard load resolves the squad four times over
    (squad view, state banner, recommendation, planner), and this collapses
    those into a single upstream request.
    """
    return await cached_json(
        cache.key_picks(manager_id, gameweek),
        lambda: _get(f"/entry/{manager_id}/event/{gameweek}/picks/"),
    )


async def fetch_manager_info(manager_id: int) -> dict:
    """Returns a manager's profile and history. Cached briefly."""
    return await cached_json(
        cache.key_entry(manager_id),
        lambda: _get(f"/entry/{manager_id}/"),
    )


async def fetch_manager_info_fresh(manager_id: int) -> dict:
    """
    A manager's profile straight from FPL, past both our cache and FPL's CDN.

    Only for ownership checks, which must see a team name the user changed
    seconds ago. FPL's varnish layer serves /entry/ responses over a minute old
    despite `no-cache`; a unique query string misses it, and FPL ignores it.
    """
    return await _get(f"/entry/{manager_id}/?_={secrets.token_hex(6)}")


async def fetch_manager_history(manager_id: int) -> dict:
    """
    Season history, including which chips have already been played.

    Cached alongside the other per-manager reads. Chip advice that recommends a
    chip already spent is worse than no advice, so this is a hard dependency of
    the advisor rather than an enrichment.
    """
    return await cached_json(
        cache.key_history(manager_id),
        lambda: _get(f"/entry/{manager_id}/history/"),
    )


async def fetch_live_points(gameweek: int) -> dict:
    """Returns live points for all players in a given gameweek."""
    return await _get(f"/event/{gameweek}/live/")


async def fetch_player_detail(player_id: int) -> dict:
    """Returns detailed history and fixture list for a single player."""
    return await _get(f"/element-summary/{player_id}/")
