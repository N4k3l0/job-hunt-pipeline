"""add semantic embeddings (pgvector)

Revision ID: g7c9e1d24b81
Revises: f9e3a18b7c42
Create Date: 2026-05-11 21:00:00.000000

Enables pgvector and adds 512-dim embedding columns to candidate_profiles
and job_entities. These power the semantic scorer that replaces the
rule-based title + skill + industry buckets.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g7c9e1d24b81"
down_revision: Union[str, None] = "f9e3a18b7c42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Supabase has pgvector available; this enables it on the database.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # Profile embedding — one per user, refreshed on resume parse +
    # profile update. Nullable so older rows survive until backfill.
    op.execute(
        "ALTER TABLE candidate_profiles ADD COLUMN IF NOT EXISTS embedding vector(512);"
    )

    # Job embedding — one per posting, written at ingest time. Lives on
    # JobEntity (the existing 1-1 sidecar to Job) rather than Job itself
    # to keep the wide-and-rarely-changing fields off the hot Job row.
    op.execute(
        "ALTER TABLE job_entities ADD COLUMN IF NOT EXISTS embedding vector(512);"
    )

    # Cache the semantic component on JobScore so we don't recompute
    # cosine similarity on every inbox query.
    op.execute(
        "ALTER TABLE job_scores ADD COLUMN IF NOT EXISTS semantic_score double precision DEFAULT 0.0;"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE job_scores DROP COLUMN IF EXISTS semantic_score;")
    op.execute("ALTER TABLE job_entities DROP COLUMN IF EXISTS embedding;")
    op.execute("ALTER TABLE candidate_profiles DROP COLUMN IF EXISTS embedding;")
    # Don't drop the extension — other tables may use it later.
