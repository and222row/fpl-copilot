"""lock the backend's tables away from Supabase's Data API

Revision ID: e9a1c3d5f7b8
Revises: d8f0b2c4e6a7
Create Date: 2026-10-08 22:00:00.000000

Supabase serves every table in the `public` schema through its REST API
(PostgREST) to anyone holding the project's publishable key, which the mobile
app ships. These tables were created by Alembic with row level security off,
so that key alone could read or rewrite users, subscriptions, devices and
squads. The backend connects as the database owner and does not need either
path.

Enables RLS with no policies on every public table (owner access is
unaffected; the API roles get nothing), revokes the API roles' privileges, and
revokes them by default for tables created later. Postgres only: a no-op on
SQLite and on Postgres without Supabase's roles.

Downgrade restores neither the grants nor RLS-off: re-opening the tables is
never what a rollback should do.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e9a1c3d5f7b8'
down_revision: Union[str, None] = 'd8f0b2c4e6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# One server-side block, so it behaves the same online and in `--sql` output,
# and table names are quoted by format('%I') rather than Python.
LOCK_DOWN = """
DO $$
DECLARE
    t record;
    r text;
BEGIN
    FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t.tablename);
    END LOOP;
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA public FROM %I', r);
            EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM %I', r);
            EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM %I', r);
            EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM %I', r);
        END IF;
    END LOOP;
END
$$
"""


def upgrade() -> None:
    if op.get_context().dialect.name != "postgresql":
        return
    op.execute(sa.text(LOCK_DOWN))


def downgrade() -> None:
    pass
