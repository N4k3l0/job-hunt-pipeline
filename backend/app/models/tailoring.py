import uuid
from datetime import datetime

from sqlalchemy import String, Text, DateTime, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class TailoredApplication(Base):
    __tablename__ = "tailored_applications"
    __table_args__ = (
        Index("ix_tailored_user_status", "user_id", "approval_status"),
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
    base_resume_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resumes.id")
    )
    tailored_resume_json: Mapped[dict | None] = mapped_column(JSONB)
    tailored_resume_url: Mapped[str | None] = mapped_column(Text)  # PDF URL in storage
    tailored_summary: Mapped[str | None] = mapped_column(Text)
    cover_letter: Mapped[str | None] = mapped_column(Text)
    recruiter_message: Mapped[str | None] = mapped_column(Text)
    short_answers: Mapped[dict | None] = mapped_column(JSONB)
    keyword_matches: Mapped[dict | None] = mapped_column(JSONB)  # matched and unmatched keywords
    validation_notes: Mapped[dict | None] = mapped_column(JSONB)  # strongest/weakest matches
    approval_status: Mapped[str] = mapped_column(
        String(50), default="pending"
    )  # pending, generating, ready, approved, rejected
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    job: Mapped["Job"] = relationship()
    user: Mapped["User"] = relationship(back_populates="tailored_applications")
    base_resume: Mapped["Resume | None"] = relationship()
