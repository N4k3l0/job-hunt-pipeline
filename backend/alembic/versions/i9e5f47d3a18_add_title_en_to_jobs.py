"""add title_en to jobs

Stores the English translation of a job title when the source posting
isn't already English. Populated at ingest by the translator helper.
NULL when the title is already English (saves ~50% storage on the
inbox's all-English majority + makes `title_en IS NOT NULL` a quick
filter for backfill targets).

Revision ID: i9e5f47d3a18
Revises: h8d4f25c92a7
Create Date: 2026-05-27 18:00:00.000000

"""

from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "i9e5f47d3a18"
down_revision: Union[str, None] = "h8d4f25c92a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("title_en", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("jobs", "title_en")
