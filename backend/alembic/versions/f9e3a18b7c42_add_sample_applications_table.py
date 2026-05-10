"""add sample_applications table

Revision ID: f9e3a18b7c42
Revises: e4f8c1a2b903
Create Date: 2026-05-10 23:00:00.000000

User-uploaded writing samples (past cover letters, outreach messages,
resume summaries) that the tailor service feeds Claude as style examples
so generated drafts read in the candidate's actual voice instead of a
generic AI tone.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'f9e3a18b7c42'
down_revision: Union[str, None] = 'e4f8c1a2b903'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'sample_applications',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'user_id', postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('kind', sa.String(50), nullable=False),  # cover_letter | outreach | summary
        sa.Column('label', sa.Text(), nullable=True),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        'ix_sample_applications_user_kind',
        'sample_applications',
        ['user_id', 'kind'],
    )


def downgrade() -> None:
    op.drop_index('ix_sample_applications_user_kind', table_name='sample_applications')
    op.drop_table('sample_applications')
