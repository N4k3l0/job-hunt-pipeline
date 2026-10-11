"""Move applications out of the way once there's nothing left to do.

- Sent and no reply for QUIET_DAYS: marked "no reply" (`ghosted`), so it
  moves to Closed and stops asking to be followed up. If a reply comes
  after all, the user moves it back (ghosted -> applied, interviewing or
  rejected).
- Not sent yet, and the job has closed: the Apply for me application is
  stopped with a note saying so, and moves to the folded list. "Prepare
  again" brings it back if the job turns out to be open.

Before this, an application from May sat in Sent with "This job may have
closed" and a follow-up four months overdue.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auto_apply import AutoApplication
from app.models.job import Job
from app.models.tracking import ApplicationTracking

QUIET_DAYS = 30
JOB_CLOSED = "The job closed before this was sent."


async def close_quiet_applications(db: AsyncSession, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    quiet = await db.execute(
        update(ApplicationTracking)
        .where(
            ApplicationTracking.status.in_(("applied", "follow_up_due")),
            func.coalesce(ApplicationTracking.applied_at, ApplicationTracking.created_at) < now - timedelta(days=QUIET_DAYS),
        )
        .values(status="ghosted", follow_up_date=None)
        .execution_options(synchronize_session=False)
    )
    closed_jobs = select(Job.id).where(Job.status == "expired")
    stopped = await db.execute(
        update(AutoApplication)
        .where(AutoApplication.status.in_(("needs_you", "queued")), AutoApplication.job_id.in_(closed_jobs))
        .values(status="cancelled", error=JOB_CLOSED)
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    return {"no_reply": quiet.rowcount or 0, "job_closed": stopped.rowcount or 0}
