"""Tell users when a job they've worked on may have closed.

Closed jobs normally leave inboxes by themselves (maintenance/job_expiry.py),
but never ones the user has worked on: tailored a resume for, tracked,
started Apply for me on, or saved. Those stay, so instead they carry a
note once no job site has listed them for a while.

`last_seen_at` is when a job board last listed the job; a job the app has
never seen again was last seen listed when it was found. Some sources list
only recent jobs, so a job can drop out of their feed while still open:
three weeks leaves room for that, and the note says "may".
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, union
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auto_apply import AutoApplication
from app.models.job import Job
from app.models.job_state import UserJobState
from app.models.tailoring import TailoredApplication
from app.models.tracking import ApplicationTracking

MAYBE_CLOSED_DAYS = 21


def _day(moment: datetime) -> str:
    return f"{moment.day} {moment:%B}"


def closed_note(job: Job, now: datetime | None = None) -> str | None:
    """The note for a job not listed anywhere for MAYBE_CLOSED_DAYS, or None."""
    now = now or datetime.now(timezone.utc)
    last_listed = job.last_seen_at or job.discovered_at
    if last_listed is None or last_listed >= now - timedelta(days=MAYBE_CLOSED_DAYS):
        return None
    return f"This job may have closed. The app last saw it listed on {_day(last_listed)}."


async def worked_on(db: AsyncSession, user_id: uuid.UUID, job_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    """The jobs among `job_ids` this user has worked on."""
    if not job_ids:
        return set()
    query = union(
        select(TailoredApplication.job_id).where(
            TailoredApplication.user_id == user_id, TailoredApplication.job_id.in_(job_ids)),
        select(ApplicationTracking.job_id).where(
            ApplicationTracking.user_id == user_id, ApplicationTracking.job_id.in_(job_ids)),
        select(AutoApplication.job_id).where(
            AutoApplication.user_id == user_id, AutoApplication.job_id.in_(job_ids)),
        select(UserJobState.job_id).where(
            UserJobState.user_id == user_id, UserJobState.job_id.in_(job_ids),
            UserJobState.status == "shortlisted"),
    )
    return set((await db.execute(query)).scalars().all())


async def closed_notes(db: AsyncSession, user_id: uuid.UUID, jobs: list[Job]) -> dict[uuid.UUID, str]:
    """Notes for the jobs in `jobs` this user has worked on that may have
    closed. Only asks the database about jobs old enough to need one."""
    now = datetime.now(timezone.utc)
    candidates = {job.id: note for job in jobs if (note := closed_note(job, now))}
    if not candidates:
        return {}
    mine = await worked_on(db, user_id, list(candidates))
    return {job_id: note for job_id, note in candidates.items() if job_id in mine}
