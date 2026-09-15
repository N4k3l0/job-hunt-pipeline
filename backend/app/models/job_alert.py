"""Jobs from users' LinkedIn job alert emails.

A script in the user's own Gmail sends new alert emails to
/api/v1/job-alerts/linkedin with the user's alert key; see
services/job_alerts/."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class JobAlertKey(Base):
    """The key a user's Gmail script sends alert emails with. Only its
    SHA-256 is stored; the key itself is shown to the user once."""

    __tablename__ = "job_alert_keys"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LinkedInJob(Base):
    """Which job a LinkedIn job id is, shared by every user whose alerts
    include it."""

    __tablename__ = "linkedin_jobs"

    linkedin_job_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # When the company's own job board was checked for the full posting.
    details_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class JobAlertHit(Base):
    """A job one of the user's LinkedIn alerts sent them."""

    __tablename__ = "job_alert_hits"
    __table_args__ = (UniqueConstraint("user_id", "job_id", name="uq_job_alert_hits_user_job"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The alert's search and location, e.g. "Automation Engineer" in "United States".
    alert_search: Mapped[str | None] = mapped_column(String(255))
    alert_location: Mapped[str | None] = mapped_column(String(255))
    # The email section the job was in ("primary_job_list" for the alert's
    # own matches) and its place there, starting at 0.
    list_name: Mapped[str | None] = mapped_column(String(64))
    position: Mapped[int | None] = mapped_column(Integer)
    times_sent: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    first_sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class JobAlertEmail(Base):
    """An alert email already read for a user, so a resend adds nothing."""

    __tablename__ = "job_alert_emails"
    __table_args__ = (UniqueConstraint("user_id", "message_id", name="uq_job_alert_emails_user_message"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    message_id: Mapped[str] = mapped_column(String(128), nullable=False)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    jobs_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
