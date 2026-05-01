import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload

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


@celery_app.task(name="app.workers.scoring_tasks.score_job_for_user")
def score_job_for_user(job_id: str, user_id: str):
    """Score a single job for a specific user."""
    _run_async(_score_job_async(job_id, user_id))


async def _score_job_async(job_id: str, user_id: str):
    async with create_worker_session()() as db:
        # Get job + entities
        result = await db.execute(
            select(Job)
            .where(Job.id == job_id)
            .options(selectinload(Job.entities))
        )
        job = result.scalar_one_or_none()
        if not job:
            logger.error("Job %s not found for scoring", job_id)
            return

        # Get user profile
        profile_data = await _load_profile(db, user_id)
        if not profile_data:
            logger.warning("No profile for user %s, skipping scoring", user_id)
            return

        # Build job data dicts
        job_data = {
            "title": job.title,
            "company": job.company,
            "location": job.location,
            "country": job.country,
            "remote_type": job.remote_type,
            "salary_min": job.salary_min,
            "salary_max": job.salary_max,
            "seniority": job.seniority,
            "raw_description": job.raw_description or "",
        }

        job_entities = {}
        if job.entities:
            job_entities = {
                "skills": job.entities.skills or [],
                "requirements": job.entities.requirements or [],
                "keywords": job.entities.keywords or [],
                "visa_notes": job.entities.visa_notes,
                "sponsorship_available": job.entities.sponsorship_available,
            }

        # Compute score
        scores = compute_job_score(job_data, job_entities, profile_data)

        # Check for existing score
        existing = await db.execute(
            select(JobScore).where(
                and_(JobScore.job_id == job_id, JobScore.user_id == user_id)
            )
        )
        job_score = existing.scalar_one_or_none()

        if job_score:
            # Update existing
            for key, value in scores.items():
                setattr(job_score, key, value)
            job_score.calculated_at = datetime.now(timezone.utc)
        else:
            # Create new
            job_score = JobScore(
                job_id=job_id,
                user_id=user_id,
                calculated_at=datetime.now(timezone.utc),
                **scores,
            )
            db.add(job_score)

        # Update job status
        if job.status in ("enriched", "normalized"):
            job.status = "scored"

        await db.commit()
        logger.info(
            "Scored job %s for user %s: %.1f (%s, %s)",
            job_id, user_id, scores["overall_fit"], scores["priority"], scores["role_path"],
        )


@celery_app.task(name="app.workers.scoring_tasks.batch_score_for_user")
def batch_score_for_user(user_id: str, rescore_all: bool = False):
    """Score all unscored jobs for a user. If rescore_all=True, re-score everything."""
    _run_async(_batch_score_async(user_id, rescore_all))


async def _batch_score_async(user_id: str, rescore_all: bool = False):
    async with create_worker_session()() as db:
        # Get profile first
        profile_data = await _load_profile(db, user_id)
        if not profile_data:
            logger.warning("No profile for user %s, skipping batch scoring", user_id)
            return

        if rescore_all:
            # Delete all existing scores for this user and re-score
            from sqlalchemy import delete
            await db.execute(delete(JobScore).where(JobScore.user_id == user_id))
            await db.commit()
            logger.info("Cleared old scores for user %s for re-scoring", user_id)

        # Find unscored jobs (jobs without a score for this user)
        scored_job_ids = select(JobScore.job_id).where(JobScore.user_id == user_id)
        result = await db.execute(
            select(Job)
            .where(
                Job.status.notin_(["duplicate", "raw", "dismissed"]),
                Job.id.notin_(scored_job_ids),
            )
            .options(selectinload(Job.entities))
            .limit(5000)
        )
        jobs = result.scalars().all()

        if not jobs:
            logger.info("No unscored jobs for user %s", user_id)
            return

        logger.info("Batch scoring %d jobs for user %s", len(jobs), user_id)

        for job in jobs:
            job_data = {
                "title": job.title,
                "company": job.company,
                "location": job.location,
                "country": job.country,
                "remote_type": job.remote_type,
                "salary_min": job.salary_min,
                "salary_max": job.salary_max,
                "seniority": job.seniority,
                # Skill scoring scans the description for user-skill mentions
                # — sources with sparse tag lists (DailyRemote, Arbeitnow)
                # don't surface skills any other way.
                "raw_description": job.raw_description or "",
            }

            job_entities = {}
            if job.entities:
                job_entities = {
                    "skills": job.entities.skills or [],
                    "requirements": job.entities.requirements or [],
                    "keywords": job.entities.keywords or [],
                    "visa_notes": job.entities.visa_notes,
                    "sponsorship_available": job.entities.sponsorship_available,
                }

            # Deterministic filter: skip if title score would be 0 on both paths
            title_lower = job.title.lower()
            from app.services.scoring.pm_scorer import PM_TITLE_SCORES
            from app.services.scoring.ai_automation_scorer import AI_TITLE_SCORES
            has_pm_title = any(kw in title_lower for kw in PM_TITLE_SCORES)
            has_ai_title = any(kw in title_lower for kw in AI_TITLE_SCORES)
            if not has_pm_title and not has_ai_title:
                # Still score it, just with lower title match
                pass

            scores = compute_job_score(job_data, job_entities, profile_data)

            job_score = JobScore(
                job_id=job.id,
                user_id=user_id,
                calculated_at=datetime.now(timezone.utc),
                **scores,
            )
            db.add(job_score)

            if job.status in ("enriched", "normalized"):
                job.status = "scored"

        await db.commit()
        logger.info("Batch scoring complete: %d jobs scored for user %s", len(jobs), user_id)


async def _load_profile(db, user_id: str) -> dict | None:
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
        "preferred_countries": profile.preferred_countries or [],
        "visa_statuses": profile.visa_statuses or {},
        "remote_preference": profile.remote_preference or "any",
        "salary_min": profile.salary_min,
        "salary_max": profile.salary_max,
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
            for w in profile.work_history
        ],
    }
