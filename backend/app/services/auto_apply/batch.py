"""Applying to many jobs from one page (the Applications page).

The page lists the user's best matches they haven't started (`picks`): the
ones on a form the app fills in, which the user ticks and prepares in one
go, and the ones on other sites, which they open and mark applied. The
same job posted twice (same company and title) shows once.

Preparing a batch (`queue_jobs`, then `prepare_queued` after the request)
puts each job in "preparing" with QUEUED, then prepares them a few at a
time: form read, answers filled in, resume written, about a minute and
$0.15 of AI each. They land in Needs you on the same page, where the user
checks and approves each one; nothing is sent without them. Any left
behind (the server restarted) are finished by the scheduler
(auto_prepare.run), which waits QUEUED_MINUTES before it steps in, so it
never prepares one a batch is still working on.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import create_worker_session
from app.models.auto_apply import AutoApplication
from app.models.job import Job
from app.services.auto_apply.ats import detect_ats
from app.services.auto_apply.auto_prepare import COST_EACH_USD, best_matches, recent_companies
from app.services.auto_apply.prepare import QUEUED

logger = logging.getLogger(__name__)

MAX_BATCH = 25
CONCURRENCY = 3
# How many of each list the page gets: the user may want 20 to 50 a day.
FILL_LIMIT = 60
ELSEWHERE_LIMIT = 40


def _key(job: Job) -> tuple[str, str]:
    return ((job.company or "").strip().lower(), (job.title_en or job.title or "").strip().lower())


async def picks(
    db: AsyncSession, user_id: uuid.UUID, *, fill_limit: int = FILL_LIMIT, elsewhere_limit: int = ELSEWHERE_LIMIT,
    now: datetime | None = None,
) -> dict:
    """The user's best matches not started yet, split by whether the app
    fills in the form, each list up to its own limit."""
    now = now or datetime.now(timezone.utc)
    rows = await best_matches(db, user_id, limit=(fill_limit + elsewhere_limit) * 4, now=now, fillable_only=False)
    started = await recent_companies(db, user_id, now)
    fill, elsewhere, seen = [], [], set()
    for job, score, url in rows:
        if _key(job) in seen:
            continue
        seen.add(_key(job))
        target = detect_ats(url)
        item = {
            "job_id": str(job.id),
            "title": job.title_en or job.title,
            "company": job.company,
            "location": job.location,
            "score": round(score or 0),
            "url": url,
            # Two applications to one company in a month can look like a spray.
            "applied_recently": (job.company or "").strip().lower() in started,
        }
        if target is not None and target.board:
            if len(fill) < fill_limit:
                fill.append(item)
        elif len(elsewhere) < elsewhere_limit:
            elsewhere.append(item)
        if len(fill) >= fill_limit and len(elsewhere) >= elsewhere_limit:
            break
    return {"fill": fill, "elsewhere": elsewhere, "cost_each_usd": COST_EACH_USD, "max_batch": MAX_BATCH}


async def queue_jobs(db: AsyncSession, user_id: uuid.UUID, job_ids: list[uuid.UUID]) -> list[uuid.UUID]:
    """Put these jobs in line to be prepared. Jobs the user already has an
    application for are left as they are."""
    wanted = list(dict.fromkeys(job_ids))[:MAX_BATCH]
    if not wanted:
        return []
    known = set((await db.execute(select(Job.id).where(Job.id.in_(wanted)))).scalars().all())
    started = set((await db.execute(
        select(AutoApplication.job_id).where(AutoApplication.user_id == user_id, AutoApplication.job_id.in_(wanted))
    )).scalars().all())
    queued = [job_id for job_id in wanted if job_id in known and job_id not in started]
    for job_id in queued:
        db.add(AutoApplication(user_id=user_id, job_id=job_id, status="preparing", answers={}, error=QUEUED))
    await db.commit()
    return queued


async def prepare_queued(
    user_id: uuid.UUID, job_ids: list[uuid.UUID], *, preparer=None, session_factory=None,
) -> dict:
    """Prepare the queued jobs, CONCURRENCY at a time. While the AI is
    paused they wait, and the scheduler finishes them once it's back."""
    from app.llm.client import credits_paused
    from app.services.auto_apply.prepare import prepare_application

    preparer = preparer or prepare_application
    session_factory = session_factory or create_worker_session()
    gate = asyncio.Semaphore(CONCURRENCY)
    outcome = {"prepared": 0, "failed": 0}

    async def one(job_id: uuid.UUID) -> None:
        async with gate:
            if credits_paused():
                return
            try:
                async with session_factory() as db:
                    # Stopped while it waited its turn: leave it stopped.
                    status = (await db.execute(
                        select(AutoApplication.status).where(
                            AutoApplication.user_id == user_id, AutoApplication.job_id == job_id,
                        )
                    )).scalar_one_or_none()
                    if status != "preparing":
                        return
                    application = await preparer(db, user_id, job_id, tailor=True)
                outcome["prepared" if application.status not in ("preparing", "failed") else "failed"] += 1
            except Exception:  # noqa: BLE001 — one job mustn't stop the others
                logger.exception("Preparing job %s for user %s failed", job_id, user_id)
                outcome["failed"] += 1

    await asyncio.gather(*(one(job_id) for job_id in job_ids))
    logger.info("Prepared a batch for user %s: %s", user_id, outcome)
    return outcome
