"""User-submitted feedback / bug reports / feature requests.

Read by the admin in /dashboard/admin so we can triage complaints
without users having to find an email address. Public can submit; only
admins can list / mark resolved.
"""

import uuid
from datetime import datetime

from sqlalchemy import String, Text, DateTime, ForeignKey, Boolean, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # One of: 'bug', 'feature', 'general'. Stored as plain string so we
    # don't need an Alembic migration to add a new category later.
    category: Mapped[str] = mapped_column(String(20), nullable=False, default="general")
    # The message itself — kept liberally sized; users sometimes paste
    # error messages, console logs, or screenshots' OCR text.
    message: Mapped[str] = mapped_column(Text, nullable=False)
    # Free-form context the client may attach (URL, viewport, browser).
    # Stored as plain text JSON so the admin can read it without parsing.
    context: Mapped[str | None] = mapped_column(Text)
    # Admin marks an item as resolved once handled. Soft delete; row stays.
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped["User"] = relationship()
