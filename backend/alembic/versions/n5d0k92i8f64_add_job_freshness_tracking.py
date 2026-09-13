"""add job freshness tracking

- jobs.last_seen_at: last time a discovery source listed the job. Jobs a
  source keeps listing are still open.
- jobs.last_checked_at: last time the job's link was probed. Lets the
  link checker work through the whole catalog instead of re-probing the
  same oldest jobs every day.

Both start NULL; expiry rules wait until tracking has run for a few days.

Revision ID: n5d0k92i8f64
Revises: m4c9j81h7e53
Create Date: 2026-09-14 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "n5d0k92i8f64"
down_revision: Union[str, None] = "m4c9j81h7e53"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "last_checked_at")
    op.drop_column("jobs", "last_seen_at")
