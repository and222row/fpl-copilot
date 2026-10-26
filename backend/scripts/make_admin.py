"""
Mark a Supabase account as an admin of the dashboard, or remove the mark.

The role lives in the account's app_metadata (auth.users.raw_app_meta_data),
which users cannot write, so no one can grant it to themselves. It is set here
through the database connection the API already uses, so no extra key is
needed. The new role reaches the API in the next access token: sign out and
in again (or wait up to an hour for the token to refresh). The dashboard also
needs a second factor, set up from the dashboard on first visit.

    python scripts/make_admin.py <user-id>            # make admin
    python scripts/make_admin.py <user-id> --revoke   # remove

Prints the account's masked email for confirmation, never the full one.
"""
import argparse
import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.database import AsyncSessionLocal  # noqa: E402
from app.services.admin import mask_email  # noqa: E402


async def main(user_id: uuid.UUID, revoke: bool) -> int:
    async with AsyncSessionLocal() as db:
        email = await db.scalar(text("SELECT email FROM auth.users WHERE id = :id"), {"id": user_id})
        if email is None:
            print("No Supabase account with that id.")
            return 1
        if revoke:
            await db.execute(text("UPDATE auth.users SET raw_app_meta_data = raw_app_meta_data - 'role' WHERE id = :id"), {"id": user_id})
        else:
            await db.execute(text(
                "UPDATE auth.users SET raw_app_meta_data = "
                "coalesce(raw_app_meta_data, '{}'::jsonb) || jsonb_build_object('role', 'admin') WHERE id = :id"
            ), {"id": user_id})
        await db.commit()
    print(f"{mask_email(email)}: {'no longer an admin' if revoke else 'admin'}. Sign out and in again for it to take effect.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("user_id", type=uuid.UUID)
    parser.add_argument("--revoke", action="store_true")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.user_id, args.revoke)))
