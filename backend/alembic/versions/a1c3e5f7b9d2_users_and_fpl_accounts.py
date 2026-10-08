"""users and fpl accounts

Revision ID: a1c3e5f7b9d2
Revises: 4462aaf15fb2
Create Date: 2026-10-08 12:00:00.000000

Additive only: two new tables, nothing existing is altered. `users.id` is the
Supabase Auth user id; there is no database-level foreign key to `auth.users`
because local Postgres and the SQLite test database have no `auth` schema.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1c3e5f7b9d2'
down_revision: Union[str, None] = '4462aaf15fb2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'users',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'fpl_accounts',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('fpl_entry_id', sa.Integer(), nullable=False),
        sa.Column('team_name', sa.String(length=120), nullable=False),
        sa.Column('manager_name', sa.String(length=120), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_fpl_accounts_user_id'), 'fpl_accounts', ['user_id'], unique=False)
    op.create_index(op.f('ix_fpl_accounts_fpl_entry_id'), 'fpl_accounts', ['fpl_entry_id'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_fpl_accounts_fpl_entry_id'), table_name='fpl_accounts')
    op.drop_index(op.f('ix_fpl_accounts_user_id'), table_name='fpl_accounts')
    op.drop_table('fpl_accounts')
    op.drop_table('users')
