import uuid
from datetime import datetime, date

from sqlalchemy import Boolean, String, Text, DateTime, Date, Float, Integer, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class CandidateProfile(Base):
    __tablename__ = "candidate_profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    headline: Mapped[str | None] = mapped_column(String(500))
    master_summary: Mapped[str | None] = mapped_column(Text)
    target_roles: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    preferred_countries: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    # ISO-2 code of where the candidate lives. Remote jobs restricted to
    # other countries are hidden when this is set.
    home_country: Mapped[str | None] = mapped_column(String(2))
    visa_statuses: Mapped[dict | None] = mapped_column(JSONB)
    remote_preference: Mapped[str | None] = mapped_column(String(50))  # full_remote, hybrid, onsite, any
    salary_min: Mapped[int | None] = mapped_column(Integer)
    salary_max: Mapped[int | None] = mapped_column(Integer)
    salary_currency: Mapped[str | None] = mapped_column(String(10), default="USD")
    search_keywords: Mapped[list[str] | None] = mapped_column(ARRAY(String))  # Custom job search queries
    blocked_sources: Mapped[list[str] | None] = mapped_column(ARRAY(String))  # source names to hide from this user's inbox
    links: Mapped[dict | None] = mapped_column(JSONB)  # linkedin, github, portfolio, etc.
    # Contact details application forms ask for.
    phone: Mapped[str | None] = mapped_column(String(40))
    current_location: Mapped[str | None] = mapped_column(String(255))  # e.g. "Lagos, Nigeria"
    # Answers application forms ask for again and again. Filled in once,
    # here or on the first form that asks, then reused everywhere.
    earliest_start: Mapped[str | None] = mapped_column(String(120))  # e.g. "Immediately", "1 month"
    open_to_relocation: Mapped[bool | None] = mapped_column(Boolean)
    languages: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="profile")
    work_history: Mapped[list["CandidateWorkHistory"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    skills: Mapped[list["CandidateSkill"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    education: Mapped[list["CandidateEducation"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    bullets: Mapped[list["CandidateBullet"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )


class CandidateWorkHistory(Base):
    __tablename__ = "candidate_work_history"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("candidate_profiles.id", ondelete="CASCADE")
    )
    company: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(255))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)  # None = current
    description: Mapped[str | None] = mapped_column(Text)
    bullets: Mapped[list[str] | None] = mapped_column(JSONB)
    skills: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    domain_tags: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    profile: Mapped["CandidateProfile"] = relationship(back_populates="work_history")


class CandidateSkill(Base):
    __tablename__ = "candidate_skills"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("candidate_profiles.id", ondelete="CASCADE")
    )
    skill_name: Mapped[str] = mapped_column(String(255))
    category: Mapped[str | None] = mapped_column(String(100))  # technical, soft, tool, domain
    proficiency: Mapped[str | None] = mapped_column(String(50))  # beginner, intermediate, advanced, expert
    years_experience: Mapped[float | None] = mapped_column(Float)

    profile: Mapped["CandidateProfile"] = relationship(back_populates="skills")


class CandidateEducation(Base):
    __tablename__ = "candidate_education"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("candidate_profiles.id", ondelete="CASCADE")
    )
    institution: Mapped[str] = mapped_column(String(255))
    degree: Mapped[str | None] = mapped_column(String(255))
    field: Mapped[str | None] = mapped_column(String(255))
    graduation_date: Mapped[date | None] = mapped_column(Date)

    profile: Mapped["CandidateProfile"] = relationship(back_populates="education")


class CandidateBullet(Base):
    __tablename__ = "candidate_bullet_bank"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("candidate_profiles.id", ondelete="CASCADE")
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    domain_tags: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    role_tags: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    keywords: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    profile: Mapped["CandidateProfile"] = relationship(back_populates="bullets")


class Resume(Base):
    __tablename__ = "resumes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    version_name: Mapped[str] = mapped_column(String(255))
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    source_type: Mapped[str] = mapped_column(String(50))  # pdf, docx
    file_url: Mapped[str] = mapped_column(Text)
    structured_json: Mapped[dict | None] = mapped_column(JSONB)
    parsed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="resumes")


class SampleApplication(Base):
    """User-uploaded writing samples used to teach the tailor service the
    candidate's voice. Three kinds (cover_letter, outreach, summary) so
    samples for one artifact don't bleed into another (a chatty cover
    letter shouldn't make outreach long-winded). Optional — if the user
    hasn't uploaded any of a given kind, generation falls back to the
    default prompt behavior."""
    __tablename__ = "sample_applications"
    __table_args__ = (
        Index("ix_sample_applications_user_kind", "user_id", "kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    # cover_letter | outreach | summary
    kind: Mapped[str] = mapped_column(String(50))
    label: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
