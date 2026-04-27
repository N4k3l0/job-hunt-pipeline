"""add blocked_sources to candidate_profiles

Revision ID: c8a1b2c3d4e5
Revises: b7e2f9c11a04
Create Date: 2026-04-27 20:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c8a1b2c3d4e5'
down_revision: Union[str, None] = 'b7e2f9c11a04'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'candidate_profiles',
        sa.Column('blocked_sources', sa.ARRAY(sa.String()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('candidate_profiles', 'blocked_sources')
