"""Mark closed job postings as expired so they leave every inbox.

Two rules, on top of the link checker in url_verifier.py:

1. Gone from the board: sources that fetch a company's entire job board
   every day ("curated" Greenhouse/Lever/Ashby boards) re-list every
   open job on each run. A job they haven't listed for several days has
   been taken down.
2. Old and no longer listed: any job discovered more than 45 days ago
   that no source has listed for 30 days. Most postings close well before
   that, and a source still listing it would have refreshed last_seen_at.

Both rules wait until last_seen_at tracking has been running long enough
to be meaningful, and never touch a job a user has applied to, tailored
materials for, or started an Apply for me application for. Old jobs a user
has shortlisted are kept too.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auto_apply import AutoApplication
from app.models.job import Job, JobSource
from app.models.job_state import UserJobState
from app.models.tailoring import TailoredApplication
from app.models.tracking import ApplicationTracking

# Sources that fetch complete job boards on every run.
FULL_BOARD_SOURCES = ("curated",)
EXPIRABLE_STATUSES = ("raw", "normalized", "deduplicated", "enriched", "scored", "discovered")

# A single company's board fetch can fail for a day or two; this leaves room.
BOARD_UNSEEN_DAYS = 5
MAX_AGE_DAYS = 45
UNSEEN_DAYS = 30
# How long last_seen_at tracking must have run before rule 2 applies.
WARMUP_DAYS = 2


async def _apply(db: AsyncSession, conditions: list, dry_run: bool) -> int:
    if dry_run:
        return (await db.execute(select(func.count(Job.id)).where(*conditions))).scalar() or 0
    result = await db.execute(
        update(Job).where(*conditions).values(status="expired").execution_options(synchronize_session=False)
    )
    return result.rowcount or 0


async def expire_stale_jobs(
    db: AsyncSession,
    *,
    dry_run: bool = False,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(timezone.utc)
    # Jobs a user is working on stay: tracked applications, tailored packs
    # (even before approval) and Apply for me applications.
    not_in_use = [
        ~exists().where(ApplicationTracking.job_id == Job.id),
        ~exists().where(TailoredApplication.job_id == Job.id),
        ~exists().where(AutoApplication.job_id == Job.id),
    ]
    base = [Job.status.in_(EXPIRABLE_STATUSES), *not_in_use]
    outcome: dict = {"dry_run": dry_run, "gone_from_board": 0, "old_and_unseen": 0}

    for source_name in FULL_BOARD_SOURCES:
        first_seen, last_seen = (await db.execute(
            select(func.min(Job.last_seen_at), func.max(Job.last_seen_at))
            .join(JobSource, JobSource.id == Job.source_id)
            .where(JobSource.name == source_name)
        )).one()
        healthy = (
            first_seen is not None
            and first_seen <= now - timedelta(days=BOARD_UNSEEN_DAYS)
            and last_seen >= now - timedelta(days=1)
        )
        if not healthy:
            continue
        source_ids = select(JobSource.id).where(JobSource.name == source_name)
        outcome["gone_from_board"] += await _apply(db, base + [
            Job.source_id.in_(source_ids),
            or_(Job.last_seen_at.is_(None), Job.last_seen_at < now - timedelta(days=BOARD_UNSEEN_DAYS)),
        ], dry_run)

    tracking_started = (await db.execute(select(func.min(Job.last_seen_at)))).scalar()
    outcome["tracking_started"] = tracking_started.isoformat() if tracking_started else None
    if tracking_started is not None and tracking_started <= now - timedelta(days=WARMUP_DAYS):
        not_shortlisted = ~exists().where(
            and_(UserJobState.job_id == Job.id, UserJobState.status == "shortlisted")
        )
        outcome["old_and_unseen"] = await _apply(db, base + [
            not_shortlisted,
            Job.discovered_at < now - timedelta(days=MAX_AGE_DAYS),
            or_(Job.last_seen_at.is_(None), Job.last_seen_at < now - timedelta(days=UNSEEN_DAYS)),
        ], dry_run)

    if not dry_run:
        await db.commit()
    return outcome
