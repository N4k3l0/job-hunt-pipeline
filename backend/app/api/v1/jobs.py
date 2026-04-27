import logging
from uuid import UUID

from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func, and_
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUserId, DbSession
from app.models.job import Job, JobEntity, JobSource
from app.models.scoring import JobScore
from app.models.candidate import CandidateProfile

logger = logging.getLogger(__name__)

router = APIRouter()


class JobImportURL(BaseModel):
    url: str


class JobImportText(BaseModel):
    text: str
    source: str = "manual"


@router.get("")
async def list_jobs(
    user_id: CurrentUserId,
    db: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    role_type: str | None = None,
    country: str | None = None,
    remote_only: bool = False,
    remote_type: str | None = None,
    sponsorship: bool = False,
    source: str | None = None,
    min_score: float | None = None,
    sort_by: str = "score",
    status: str | None = None,
):
    """List jobs in the user's inbox with filters and pagination."""
    # Base query
    query = (
        select(Job, JobScore, JobSource)
        .outerjoin(JobScore, and_(JobScore.job_id == Job.id, JobScore.user_id == user_id))
        .outerjoin(JobSource, JobSource.id == Job.source_id)
        .outerjoin(JobEntity, JobEntity.job_id == Job.id)
        .where(Job.status.notin_(["duplicate", "raw"]))
    )

    # Auto-filter by user's target roles (only show relevant jobs)
    from sqlalchemy import or_
    profile_result = await db.execute(
        select(CandidateProfile.target_roles).where(CandidateProfile.user_id == user_id)
    )
    target_roles = profile_result.scalar_one_or_none()
    role_keywords = []
    keywords = []
    if target_roles and not role_type:
        # Build keywords from target roles
        from sqlalchemy import or_
        role_keywords = []
        for role in target_roles:
            role_lower = role.lower()
            role_keywords.append(f"%{role_lower}%")
            # Add related keywords for common roles
            if "product" in role_lower:
                role_keywords.extend([
                    "%product manager%", "%product lead%", "%product owner%",
                    "%head of product%", "%product strateg%", "%product director%",
                ])
            if "ai" in role_lower or "automation" in role_lower:
                role_keywords.extend([
                    "%ai %", "% ai", "%artificial intelligence%", "%machine learning%",
                    "%automation%", "%llm%", "%ml engineer%",
                ])
        # Deduplicate
        role_keywords = list(set(role_keywords))
        query = query.where(or_(*[func.lower(Job.title).like(kw) for kw in role_keywords]))

    # Apply filters
    if country:
        query = query.where(Job.country == country.upper())
    if remote_type:
        if remote_type == "unknown":
            query = query.where(Job.remote_type == None)
        else:
            query = query.where(Job.remote_type == remote_type)
    elif remote_only:
        query = query.where(Job.remote_type == "full_remote")
    if sponsorship:
        query = query.where(JobEntity.sponsorship_available == True)
    if source:
        query = query.where(JobSource.name == source)
    if min_score is not None:
        query = query.where(JobScore.overall_fit >= min_score)
    if role_type:
        if role_type == "pm":
            keywords = [
                "%product manager%", "%product lead%", "%product owner%",
                "%head of product%", "%product strateg%", "%product director%",
                "%group product manager%", "%product analyst%",
            ]
        elif role_type == "ai_automation":
            keywords = [
                "%ai %", "% ai", "%artificial intelligence%", "%machine learning%",
                "%ml engineer%", "%automation%", "%llm%", "%deep learning%",
                "%nlp%", "%data scien%", "%prompt engineer%", "%mlops%",
            ]
        else:
            keywords = [f"%{role_type}%"]

        query = query.where(or_(*[func.lower(Job.title).like(kw) for kw in keywords]))
    if status:
        query = query.where(Job.status == status)

    # Count total — build a parallel count query with same filters
    count_base = (
        select(func.count(func.distinct(Job.id)))
        .outerjoin(JobScore, and_(JobScore.job_id == Job.id, JobScore.user_id == user_id))
        .outerjoin(JobSource, JobSource.id == Job.source_id)
        .outerjoin(JobEntity, JobEntity.job_id == Job.id)
        .where(Job.status.notin_(["duplicate", "raw"]))
    )
    # Apply same filters to count
    if target_roles and not role_type:
        count_base = count_base.where(or_(*[func.lower(Job.title).like(kw) for kw in role_keywords]))
    if country:
        count_base = count_base.where(Job.country == country.upper())
    if remote_type:
        if remote_type == "unknown":
            count_base = count_base.where(Job.remote_type == None)
        else:
            count_base = count_base.where(Job.remote_type == remote_type)
    elif remote_only:
        count_base = count_base.where(Job.remote_type == "full_remote")
    if sponsorship:
        count_base = count_base.where(JobEntity.sponsorship_available == True)
    if source:
        count_base = count_base.where(JobSource.name == source)
    if min_score is not None:
        count_base = count_base.where(JobScore.overall_fit >= min_score)
    if role_type:
        count_base = count_base.where(or_(*[func.lower(Job.title).like(kw) for kw in keywords]))
    if status:
        count_base = count_base.where(Job.status == status)
    total_result = await db.execute(count_base)
    total = total_result.scalar() or 0

    # Sort
    if sort_by == "score":
        query = query.order_by(JobScore.overall_fit.desc().nulls_last())
    elif sort_by == "date":
        query = query.order_by(Job.discovered_at.desc())
    elif sort_by == "salary":
        query = query.order_by(Job.salary_max.desc().nulls_last())
    else:
        query = query.order_by(Job.discovered_at.desc())

    # Paginate
    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)

    result = await db.execute(query)
    rows = result.unique().all()

    # Serialize with score and source included
    jobs_out = []
    for row in rows:
        job = row[0]  # Job
        score = row[1]  # JobScore or None
        job_source = row[2]  # JobSource or None

        job_dict = {
            "id": str(job.id),
            "company": job.company,
            "title": job.title,
            "location": job.location,
            "country": job.country,
            "remote_type": job.remote_type,
            "job_url": job.job_url,
            "apply_url": job.apply_url,
            "salary_text": job.salary_text,
            "salary_min": job.salary_min,
            "salary_max": job.salary_max,
            "salary_currency": job.salary_currency,
            "employment_type": job.employment_type,
            "seniority": job.seniority,
            "application_type": job.application_type,
            "source_name": job_source.name if job_source else "manual",
            "status": job.status,
            "discovered_at": job.discovered_at.isoformat() if job.discovered_at else None,
            "expires_at": job.expires_at.isoformat() if job.expires_at else None,
            "score": {
                "role_path": score.role_path,
                "overall_fit": score.overall_fit,
                "priority": score.priority,
                "title_score": score.title_score,
                "skill_score": score.skill_score,
                "seniority_score": score.seniority_score,
                "industry_score": score.industry_score,
                "geo_score": score.geo_score,
                "remote_score": score.remote_score,
                "salary_score": score.salary_score,
                "visa_score": score.visa_score,
            } if score else None,
        }
        jobs_out.append(job_dict)

    return {
        "jobs": jobs_out,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{job_id}")
async def get_job(job_id: UUID, user_id: CurrentUserId, db: DbSession):
    """Get full job details including score and entities."""
    result = await db.execute(
        select(Job)
        .where(Job.id == job_id)
        .options(selectinload(Job.entities), selectinload(Job.source))
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Get user's score for this job
    score_result = await db.execute(
        select(JobScore).where(
            JobScore.job_id == job_id,
            JobScore.user_id == user_id,
        )
    )
    score = score_result.scalar_one_or_none()

    return {
        "id": str(job.id),
        "company": job.company,
        "title": job.title,
        "location": job.location,
        "country": job.country,
        "remote_type": job.remote_type,
        "job_url": job.job_url,
        "apply_url": job.apply_url,
        "salary_text": job.salary_text,
        "salary_min": job.salary_min,
        "salary_max": job.salary_max,
        "salary_currency": job.salary_currency,
        "employment_type": job.employment_type,
        "seniority": job.seniority,
        "application_type": job.application_type,
        "source_name": job.source.name if job.source else "manual",
        "status": job.status,
        "raw_description": job.raw_description,
        "discovered_at": job.discovered_at.isoformat() if job.discovered_at else None,
        "expires_at": job.expires_at.isoformat() if job.expires_at else None,
        "entities": {
            "skills": job.entities.skills if job.entities else None,
            "requirements": job.entities.requirements if job.entities else None,
            "keywords": job.entities.keywords if job.entities else None,
            "nice_to_have": job.entities.nice_to_have if job.entities else None,
            "visa_notes": job.entities.visa_notes if job.entities else None,
            "sponsorship_available": job.entities.sponsorship_available if job.entities else None,
            "application_questions": job.entities.application_questions if job.entities else None,
            "years_experience_min": job.entities.years_experience_min if job.entities else None,
            "years_experience_max": job.entities.years_experience_max if job.entities else None,
        } if job.entities else None,
        "score": {
            "role_path": score.role_path,
            "title_score": score.title_score,
            "skill_score": score.skill_score,
            "seniority_score": score.seniority_score,
            "industry_score": score.industry_score,
            "geo_score": score.geo_score,
            "remote_score": score.remote_score,
            "salary_score": score.salary_score,
            "visa_score": score.visa_score,
            "overall_fit": score.overall_fit,
            "priority": score.priority,
            "reasoning": score.reasoning,
            "calculated_at": score.calculated_at.isoformat() if score.calculated_at else None,
            "deep_score": score.deep_score_json,
        } if score else None,
    }


@router.post("/{job_id}/deep-score")
async def deep_score_job(
    job_id: UUID,
    user_id: CurrentUserId,
    db: DbSession,
    force: bool = Query(False, description="Re-run even if a cached deep score exists"),
):
    """Run LLM-based deep scoring for a job against the user's profile.

    Sends the user's resume/profile and the full job description to Claude
    for a detailed fitness assessment. Results are cached on the JobScore record.
    """
    from app.services.scoring.deep_scorer import run_deep_score

    try:
        result = await run_deep_score(
            db=db,
            job_id=str(job_id),
            user_id=str(user_id),
            force=force,
        )
        await db.commit()
        return {
            "job_id": str(job_id),
            "deep_score": result,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        logger.error("Deep scoring failed for job %s: %s", job_id, e)
        raise HTTPException(status_code=502, detail="Deep scoring failed — LLM did not return structured output")


@router.post("/discover")
async def trigger_discovery(user_id: CurrentUserId):
    """Manually trigger job discovery from all free/no-key sources."""
    from app.workers.discovery_tasks import (
        run_adzuna_discovery, run_remoteok_discovery,
        run_arbeitnow_discovery, run_himalayas_discovery,
        run_remotive_discovery, run_weworkremotely_discovery,
        run_crossover_discovery,
    )
    run_adzuna_discovery.delay()
    run_remoteok_discovery.delay()
    run_arbeitnow_discovery.delay()
    run_himalayas_discovery.delay()
    run_remotive_discovery.delay()
    run_weworkremotely_discovery.delay()
    run_crossover_discovery.delay()
    return {
        "status": "queued",
        "sources": [
            "adzuna", "remoteok", "arbeitnow",
            "himalayas", "remotive", "weworkremotely", "crossover",
        ],
    }


@router.post("/import/url")
async def import_job_url(request: JobImportURL, user_id: CurrentUserId, db: DbSession):
    """Import a job by URL (Firecrawl + Claude parsing)."""
    from app.workers.parsing_tasks import parse_job_from_url
    parse_job_from_url.delay(request.url)
    return {"status": "queued", "url": request.url}


@router.post("/import/text")
async def import_job_text(request: JobImportText, user_id: CurrentUserId, db: DbSession):
    """Import a job by pasting text (Claude parsing)."""
    from app.workers.parsing_tasks import parse_job_from_text
    parse_job_from_text.delay(request.text, request.source)
    return {"status": "queued", "source": request.source}


@router.post("/{job_id}/shortlist")
async def shortlist_job(job_id: UUID, user_id: CurrentUserId, db: DbSession):
    """Move a job to shortlisted status."""
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job.status = "shortlisted"
    await db.commit()
    return {"status": "shortlisted", "job_id": str(job_id)}


@router.post("/{job_id}/dismiss")
async def dismiss_job(job_id: UUID, user_id: CurrentUserId, db: DbSession):
    """Dismiss/archive a job."""
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job.status = "dismissed"
    await db.commit()
    return {"status": "dismissed", "job_id": str(job_id)}
