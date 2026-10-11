"""Empty the stored text of jobs nobody will look at again.

A job's description, its English translation and the page it was read
from are most of the database (140 MB of 270 on 2026-10-11, on a free plan
of 500 MB). The row itself stays, so the app still knows the job and won't
add it again; only the text goes, from:

- jobs that closed more than CLOSED_DAYS ago (expired, or a duplicate of
  another job);
- jobs older than UNMATCHED_DAYS that never scored UNMATCHED_SCORE for
  anyone, so no inbox shows them.

Never a job anyone worked on: applied to, started an application for,
wrote a resume for, saved or dismissed, rated, or looked up a contact for.
Freed space is reused by new rows, so the database stops growing; it only
shrinks on disk after a VACUUM FULL.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auto_apply import AutoApplication
from app.models.job import Job, JobContact
from app.models.job_rating import JobRating
from app.models.job_state import UserJobState
from app.models.scoring import JobScore
from app.models.tailoring import TailoredApplication
from app.models.tracking import ApplicationTracking

CLOSED_DAYS = 30
UNMATCHED_DAYS = 45
UNMATCHED_SCORE = 40
BATCH = 2000


def _worked_on():
    """Every job any user has done something with. Empty job ids are left
    out: one NULL in a NOT IN list makes it match nothing at all."""
    columns = (AutoApplication.job_id, ApplicationTracking.job_id, TailoredApplication.job_id,
               UserJobState.job_id, JobRating.job_id, JobContact.job_id)
    first, *rest = (select(c).where(c.isnot(None)) for c in columns)
    return first.union(*rest)


async def trim_old_jobs(db: AsyncSession, *, limit: int = BATCH, now: datetime | None = None) -> dict:
    """Empty the text of up to `limit` jobs; returns how many."""
    now = now or datetime.now(timezone.utc)
    best = select(JobScore.job_id, func.max(JobScore.overall_fit).label("fit")).group_by(JobScore.job_id).subquery()
    has_text = or_(Job.raw_description.isnot(None), Job.raw_description_en.isnot(None), Job.raw_content.isnot(None))
    closed = (
        Job.status.in_(("expired", "duplicate"))
        & (func.coalesce(Job.last_seen_at, Job.discovered_at) < now - timedelta(days=CLOSED_DAYS))
    )
    unmatched = (
        Job.status.notin_(("expired", "duplicate"))
        & (Job.discovered_at < now - timedelta(days=UNMATCHED_DAYS))
        & (func.coalesce(best.c.fit, 0) < UNMATCHED_SCORE)
    )
    ids = (await db.execute(
        select(Job.id)
        .outerjoin(best, best.c.job_id == Job.id)
        .where(has_text, or_(closed, unmatched), Job.id.notin_(_worked_on()))
        .limit(limit)
    )).scalars().all()
    if ids:
        await db.execute(
            update(Job).where(Job.id.in_(ids))
            .values(raw_description=None, raw_description_en=None, raw_content=None)
            .execution_options(synchronize_session=False)
        )
        await db.commit()
    return {"trimmed": len(ids)}
