"""add feedback table

Revision ID: h8d4f25c92a7
Revises: g7c9e1d24b81
Create Date: 2026-05-26 11:00:00.000000

Stores user-submitted feedback / bug reports / feature requests.
Admin reads them in the admin panel; users submit via a sidebar entry.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "h8d4f25c92a7"
down_revision: Union[str, None] = "g7c9e1d24b81"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("category", sa.String(20), nullable=False, server_default="general"),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("context", sa.Text(), nullable=True),
        sa.Column(
            "resolved",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_feedback_user_id_created_at",
        "feedback",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_feedback_resolved_created_at",
        "feedback",
        ["resolved", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_feedback_resolved_created_at", table_name="feedback")
    op.drop_index("ix_feedback_user_id_created_at", table_name="feedback")
    op.drop_table("feedback")
