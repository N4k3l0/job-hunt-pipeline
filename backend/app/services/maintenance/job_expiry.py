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
to be meaningful. Rule 1 leaves jobs people have worked on (applied to,
tailored materials for, started Apply for me on) to the link checker,
which asks the hiring system itself (url_verifier.py). Rule 2 closes them
too, saved or not, except ones on Greenhouse, Lever or Ashby: the link
checker asks those for certain, so only it closes them.
Closing a job never removes a user's record of it: sent applications stay
where they are, and unsent ones move to the closed ones
(services/tracking/quiet.py).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auto_apply import AutoApplication
from app.models.job import Job, JobSource
from app.models.tailoring import TailoredApplication
from app.models.tracking import ApplicationTracking
from app.services.job_freshness import anyone_worked_on

# Sources that fetch complete job boards on every run.
FULL_BOARD_SOURCES = ("curated",)
EXPIRABLE_STATUSES = ("raw", "normalized", "deduplicated", "enriched", "scored", "discovered")

# A single company's board fetch can fail for a day or two; this leaves room.
BOARD_UNSEEN_DAYS = 5
MAX_AGE_DAYS = 45
UNSEEN_DAYS = 30
# How long last_seen_at tracking must have run before rule 2 applies.
WARMUP_DAYS = 2
# Job links on hiring systems the link checker asks directly.
HIRING_SYSTEM_URL = r"^https?://((job-boards|boards)(\.eu)?\.greenhouse\.io|jobs(\.eu)?\.lever\.co|jobs\.ashbyhq\.com)/"


def _on_hiring_system():
    return or_(
        func.coalesce(Job.apply_url, "").op("~*")(HIRING_SYSTEM_URL),
        func.coalesce(Job.job_url, "").op("~*")(HIRING_SYSTEM_URL),
    )


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
    # Rule 1 leaves jobs a user is working on to the link checker: tracked
    # applications, tailored packs (even before approval) and Apply for me
    # applications.
    not_in_use = [
        ~exists().where(ApplicationTracking.job_id == Job.id),
        ~exists().where(TailoredApplication.job_id == Job.id),
        ~exists().where(AutoApplication.job_id == Job.id),
    ]
    open_jobs = [Job.status.in_(EXPIRABLE_STATUSES)]
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
        outcome["gone_from_board"] += await _apply(db, open_jobs + not_in_use + [
            Job.source_id.in_(source_ids),
            or_(Job.last_seen_at.is_(None), Job.last_seen_at < now - timedelta(days=BOARD_UNSEEN_DAYS)),
        ], dry_run)

    tracking_started = (await db.execute(select(func.min(Job.last_seen_at)))).scalar()
    outcome["tracking_started"] = tracking_started.isoformat() if tracking_started else None
    if tracking_started is not None and tracking_started <= now - timedelta(days=WARMUP_DAYS):
        outcome["old_and_unseen"] = await _apply(db, open_jobs + [
            or_(~anyone_worked_on(Job.id), ~_on_hiring_system()),
            Job.discovered_at < now - timedelta(days=MAX_AGE_DAYS),
            or_(Job.last_seen_at.is_(None), Job.last_seen_at < now - timedelta(days=UNSEEN_DAYS)),
        ], dry_run)

    if not dry_run:
        await db.commit()
    return outcome
