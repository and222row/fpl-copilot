"""account deletion tombstones and push notifications

Revision ID: d8f0b2c4e6a7
Revises: c7e9a1b3d5f6
Create Date: 2026-10-08 20:00:00.000000

Additive only: four new tables.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd8f0b2c4e6a7'
down_revision: Union[str, None] = 'c7e9a1b3d5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'deleted_users',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'devices',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('token', sa.String(length=200), nullable=False),
        sa.Column('platform', sa.String(length=10), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_devices_token'), 'devices', ['token'], unique=True)
    op.create_index(op.f('ix_devices_user_id'), 'devices', ['user_id'], unique=False)
    op.create_table(
        'notification_preferences',
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('availability', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('price', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('deadline', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id'),
    )
    op.create_table(
        'push_deliveries',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('dedupe_key', sa.String(length=80), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'kind', 'dedupe_key'),
    )
    op.create_index(op.f('ix_push_deliveries_user_id'), 'push_deliveries', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_push_deliveries_user_id'), table_name='push_deliveries')
    op.drop_table('push_deliveries')
    op.drop_table('notification_preferences')
    op.drop_index(op.f('ix_devices_user_id'), table_name='devices')
    op.drop_index(op.f('ix_devices_token'), table_name='devices')
    op.drop_table('devices')
    op.drop_table('deleted_users')
