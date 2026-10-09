"""team code, for kit images

Revision ID: a7c9e1b3d5f2
Revises: f1b3d5e7a9c0
Create Date: 2026-10-09 17:00:00.000000

Additive only: one column with a default, filled by the next sync. The code
running before this migration does not read it, so applying it ahead of the
deploy is safe.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a7c9e1b3d5f2'
down_revision: Union[str, None] = 'f1b3d5e7a9c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('teams', sa.Column('code', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    op.drop_column('teams', 'code')
