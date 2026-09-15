"""Recording that a user sent an application."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tracking import ApplicationTracking


async def record_applied(db: AsyncSession, user_id: UUID, job_id: UUID) -> ApplicationTracking:
    """Track the job as applied to, which hides it from the user's inbox.
    Doesn't downgrade an interview, offer or rejection. The caller commits."""
    tracking = (await db.execute(
        select(ApplicationTracking).where(
            ApplicationTracking.job_id == job_id,
            ApplicationTracking.user_id == user_id,
        ).order_by(ApplicationTracking.updated_at.desc()).limit(1)
    )).scalar_one_or_none()
    if tracking is None:
        tracking = ApplicationTracking(
            job_id=job_id,
            user_id=user_id,
            status="applied",
            applied_at=datetime.now(timezone.utc),
        )
        db.add(tracking)
    elif tracking.status not in ("interviewing", "offered", "rejected"):
        tracking.status = "applied"
        if not tracking.applied_at:
            tracking.applied_at = datetime.now(timezone.utc)
    return tracking
