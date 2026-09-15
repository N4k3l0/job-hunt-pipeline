import uuid
from datetime import datetime

from sqlalchemy import String, Text, Integer, DateTime, ForeignKey, Float, Index, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class JobSource(Base):
    __tablename__ = "job_sources"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), unique=True)
    source_type: Mapped[str] = mapped_column(String(50))  # api, scraper, email, manual
    config: Mapped[dict | None] = mapped_column(JSONB)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    jobs: Mapped[list["Job"]] = relationship(back_populates="source")


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_canonical_hash", "canonical_hash"),
        Index("ix_jobs_source_external", "source_id", "external_id", unique=True),
        Index("ix_jobs_status_discovered", "status", "discovered_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    external_id: Mapped[str | None] = mapped_column(String(500))
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("job_sources.id")
    )
    company: Mapped[str] = mapped_column(String(500))
    title: Mapped[str] = mapped_column(String(500))
    # English translation of `title`, populated at ingest time by the
    # translator helper when the original title isn't already English.
    # Left NULL for English-source jobs so the frontend can `title_en
    # || title` without bloat. Same shape would apply to a future
    # description_en if we ever need translated descriptions in-app.
    title_en: Mapped[str | None] = mapped_column(String(500))
    location: Mapped[str | None] = mapped_column(String(500))
    country: Mapped[str | None] = mapped_column(String(10))  # ISO code
    remote_type: Mapped[str | None] = mapped_column(String(50))  # full_remote, hybrid, onsite
    job_url: Mapped[str | None] = mapped_column(Text)
    apply_url: Mapped[str | None] = mapped_column(Text)
    salary_text: Mapped[str | None] = mapped_column(String(500))
    salary_min: Mapped[int | None] = mapped_column(Integer)
    salary_max: Mapped[int | None] = mapped_column(Integer)
    salary_currency: Mapped[str | None] = mapped_column(String(10))
    raw_description: Mapped[str | None] = mapped_column(Text)
    # English translation of `raw_description`, populated for non-English
    # jobs at ingest by the translator helper. NULL on already-English
    # jobs so the column doesn't double storage for the majority. Job
    # Detail page renders `raw_description_en || raw_description`; the
    # inbox excerpt is also derived from this when present.
    raw_description_en: Mapped[str | None] = mapped_column(Text)
    raw_content: Mapped[str | None] = mapped_column(Text)  # Raw Firecrawl/API output
    employment_type: Mapped[str | None] = mapped_column(String(50))  # full_time, part_time, contract
    seniority: Mapped[str | None] = mapped_column(String(50))  # entry, mid, senior, lead, director, vp
    application_type: Mapped[str | None] = mapped_column(String(50))  # url, email, easy_apply
    language: Mapped[str | None] = mapped_column(String(20))
    canonical_hash: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(50), default="raw")
    # Statuses: raw, normalized, deduplicated, enriched, scored, duplicate, dismissed
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    parsed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Last time a discovery source listed this job (it's still open there).
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Last time the job's link was probed by the URL checker.
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationships
    source: Mapped["JobSource | None"] = relationship(back_populates="jobs")
    entities: Mapped["JobEntity | None"] = relationship(
        back_populates="job", uselist=False, cascade="all, delete-orphan"
    )
    scores: Mapped[list["JobScore"]] = relationship(back_populates="job")
    duplicates: Mapped[list["JobDuplicate"]] = relationship(
        back_populates="job", foreign_keys="JobDuplicate.job_id"
    )


class JobEntity(Base):
    __tablename__ = "job_entities"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), unique=True
    )
    skills: Mapped[list[str] | None] = mapped_column(JSONB)
    requirements: Mapped[list[str] | None] = mapped_column(JSONB)
    keywords: Mapped[list[str] | None] = mapped_column(JSONB)
    nice_to_have: Mapped[list[str] | None] = mapped_column(JSONB)
    visa_notes: Mapped[str | None] = mapped_column(Text)
    sponsorship_available: Mapped[bool | None] = mapped_column(default=None)
    application_questions: Mapped[list[str] | None] = mapped_column(JSONB)
    years_experience_min: Mapped[int | None] = mapped_column(Integer)
    years_experience_max: Mapped[int | None] = mapped_column(Integer)
    # ISO-2 codes the posting accepts applicants from (e.g. ["US"] for a
    # US-only remote role). NULL = unrestricted or unknown.
    eligible_countries: Mapped[list[str] | None] = mapped_column(JSONB)
    # Set when the extraction model has read the posting.
    enriched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    job: Mapped["Job"] = relationship(back_populates="entities")


class JobContact(Base):
    """Decision-maker lookup for a job (hiring manager / dept head / CEO).
    One row per job so two users at the same company+role share the cached
    lookup — web_search calls are paid, no point re-querying."""
    __tablename__ = "job_contacts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), unique=True
    )
    name: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    linkedin_url: Mapped[str | None] = mapped_column(Text)
    email_guess: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[str | None] = mapped_column(String(20))  # low/medium/high
    source_notes: Mapped[str | None] = mapped_column(Text)
    citations: Mapped[list[dict] | None] = mapped_column(JSONB)
    searched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    job: Mapped["Job"] = relationship()


class JobDuplicate(Base):
    __tablename__ = "job_duplicates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE")
    )
    duplicate_of_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE")
    )
    confidence: Mapped[float] = mapped_column(Float)
    method: Mapped[str] = mapped_column(String(50))  # hash, similarity, llm
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    job: Mapped["Job"] = relationship(foreign_keys=[job_id])
    canonical_job: Mapped["Job"] = relationship(foreign_keys=[duplicate_of_job_id])
