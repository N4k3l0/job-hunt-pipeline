"""add progress_step to tailored_applications

Revision ID: b7e2f9c11a04
Revises: a1b2c3d4e5f6
Create Date: 2026-04-25 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7e2f9c11a04'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'tailored_applications',
        sa.Column('progress_step', sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('tailored_applications', 'progress_step')
