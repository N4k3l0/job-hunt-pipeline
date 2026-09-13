"""add job enrichment fields and candidate home country

- job_entities.eligible_countries: ISO-2 codes a job accepts applicants
  from (remote jobs restricted to e.g. US-only). NULL means unrestricted
  or unknown.
- job_entities.enriched_at: when the job was read by the extraction
  model; NULL means not yet enriched.
- candidate_profiles.home_country: where the candidate lives, used to
  hide remote jobs they aren't eligible for.

Revision ID: m4c9j81h7e53
Revises: l3b8i70g6d42
Create Date: 2026-09-14 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "m4c9j81h7e53"
down_revision: Union[str, None] = "l3b8i70g6d42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("job_entities", sa.Column("eligible_countries", postgresql.JSONB(), nullable=True))
    op.add_column("job_entities", sa.Column("enriched_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("candidate_profiles", sa.Column("home_country", sa.String(2), nullable=True))


def downgrade() -> None:
    op.drop_column("candidate_profiles", "home_country")
    op.drop_column("job_entities", "enriched_at")
    op.drop_column("job_entities", "eligible_countries")
