"""job run history for background-job monitoring

Revision ID: f1b3d5e7a9c0
Revises: e9a1c3d5f7b8
Create Date: 2026-10-09 10:00:00.000000

Additive only: one new table, pruned to 30 days by the app. On Postgres RLS is
enabled on it like every other public table (e9a1c3d5f7b8 already revoked the
Data API roles' default privileges for new tables).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f1b3d5e7a9c0'
down_revision: Union[str, None] = 'e9a1c3d5f7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'job_runs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('job', sa.String(length=40), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('duration_seconds', sa.Float(), nullable=False),
        sa.Column('ok', sa.Boolean(), nullable=False),
        sa.Column('errors', sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_job_runs_job_started', 'job_runs', ['job', 'started_at'], unique=False)
    if op.get_context().dialect.name == "postgresql":
        op.execute(sa.text("ALTER TABLE public.job_runs ENABLE ROW LEVEL SECURITY"))


def downgrade() -> None:
    op.drop_index('ix_job_runs_job_started', table_name='job_runs')
    op.drop_table('job_runs')
