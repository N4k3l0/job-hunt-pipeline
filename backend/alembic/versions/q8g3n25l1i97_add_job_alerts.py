"""add LinkedIn job alert sync

- job_alert_keys: the hashed key each user's Gmail script sends with.
- linkedin_jobs: LinkedIn job id to job, and when the company's own job
  board was checked for the full posting.
- job_alert_hits: jobs a user's LinkedIn alerts sent them.
- job_alert_emails: alert emails already read, per user.

Row level security is enabled on the new tables, like every other public
table in Supabase. The backend connects as the table owner and isn't
affected.

Revision ID: q8g3n25l1i97
Revises: p7f2m14k0h86
Create Date: 2026-09-15 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "q8g3n25l1i97"
down_revision: Union[str, None] = "p7f2m14k0h86"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ("job_alert_keys", "linkedin_jobs", "job_alert_hits", "job_alert_emails")


def upgrade() -> None:
    op.create_table(
        "job_alert_keys",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "linkedin_jobs",
        sa.Column("linkedin_job_id", sa.String(32), primary_key=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("details_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_linkedin_jobs_job_id", "linkedin_jobs", ["job_id"])
    op.create_table(
        "job_alert_hits",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("alert_search", sa.String(255), nullable=True),
        sa.Column("alert_location", sa.String(255), nullable=True),
        sa.Column("list_name", sa.String(64), nullable=True),
        sa.Column("position", sa.Integer(), nullable=True),
        sa.Column("times_sent", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("first_sent_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "job_id", name="uq_job_alert_hits_user_job"),
    )
    op.create_index("ix_job_alert_hits_job_id", "job_alert_hits", ["job_id"])
    op.create_table(
        "job_alert_emails",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("message_id", sa.String(128), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("jobs_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "message_id", name="uq_job_alert_emails_user_message"),
    )
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("job_alert_emails")
    op.drop_index("ix_job_alert_hits_job_id", table_name="job_alert_hits")
    op.drop_table("job_alert_hits")
    op.drop_index("ix_linkedin_jobs_job_id", table_name="linkedin_jobs")
    op.drop_table("linkedin_jobs")
    op.drop_table("job_alert_keys")
