"""add job_contacts table

Revision ID: e4f8c1a2b903
Revises: d38c2fb2e615
Create Date: 2026-05-10 22:00:00.000000

Stores hiring-manager / decision-maker lookups per job. One row per job
(job_id is unique) so that two users at the same company+role share the
same cached lookup — web_search calls are paid, no point repeating.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'e4f8c1a2b903'
down_revision: Union[str, None] = 'd38c2fb2e615'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'job_contacts',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'job_id', postgresql.UUID(as_uuid=True),
            sa.ForeignKey('jobs.id', ondelete='CASCADE'),
            unique=True, nullable=False,
        ),
        sa.Column('name', sa.Text(), nullable=True),
        sa.Column('title', sa.Text(), nullable=True),
        sa.Column('linkedin_url', sa.Text(), nullable=True),
        sa.Column('email_guess', sa.Text(), nullable=True),
        sa.Column('confidence', sa.String(20), nullable=True),  # low/medium/high
        sa.Column('source_notes', sa.Text(), nullable=True),
        sa.Column('citations', postgresql.JSONB, nullable=True),  # list of {url, title}
        sa.Column(
            'searched_at',
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table('job_contacts')
