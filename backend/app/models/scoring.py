import uuid
from datetime import datetime

from sqlalchemy import String, Float, DateTime, ForeignKey, Integer, Index, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class JobScore(Base):
    __tablename__ = "job_scores"
    __table_args__ = (
        Index("ix_job_scores_user_fit", "user_id", "overall_fit"),
        Index("ix_job_scores_user_priority", "user_id", "priority"),
        # A job's best score for any user (enrichment reads those first).
        Index("ix_job_scores_job_fit", "job_id", "overall_fit"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    role_path: Mapped[str] = mapped_column(String(50))  # pm, ai_automation
    title_score: Mapped[float] = mapped_column(Float, default=0.0)
    skill_score: Mapped[float] = mapped_column(Float, default=0.0)
    seniority_score: Mapped[float] = mapped_column(Float, default=0.0)
    industry_score: Mapped[float] = mapped_column(Float, default=0.0)
    geo_score: Mapped[float] = mapped_column(Float, default=0.0)
    remote_score: Mapped[float] = mapped_column(Float, default=0.0)
    salary_score: Mapped[float] = mapped_column(Float, default=0.0)
    visa_score: Mapped[float] = mapped_column(Float, default=0.0)
    # Always 0: it held resume-to-job embedding similarity, which was removed.
    semantic_score: Mapped[float] = mapped_column(Float, default=0.0)
    overall_fit: Mapped[float] = mapped_column(Float, default=0.0)
    priority: Mapped[str] = mapped_column(String(20), default="low")  # high, medium, low, archive
    reasoning: Mapped[dict | None] = mapped_column(JSONB)
    deep_score_json: Mapped[dict | None] = mapped_column(JSONB)
    score_version: Mapped[int] = mapped_column(Integer, default=1)
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    job: Mapped["Job"] = relationship(back_populates="scores")
    user: Mapped["User"] = relationship(back_populates="job_scores")
