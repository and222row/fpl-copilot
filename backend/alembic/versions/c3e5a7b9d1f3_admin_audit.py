"""admin audit log

Revision ID: c3e5a7b9d1f3
Revises: b8d0f2a4c6e8
Create Date: 2026-10-26 15:00:00.000000

Additive only: one new table recording every admin dashboard action. On
Postgres RLS is enabled on it like every other public table.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3e5a7b9d1f3'
down_revision: Union[str, None] = 'b8d0f2a4c6e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'admin_audit',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('admin_user_id', sa.Uuid(), nullable=False),
        sa.Column('action', sa.String(length=40), nullable=False),
        sa.Column('target_user_id', sa.Uuid(), nullable=True),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('detail', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_admin_audit_admin_user_id'), 'admin_audit', ['admin_user_id'], unique=False)
    op.create_index(op.f('ix_admin_audit_target_user_id'), 'admin_audit', ['target_user_id'], unique=False)
    op.create_index(op.f('ix_admin_audit_created_at'), 'admin_audit', ['created_at'], unique=False)
    if op.get_context().dialect.name == "postgresql":
        op.execute(sa.text("ALTER TABLE public.admin_audit ENABLE ROW LEVEL SECURITY"))


def downgrade() -> None:
    op.drop_index(op.f('ix_admin_audit_created_at'), table_name='admin_audit')
    op.drop_index(op.f('ix_admin_audit_target_user_id'), table_name='admin_audit')
    op.drop_index(op.f('ix_admin_audit_admin_user_id'), table_name='admin_audit')
    op.drop_table('admin_audit')
