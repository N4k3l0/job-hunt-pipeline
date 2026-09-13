"""add user_job_states and move per-user state off jobs.status

Shortlist / dismiss / applied used to be written to the shared
`jobs.status` column, so one user's action changed every user's inbox.
This moves shortlist/dismiss into a per-user table.

Data: existing shortlisted/dismissed jobs are copied to every user so no
one's inbox changes on deploy; after that each user's actions are their
own. Applied state already lives per-user in application_tracking, so
those jobs just get their shared status reset.

Also merges the two alembic heads (c8a1b2c3d4e5 and j1f6g58e4b29) so
`alembic upgrade head` works again.

Revision ID: k2a7h69f5c31
Revises: c8a1b2c3d4e5, j1f6g58e4b29
Create Date: 2026-09-13 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "k2a7h69f5c31"
down_revision: Union[str, Sequence[str], None] = ("c8a1b2c3d4e5", "j1f6g58e4b29")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_job_states",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "job_id", name="uq_user_job_states_user_job"),
    )
    op.create_index(
        "ix_user_job_states_user_status",
        "user_job_states",
        ["user_id", "status"],
    )

    op.execute(
        """
        INSERT INTO user_job_states (id, user_id, job_id, status)
        SELECT gen_random_uuid(), u.id, j.id, j.status
        FROM jobs j CROSS JOIN users u
        WHERE j.status IN ('shortlisted', 'dismissed')
        """
    )
    op.execute(
        """
        UPDATE jobs SET status = CASE
            WHEN EXISTS (SELECT 1 FROM job_scores s WHERE s.job_id = jobs.id)
            THEN 'scored' ELSE 'enriched' END
        WHERE status IN ('shortlisted', 'dismissed', 'applied', 'discovered')
        """
    )


def downgrade() -> None:
    # Per-user state can't be folded back into one shared column without
    # losing information; the table is dropped and jobs keep their
    # pipeline status.
    op.drop_index("ix_user_job_states_user_status", table_name="user_job_states")
    op.drop_table("user_job_states")
