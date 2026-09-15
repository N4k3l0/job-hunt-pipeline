import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, and_
from sqlalchemy.orm import defer, selectinload

from app.workers.celery_app import celery_app
from app.core.database import create_worker_session
from app.models.job import Job, JobEntity
from app.models.scoring import JobScore
from app.models.candidate import CandidateProfile, CandidateSkill, CandidateWorkHistory
from app.services.scoring.scorer import compute_job_score

logger = logging.getLogger(__name__)


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def job_score_inputs(job: Job) -> tuple[dict, dict]:
    """The (job_data, job_entities) dicts compute_job_score expects.
    `job.entities` must already be loaded."""
    job_data = {
        "title": job.title_en or job.title,
        "company": job.company,
        "location": job.location,
        "country": job.country,
        "remote_type": job.remote_type,
        "salary_min": job.salary_min,
        "salary_max": job.salary_max,
        "seniority": job.seniority,
        # Skill scoring scans the description for user-skill mentions —
        # sources with sparse tag lists don't surface skills any other way.
        "raw_description": job.raw_description_en or job.raw_description or "",
    }
    job_entities: dict = {}
    if job.entities:
        e = job.entities
        job_entities = {
            "skills": e.skills or [],
            "nice_to_have": e.nice_to_have or [],
            "requirements": e.requirements or [],
            "keywords": e.keywords or [],
            "years_experience_min": e.years_experience_min,
            "visa_notes": e.visa_notes,
            "sponsorship_available": e.sponsorship_available,
            # NULL until embedded; the scorer then uses rules only.
            "embedding": getattr(e, "embedding", None),
        }
    return job_data, job_entities


@celery_app.task(name="app.workers.scoring_tasks.score_job_for_user")
def score_job_for_user(job_id: str, user_id: str):
    """Score a single job for a specific user."""
    _run_async(_score_job_async(job_id, user_id))


async def _score_job_async(job_id: str, user_id: str):
    async with create_worker_session()() as db:
        result = await db.execute(
            select(Job)
            .where(Job.id == job_id)
            .options(selectinload(Job.entities))
        )
        job = result.scalar_one_or_none()
        if not job:
            logger.error("Job %s not found for scoring", job_id)
            return

        profile_data = await load_scoring_profile(db, user_id)
        if not profile_data:
            logger.warning("No profile for user %s, skipping scoring", user_id)
            return

        job_data, job_entities = job_score_inputs(job)
        scores = compute_job_score(job_data, job_entities, profile_data)

        existing = await db.execute(
            select(JobScore).where(
                and_(JobScore.job_id == job_id, JobScore.user_id == user_id)
            )
        )
        job_score = existing.scalars().first()

        if job_score:
            for key, value in scores.items():
                setattr(job_score, key, value)
            job_score.calculated_at = datetime.now(timezone.utc)
        else:
            job_score = JobScore(
                job_id=job_id,
                user_id=user_id,
                calculated_at=datetime.now(timezone.utc),
                **scores,
            )
            db.add(job_score)

        if job.status in ("enriched", "normalized"):
            job.status = "scored"

        await db.commit()
        logger.info(
            "Scored job %s for user %s: %.1f (%s)",
            job_id, user_id, scores["overall_fit"], scores["priority"],
        )


@celery_app.task(name="app.workers.scoring_tasks.batch_score_for_user")
def batch_score_for_user(user_id: str, rescore_all: bool = False):
    """Score all unscored jobs for a user. If rescore_all=True, re-score everything."""
    _run_async(_batch_score_async(user_id, rescore_all))


async def _batch_score_async(user_id: str, rescore_all: bool = False):
    async with create_worker_session()() as db:
        profile_data = await load_scoring_profile(db, user_id)
        if not profile_data:
            logger.warning("No profile for user %s, skipping batch scoring", user_id)
            return

        if rescore_all:
            # Delete existing scores for this user and re-score in the same
            # transaction: either everything lands or nothing does and the
            # user keeps their old scores. Deep reviews are carried over.
            from sqlalchemy import delete
            deep_reviews = {
                job_id: deep
                for job_id, deep in (await db.execute(
                    select(JobScore.job_id, JobScore.deep_score_json).where(
                        JobScore.user_id == user_id,
                        JobScore.deep_score_json.is_not(None),
                    )
                )).all()
            }
            await db.execute(delete(JobScore).where(JobScore.user_id == user_id))
            await db.flush()
        else:
            deep_reviews = {}

        # Find unscored jobs. The cron pass caps at 300 to stay inside its
        # budget; a user-triggered rescore_all looks at the whole catalog.
        scored_job_ids = select(JobScore.job_id).where(JobScore.user_id == user_id)
        scan = (
            select(Job)
            .where(
                Job.status.notin_(["duplicate", "raw", "dismissed", "expired"]),
                Job.id.notin_(scored_job_ids),
            )
            .order_by(Job.discovered_at.desc().nulls_last())
            # raw_content duplicates the whole source payload and isn't
            # used for scoring; skipping it roughly halves the data a full
            # rescore pulls from the database.
            .options(defer(Job.raw_content), selectinload(Job.entities))
        )
        if not rescore_all:
            scan = scan.limit(300)
        jobs = (await db.execute(scan)).scalars().all()

        if not jobs:
            logger.info("No unscored jobs for user %s", user_id)
            await db.commit()
            return

        logger.info("Batch scoring %d jobs for user %s", len(jobs), user_id)
        now = datetime.now(timezone.utc)
        for job in jobs:
            job_data, job_entities = job_score_inputs(job)
            scores = compute_job_score(job_data, job_entities, profile_data)
            row = JobScore(job_id=job.id, user_id=user_id, calculated_at=now, **scores)
            # Only set when there is a review: assigning None stores JSON
            # 'null', which isn't SQL NULL and breaks IS NULL checks.
            if job.id in deep_reviews:
                row.deep_score_json = deep_reviews[job.id]
            db.add(row)
            if job.status in ("enriched", "normalized"):
                job.status = "scored"

        await db.commit()
        logger.info("Batch scoring complete: %d jobs scored for user %s", len(jobs), user_id)


async def rescore_jobs_for_all_users(job_ids: list[UUID]) -> int:
    """Recompute scores for specific jobs for every user with a profile,
    e.g. after the jobs were enriched. Updates existing rows in place (deep
    reviews are kept) and inserts missing ones. Returns rows written."""
    if not job_ids:
        return 0
    written = 0
    async with create_worker_session()() as db:
        user_ids = [
            row[0] for row in (await db.execute(select(CandidateProfile.user_id))).all()
        ]
        profiles = {}
        for uid in user_ids:
            profile = await load_scoring_profile(db, str(uid))
            if profile:
                profiles[uid] = profile
        if not profiles:
            return 0

        jobs = (await db.execute(
            select(Job).where(Job.id.in_(job_ids)).options(defer(Job.raw_content), selectinload(Job.entities))
        )).scalars().all()
        existing: dict[tuple, JobScore] = {}
        for row in (await db.execute(
            select(JobScore).where(JobScore.job_id.in_(job_ids))
        )).scalars().all():
            existing.setdefault((row.job_id, row.user_id), row)

        now = datetime.now(timezone.utc)
        for job in jobs:
            job_data, job_entities = job_score_inputs(job)
            for uid, profile in profiles.items():
                scores = compute_job_score(job_data, job_entities, profile)
                row = existing.get((job.id, uid))
                if row is None:
                    db.add(JobScore(job_id=job.id, user_id=uid, calculated_at=now, **scores))
                else:
                    for key, value in scores.items():
                        setattr(row, key, value)
                    row.calculated_at = now
                written += 1
            if job.status in ("enriched", "normalized"):
                job.status = "scored"
        await db.commit()
    return written


async def load_scoring_profile(db, user_id: str) -> dict | None:
    """Load a user's candidate profile as a dict for scoring."""
    result = await db.execute(
        select(CandidateProfile)
        .where(CandidateProfile.user_id == user_id)
        .options(
            selectinload(CandidateProfile.skills),
            selectinload(CandidateProfile.work_history),
        )
    )
    profile = result.scalar_one_or_none()
    if not profile:
        return None

    return {
        "target_roles": profile.target_roles or [],
        "search_keywords": profile.search_keywords or [],
        "preferred_countries": profile.preferred_countries or [],
        "home_country": profile.home_country,
        "visa_statuses": profile.visa_statuses or {},
        "remote_preference": profile.remote_preference or "any",
        "salary_min": profile.salary_min,
        "salary_max": profile.salary_max,
        # Cached profile embedding — drives semantic similarity in
        # compute_job_score. NULL until the resume has been embedded.
        "embedding": getattr(profile, "embedding", None),
        "skills": [
            {"skill_name": s.skill_name, "category": s.category}
            for s in profile.skills
        ],
        "work_history": [
            {
                "company": w.company,
                "title": w.title,
                "start_date": str(w.start_date) if w.start_date else None,
                "end_date": str(w.end_date) if w.end_date else None,
                "skills": w.skills or [],
                "domain_tags": w.domain_tags or [],
            }
            for w in sorted(profile.work_history, key=lambda w: w.sort_order)
        ],
    }
