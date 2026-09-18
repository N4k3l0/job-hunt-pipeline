"""The follow-up message drafted for a sent application

Revision ID: t3l7q58o4m20
Revises: s2k6p47n3l19
Create Date: 2026-09-18
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "t3l7q58o4m20"
down_revision = "s2k6p47n3l19"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("auto_applications", sa.Column("follow_up", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("auto_applications", "follow_up")
