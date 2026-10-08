"""subscriptions and billing events

Revision ID: c7e9a1b3d5f6
Revises: b4d6f8a0c2e3
Create Date: 2026-10-08 18:00:00.000000

Additive only: two new tables.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c7e9a1b3d5f6'
down_revision: Union[str, None] = 'b4d6f8a0c2e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'subscriptions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('provider', sa.String(length=20), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('plan', sa.String(length=20), nullable=True),
        sa.Column('product_id', sa.String(length=120), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('grace_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_sandbox', sa.Boolean(), nullable=False),
        sa.Column('management_url', sa.String(length=500), nullable=True),
        sa.Column('synced_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_subscriptions_user_id'), 'subscriptions', ['user_id'], unique=True)
    op.create_table(
        'billing_events',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('event_id', sa.String(length=120), nullable=False),
        sa.Column('event_type', sa.String(length=60), nullable=False),
        sa.Column('app_user_id', sa.String(length=120), nullable=False),
        sa.Column('environment', sa.String(length=20), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_billing_events_event_id'), 'billing_events', ['event_id'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_billing_events_event_id'), table_name='billing_events')
    op.drop_table('billing_events')
    op.drop_index(op.f('ix_subscriptions_user_id'), table_name='subscriptions')
    op.drop_table('subscriptions')
