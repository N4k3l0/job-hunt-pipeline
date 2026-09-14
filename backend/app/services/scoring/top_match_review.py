"""Automatic AI reviews of each user's best new matches.

The deep review (strengths, gaps, a short explanation of why the job fits)
used to run only when a user clicked "Analyze" on a job. This picks each
user's highest-scoring recent jobs that are actually visible in their
inbox and reviews a few of them a day, within a per-user daily cap.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, or_, select

from app.core.database import create_worker_session
from app.models.candidate import CandidateProfile, CandidateSkill
from app.models.job import Job, JobEntity, JobSource
from app.models.job_state import UserJobState
from app.models.scoring import JobScore
from app.models.tracking import ApplicationTracking
from app.services.job_state import APPLIED_TRACKING_STATUSES
from app.services.jobs_filter import apply_user_filters

logger = logging.getLogger(__name__)


async def reviews_done_today(db, user_id) -> int:
    start_of_day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return (await db.execute(
        select(func.count()).select_from(JobScore).where(
            JobScore.user_id == user_id,
            JobScore.deep_score_json.is_not(None),
            JobScore.deep_score_json["scored_at"].astext >= start_of_day.isoformat(),
        )
    )).scalar() or 0


async def pick_jobs_to_review(db, user_id, *, limit: int, min_score: float, max_age_days: int) -> list:
    """Highest-scoring unreviewed jobs discovered recently that pass the
    user's inbox filters and that they haven't dismissed or applied to."""
    if limit <= 0:
        return []
    profile = (await db.execute(
        select(CandidateProfile).where(CandidateProfile.user_id == user_id)
    )).scalar_one_or_none()
    if profile is None:
        return []
    skills = (await db.execute(
        select(CandidateSkill.skill_name).where(
            CandidateSkill.profile_id == profile.id,
            CandidateSkill.category.in_(("technical", "tool")),
        )
    )).scalars().all()

    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    applied = select(ApplicationTracking.job_id).where(
        ApplicationTracking.user_id == user_id,
        ApplicationTracking.status.in_(APPLIED_TRACKING_STATUSES),
    )
    query = (
        select(Job.id)
        .join(JobScore, and_(JobScore.job_id == Job.id, JobScore.user_id == user_id))
        .outerjoin(JobSource, JobSource.id == Job.source_id)
        .outerjoin(JobEntity, JobEntity.job_id == Job.id)
        .outerjoin(UserJobState, and_(UserJobState.job_id == Job.id, UserJobState.user_id == user_id))
        .where(
            Job.status.notin_(["duplicate", "raw", "expired", "dismissed"]),
            Job.discovered_at >= cutoff,
            JobScore.overall_fit >= min_score,
            JobScore.deep_score_json.is_(None),
            or_(UserJobState.status.is_(None), UserJobState.status != "dismissed"),
            Job.id.notin_(applied),
        )
    )
    query = apply_user_filters(
        query,
        target_roles=profile.target_roles,
        skills=[s for s in skills if s],
        blocked_sources=profile.blocked_sources,
        remote_preference=profile.remote_preference,
        preferred_countries=profile.preferred_countries,
        home_country=profile.home_country,
        visa_statuses=profile.visa_statuses,
        salary_min=profile.salary_min,
        salary_currency=profile.salary_currency,
        user_id=user_id,
    )
    query = query.order_by(JobScore.overall_fit.desc()).limit(limit)
    return list((await db.execute(query)).scalars().all())


async def review_top_matches(
    *,
    per_user_daily: int = 3,
    min_score: float = 70.0,
    max_age_days: int = 3,
    time_budget_seconds: float = 40.0,
    concurrency: int = 3,
) -> dict:
    """Review up to `per_user_daily` jobs per user per UTC day. Stops
    starting new reviews once the time budget is spent; the next run picks
    up where this one left off."""
    from app.services.scoring.deep_scorer import run_deep_score

    started = time.monotonic()
    async with create_worker_session()() as db:
        user_ids = (await db.execute(select(CandidateProfile.user_id))).scalars().all()
        queue: list[tuple] = []
        for user_id in user_ids:
            remaining = per_user_daily - await reviews_done_today(db, user_id)
            for job_id in await pick_jobs_to_review(
                db, user_id, limit=remaining, min_score=min_score, max_age_days=max_age_days,
            ):
                queue.append((user_id, job_id))

    semaphore = asyncio.Semaphore(concurrency)
    outcome = {"queued": len(queue), "reviewed": 0, "failed": 0, "skipped_for_time": 0, "errors": []}

    async def review(user_id, job_id):
        async with semaphore:
            if time.monotonic() - started > time_budget_seconds:
                outcome["skipped_for_time"] += 1
                return
            try:
                async with create_worker_session()() as review_db:
                    await run_deep_score(review_db, str(job_id), str(user_id))
                    await review_db.commit()
                outcome["reviewed"] += 1
            except Exception as e:  # noqa: BLE001
                outcome["failed"] += 1
                outcome["errors"].append(f"{job_id}: {type(e).__name__}: {e}"[:300])

    await asyncio.gather(*(review(u, j) for u, j in queue))
    logger.info("Top-match reviews: %s", {k: v for k, v in outcome.items() if k != "errors"})
    return outcome
