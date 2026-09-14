"""add auto applications

- auto_applications: one job's application form and the answers prepared
  for it, per user.
- saved_answers: what a user answered to a form question, reused on the
  next form that asks the same thing.
- candidate_profiles.phone and current_location: contact details forms
  ask for that resumes don't reliably provide.

Row level security is enabled on the new tables, like every other public
table in Supabase. The backend connects as the table owner and isn't
affected.

Revision ID: o6e1l03j9g75
Revises: n5d0k92i8f64
Create Date: 2026-09-14 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "o6e1l03j9g75"
down_revision: Union[str, None] = "n5d0k92i8f64"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "auto_applications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="preparing"),
        sa.Column("ats", sa.String(20), nullable=True),
        sa.Column("form_url", sa.Text(), nullable=True),
        sa.Column("form", postgresql.JSONB(), nullable=True),
        sa.Column("answers", postgresql.JSONB(), nullable=True),
        sa.Column("resume_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("resumes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "job_id", name="uq_auto_applications_user_job"),
    )
    op.create_index("ix_auto_applications_status_updated", "auto_applications", ["status", "updated_at"])

    op.create_table(
        "saved_answers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("question_key", sa.String(64), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("answer", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "question_key", name="uq_saved_answers_user_question"),
    )

    op.execute("ALTER TABLE auto_applications ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE saved_answers ENABLE ROW LEVEL SECURITY")

    op.add_column("candidate_profiles", sa.Column("phone", sa.String(40), nullable=True))
    op.add_column("candidate_profiles", sa.Column("current_location", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("candidate_profiles", "current_location")
    op.drop_column("candidate_profiles", "phone")
    op.drop_table("saved_answers")
    op.drop_index("ix_auto_applications_status_updated", table_name="auto_applications")
    op.drop_table("auto_applications")
