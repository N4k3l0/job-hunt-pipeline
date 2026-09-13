"""Read/write helpers for per-user job state. See app/models/job_state.py."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job_state import UserJobState

USER_JOB_STATUSES = ("shortlisted", "dismissed")

# ApplicationTracking statuses that mean "the user has applied". The inbox
# hides these jobs and the job detail page shows them as applied.
APPLIED_TRACKING_STATUSES = (
    "applied",
    "follow_up_due",
    "interviewing",
    "offered",
    "rejected",
    "ghosted",
)


def effective_status(
    job_status: str | None,
    user_state: str | None,
    tracking_status: str | None = None,
) -> str | None:
    """The status one user sees for a job: their application state first,
    then their shortlist/dismiss state, then the shared pipeline state."""
    if tracking_status in APPLIED_TRACKING_STATUSES:
        return "applied"
    if user_state in USER_JOB_STATUSES:
        return user_state
    return job_status


async def set_user_job_state(
    db: AsyncSession, user_id: UUID, job_id: UUID, status: str | None
) -> None:
    """Upsert the user's state for a job; `None` clears it. Caller commits."""
    if status is None:
        await db.execute(
            delete(UserJobState).where(
                UserJobState.user_id == user_id,
                UserJobState.job_id == job_id,
            )
        )
        return
    if status not in USER_JOB_STATUSES:
        raise ValueError(f"status must be one of {USER_JOB_STATUSES}")
    stmt = pg_insert(UserJobState).values(user_id=user_id, job_id=job_id, status=status)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_user_job_states_user_job",
        set_={"status": status, "updated_at": func.now()},
    )
    await db.execute(stmt)
