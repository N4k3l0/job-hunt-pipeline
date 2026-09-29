"""What the app spends on Claude, and the balance the admin records

Revision ID: u4m8r69p5n31
Revises: t3l7q58o4m20
Create Date: 2026-09-29
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "u4m8r69p5n31"
down_revision = "t3l7q58o4m20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_usage_hours",
        sa.Column("hour", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("task", sa.String(40), primary_key=True),
        sa.Column("model", sa.String(60), primary_key=True),
        sa.Column("calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("input_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("web_searches", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=False, server_default="0"),
    )
    op.create_table(
        "ai_credit_balances",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("balance_usd", sa.Numeric(10, 2), nullable=False),
        sa.Column("recorded_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )
    op.execute("ALTER TABLE ai_usage_hours ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ai_credit_balances ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("ai_credit_balances")
    op.drop_table("ai_usage_hours")
