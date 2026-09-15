"""add daily email settings to users

- users.email_digest: whether the user gets the daily email (on by default).
- users.last_digest_sent_at: when it was last sent, or last found to have
  nothing new, so it goes out once a day.

Revision ID: r1j5o36m2k08
Revises: q8g3n25l1i97
Create Date: 2026-09-15 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "r1j5o36m2k08"
down_revision: Union[str, None] = "q8g3n25l1i97"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email_digest", sa.Boolean(), nullable=False, server_default=sa.text("true")))
    op.add_column("users", sa.Column("last_digest_sent_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "last_digest_sent_at")
    op.drop_column("users", "email_digest")
