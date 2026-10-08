"""Server-side calls to Supabase Auth's admin API."""
import uuid

import httpx

from app.config import settings
from app.services.upstreams import monitored


class AuthAdminUnavailable(Exception):
    """Supabase's admin API is not configured or did not do what was asked."""


async def delete_auth_user(user_id: uuid.UUID) -> None:
    """
    Delete the user from Supabase Auth, which also revokes their refresh
    tokens. Already gone (404) counts as done, so a retry is safe.
    """
    key = settings.supabase_service_key
    if not key or not settings.supabase_url:
        raise AuthAdminUnavailable("SUPABASE_SERVICE_KEY is not set")

    headers = {"apikey": key}
    # Legacy service_role keys are JWTs and also go in Authorization. The newer
    # sb_secret_ keys are not JWTs and belong in apikey alone.
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"

    url = f"{settings.supabase_url.rstrip('/')}/auth/v1/admin/users/{user_id}"
    try:
        async with httpx.AsyncClient(timeout=10.0, transport=monitored("supabase_admin")) as client:
            response = await client.delete(url, headers=headers)
    except httpx.HTTPError as e:
        raise AuthAdminUnavailable(str(e)) from e
    if response.status_code not in (200, 204, 404):
        raise AuthAdminUnavailable(f"Supabase returned {response.status_code}")
