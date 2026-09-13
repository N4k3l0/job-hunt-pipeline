"""Per-user inbox state for a job (shortlisted / dismissed).

`jobs` rows are shared by every user, so this state can't live on
`Job.status` — writing it there made one user's dismiss hide the job
from everyone. `Job.status` keeps only pipeline states (enriched,
scored, duplicate, expired). Applied state lives in
`application_tracking`, which is already per-user.
"""

import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey, Index, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class UserJobState(Base):
    __tablename__ = "user_job_states"
    __table_args__ = (
        UniqueConstraint("user_id", "job_id", name="uq_user_job_states_user_job"),
        Index("ix_user_job_states_user_status", "user_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    # shortlisted | dismissed
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
