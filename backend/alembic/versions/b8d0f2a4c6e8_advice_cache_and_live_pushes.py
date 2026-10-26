"""advice cache, and a switch for live match pushes

Revision ID: b8d0f2a4c6e8
Revises: f24e73cba43a
Create Date: 2026-10-26 12:00:00.000000

Additive only: one new table, and one new boolean column defaulting to true
(existing preference rows get live pushes on, like every other kind). Safe to
apply before the code that uses them is deployed. On Postgres RLS is enabled
on the new table like every other public table.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b8d0f2a4c6e8'
down_revision: Union[str, None] = 'f24e73cba43a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'advice_cache',
        sa.Column('fpl_entry_id', sa.Integer(), nullable=False),
        sa.Column('gameweek_id', sa.Integer(), nullable=False),
        sa.Column('fingerprint', sa.String(length=64), nullable=False),
        sa.Column('body', sa.JSON(), nullable=False),
        sa.Column('computed_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('fpl_entry_id'),
    )
    if op.get_context().dialect.name == "postgresql":
        op.execute(sa.text("ALTER TABLE public.advice_cache ENABLE ROW LEVEL SECURITY"))
    op.add_column(
        'notification_preferences',
        sa.Column('live', sa.Boolean(), server_default='true', nullable=False),
    )


def downgrade() -> None:
    op.drop_column('notification_preferences', 'live')
    op.drop_table('advice_cache')
