"""Server-side calls to Supabase Auth's admin API."""
import uuid

import httpx

from app.config import settings
from app.services.upstreams import monitored


class AuthAdminUnavailable(Exception):
    """Supabase's admin API is not configured or did not do what was asked."""


def _headers() -> dict:
    key = settings.supabase_service_key
    if not key or not settings.supabase_url:
        raise AuthAdminUnavailable("SUPABASE_SERVICE_KEY is not set")
    headers = {"apikey": key}
    # Legacy service_role keys are JWTs and also go in Authorization. The newer
    # sb_secret_ keys are not JWTs and belong in apikey alone.
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _url(path: str) -> str:
    return f"{settings.supabase_url.rstrip('/')}/auth/v1/admin/{path}"


async def delete_auth_user(user_id: uuid.UUID) -> None:
    """
    Delete the user from Supabase Auth, which also revokes their refresh
    tokens. Already gone (404) counts as done, so a retry is safe.
    """
    headers = _headers()
    try:
        async with httpx.AsyncClient(timeout=10.0, transport=monitored("supabase_admin")) as client:
            response = await client.delete(_url(f"users/{user_id}"), headers=headers)
    except httpx.HTTPError as e:
        raise AuthAdminUnavailable(str(e)) from e
    if response.status_code not in (200, 204, 404):
        raise AuthAdminUnavailable(f"Supabase returned {response.status_code}")


# Enough pages for 10,000 accounts; the admin dashboard is the only reader.
MAX_PAGES = 10
PER_PAGE = 1000


async def list_auth_users() -> list[dict]:
    """Every sign-in account: id, email, providers, created, last sign-in."""
    headers = _headers()
    users: list[dict] = []
    try:
        async with httpx.AsyncClient(timeout=15.0, transport=monitored("supabase_admin")) as client:
            for page in range(1, MAX_PAGES + 1):
                response = await client.get(_url("users"), params={"page": page, "per_page": PER_PAGE}, headers=headers)
                response.raise_for_status()
                batch = response.json().get("users") or []
                users.extend(batch)
                if len(batch) < PER_PAGE:
                    break
    except (httpx.HTTPError, ValueError) as e:
        raise AuthAdminUnavailable(str(e)) from e
    return users


async def get_auth_user(user_id: uuid.UUID) -> dict | None:
    """One sign-in account, or None if Supabase has no such user."""
    headers = _headers()
    try:
        async with httpx.AsyncClient(timeout=10.0, transport=monitored("supabase_admin")) as client:
            response = await client.get(_url(f"users/{user_id}"), headers=headers)
    except httpx.HTTPError as e:
        raise AuthAdminUnavailable(str(e)) from e
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise AuthAdminUnavailable(f"Supabase returned {response.status_code}")
    return response.json()
