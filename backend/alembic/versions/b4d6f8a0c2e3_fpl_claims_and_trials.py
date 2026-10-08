"""fpl claims and trials

Revision ID: b4d6f8a0c2e3
Revises: a1c3e5f7b9d2
Create Date: 2026-10-08 14:00:00.000000

Additive only. `trials` keeps its rows when a user is deleted (user_id is set
null) so a team can never receive a second trial.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b4d6f8a0c2e3'
down_revision: Union[str, None] = 'a1c3e5f7b9d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'fpl_claims',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('fpl_entry_id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=12), nullable=False),
        sa.Column('team_name', sa.String(length=120), nullable=False),
        sa.Column('manager_name', sa.String(length=120), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'fpl_entry_id'),
    )
    op.create_index(op.f('ix_fpl_claims_fpl_entry_id'), 'fpl_claims', ['fpl_entry_id'], unique=False)
    op.create_index(op.f('ix_fpl_claims_user_id'), 'fpl_claims', ['user_id'], unique=False)
    op.create_table(
        'trials',
        sa.Column('fpl_entry_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ends_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('fpl_entry_id'),
        sa.UniqueConstraint('user_id'),
    )


def downgrade() -> None:
    op.drop_table('trials')
    op.drop_index(op.f('ix_fpl_claims_user_id'), table_name='fpl_claims')
    op.drop_index(op.f('ix_fpl_claims_fpl_entry_id'), table_name='fpl_claims')
    op.drop_table('fpl_claims')
