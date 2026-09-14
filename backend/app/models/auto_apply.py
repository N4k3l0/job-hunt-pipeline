"""Applications the app fills in for a user.

An AutoApplication holds one job's application form, read from the
company's hiring system (Greenhouse, Lever or Ashby), and the answer
prepared for each field. Answers the user has to give or confirm keep the
application in "needs_you" until they do.

SavedAnswer remembers what a user answered to a question so the same
question on the next form doesn't have to be asked again.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

# preparing  → reading the form and drafting answers
# needs_you  → some answers need the user
# queued     → every answer is ready; waiting to be sent
# submitting → being sent (step 2)
# submitted  → sent
# failed     → couldn't be prepared or sent; `error` says why
# unsupported→ the job's form isn't on a supported hiring system
# cancelled  → the user stopped it
AUTO_APPLY_STATUSES = (
    "preparing", "needs_you", "queued", "submitting", "submitted",
    "failed", "unsupported", "cancelled",
)


class AutoApplication(Base):
    __tablename__ = "auto_applications"
    __table_args__ = (
        UniqueConstraint("user_id", "job_id", name="uq_auto_applications_user_job"),
        Index("ix_auto_applications_status_updated", "status", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="preparing")
    ats: Mapped[str | None] = mapped_column(String(20))
    form_url: Mapped[str | None] = mapped_column(Text)
    # Normalized form fields, in form order (see services/auto_apply/forms.py).
    form: Mapped[list | None] = mapped_column(JSONB)
    # Field key → {"value", "source", "confirmed", "note"}.
    answers: Mapped[dict | None] = mapped_column(JSONB)
    resume_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resumes.id", ondelete="SET NULL")
    )
    error: Mapped[str | None] = mapped_column(Text)
    # What sending produced: confirmation text, screenshot path.
    result: Mapped[dict | None] = mapped_column(JSONB)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Set while a sender is working on this application.
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    job: Mapped["Job"] = relationship()


class SavedAnswer(Base):
    __tablename__ = "saved_answers"
    __table_args__ = (
        UniqueConstraint("user_id", "question_key", name="uq_saved_answers_user_question"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Hash of the normalized question text and field type.
    question_key: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    # Text, a list of chosen option labels, or a boolean.
    answer: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
