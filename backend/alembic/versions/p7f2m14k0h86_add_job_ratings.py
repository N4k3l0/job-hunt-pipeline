"""add job ratings and an index on each job's scores

- job_ratings: whether a user says a job fits them ("good") or not
  ("bad"), from the Rate matches page. Used to measure scoring.
- ix_job_scores_job_fit: a job's best score for any user without scanning
  every score (~60k rows took ~3s); enrichment reads the best jobs first.

Row level security is enabled, like every other public table in Supabase.
The backend connects as the table owner and isn't affected.

Revision ID: p7f2m14k0h86
Revises: o6e1l03j9g75
Create Date: 2026-09-15 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "p7f2m14k0h86"
down_revision: Union[str, None] = "o6e1l03j9g75"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "job_ratings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rating", sa.String(10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "job_id", name="uq_job_ratings_user_job"),
    )
    op.execute("ALTER TABLE job_ratings ENABLE ROW LEVEL SECURITY")
    op.create_index("ix_job_scores_job_fit", "job_scores", ["job_id", "overall_fit"])


def downgrade() -> None:
    op.drop_index("ix_job_scores_job_fit", table_name="job_scores")
    op.drop_table("job_ratings")
