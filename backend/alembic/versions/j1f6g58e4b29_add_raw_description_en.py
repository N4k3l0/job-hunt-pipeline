"""add raw_description_en to jobs

English translation of `raw_description` for non-English postings.
NULL on already-English jobs (~70% of inbox), so we avoid doubling
storage on the majority. Frontend renders
`raw_description_en || raw_description` on Job Detail, and the
inbox-row excerpt is derived from this when present.

Revision ID: j1f6g58e4b29
Revises: i9e5f47d3a18
Create Date: 2026-05-27 19:00:00.000000

"""

from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "j1f6g58e4b29"
down_revision: Union[str, None] = "i9e5f47d3a18"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("raw_description_en", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "raw_description_en")
