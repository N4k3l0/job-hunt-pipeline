"""add deep_score_json to job_scores

Revision ID: a1b2c3d4e5f6
Revises: d38c2fb2e615
Create Date: 2026-03-20 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'd38c2fb2e615'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('job_scores', sa.Column('deep_score_json', postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column('job_scores', 'deep_score_json')
