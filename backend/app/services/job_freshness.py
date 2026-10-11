"""Tell users when a job they've worked on may have closed.

Jobs a user has worked on (tailored a resume for, tracked, started Apply
for me on, or saved) carry a note once no job site has listed them for a
while. The link checker (maintenance/url_verifier.py) looks at those first:
Greenhouse, Lever and Ashby say for certain whether a job is open, so it
either closes (and leaves the app, maintenance/job_expiry.py) or counts as
listed again and loses the note. Elsewhere a missing page closes it, and
otherwise it closes once no site has listed it for a month.

`last_seen_at` is when a job board last listed the job; a job the app has
never seen again was last seen listed when it was found. Some sources list
only recent jobs, so a job can drop out of their feed while still open:
three weeks leaves room for that, and the note says "may".
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, exists, or_, select, union
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
    """The note for a closed job, or one not listed anywhere for
    MAYBE_CLOSED_DAYS, or None."""
    if job.status == "expired":
        return "This job has closed."
    now = now or datetime.now(timezone.utc)
    last_listed = job.last_seen_at or job.discovered_at
    if last_listed is None or last_listed >= now - timedelta(days=MAYBE_CLOSED_DAYS):
        return None
    return f"This job may have closed. The app last saw it listed on {_day(last_listed)}."


def anyone_worked_on(job_id):
    """SQL: someone has worked on the job with this id."""
    return or_(
        exists().where(TailoredApplication.job_id == job_id),
        exists().where(ApplicationTracking.job_id == job_id),
        exists().where(AutoApplication.job_id == job_id),
        exists().where(and_(UserJobState.job_id == job_id, UserJobState.status == "shortlisted")),
    )


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
