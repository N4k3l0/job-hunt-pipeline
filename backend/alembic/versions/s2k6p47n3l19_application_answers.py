"""The answers every application asks for, kept on the profile

Revision ID: s2k6p47n3l19
Revises: r1j5o36m2k08
Create Date: 2026-09-18
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "s2k6p47n3l19"
down_revision = "r1j5o36m2k08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("candidate_profiles", sa.Column("earliest_start", sa.String(120), nullable=True))
    op.add_column("candidate_profiles", sa.Column("open_to_relocation", sa.Boolean(), nullable=True))
    op.add_column(
        "candidate_profiles",
        sa.Column("languages", postgresql.ARRAY(sa.String()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("candidate_profiles", "languages")
    op.drop_column("candidate_profiles", "open_to_relocation")
    op.drop_column("candidate_profiles", "earliest_start")
