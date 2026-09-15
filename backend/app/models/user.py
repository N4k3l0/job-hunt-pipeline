import uuid
from datetime import datetime

from sqlalchemy import Boolean, String, DateTime, func, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), default="user")  # user, admin
    preferences: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    # The daily email (services/notifications/digest.py): whether the user
    # wants it, and when it was last sent or found to have nothing new.
    email_digest: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    last_digest_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    profile: Mapped["CandidateProfile"] = relationship(back_populates="user", uselist=False)
    resumes: Mapped[list["Resume"]] = relationship(back_populates="user")
    job_scores: Mapped[list["JobScore"]] = relationship(back_populates="user")
    tailored_applications: Mapped[list["TailoredApplication"]] = relationship(back_populates="user")
    application_trackings: Mapped[list["ApplicationTracking"]] = relationship(back_populates="user")
