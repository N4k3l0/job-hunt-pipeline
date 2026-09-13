"""Email addresses submitted through the landing page's "Request invite"
form. Public, unauthenticated input — the admin reviews the list and
sends real invites from the admin panel."""

import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class InviteRequest(Base):
    __tablename__ = "invite_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Stored lowercased; unique so repeat submissions don't pile up.
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    # Which form on the page it came from (hero / invite).
    source: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
