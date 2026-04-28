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

    # Pull profile preferences once and run them through the shared filter
    # (same code path the dashboard's /analytics/overview uses, so the counts
    # always agree).
    from sqlalchemy import or_  # still used by role_type override below
    from app.services.jobs_filter import apply_user_filters
    profile_result = await db.execute(
        select(
            CandidateProfile.target_roles,
            CandidateProfile.blocked_sources,
            CandidateProfile.remote_preference,
        ).where(CandidateProfile.user_id == user_id)
    )
    profile_row = profile_result.first()
    target_roles = profile_row[0] if profile_row else None
    blocked_sources = profile_row[1] if profile_row else None
    profile_remote_pref = profile_row[2] if profile_row else None

    # role_type query param overrides the profile's target_roles.
    apply_target_roles = target_roles if not role_type else None
    # Explicit remote_type / remote_only query params override profile pref.
    effective_remote_pref = (
        None if (remote_type or remote_only) else profile_remote_pref
    )

    query = apply_user_filters(
        query,
        target_roles=apply_target_roles,
        blocked_sources=blocked_sources,
        remote_preference=effective_remote_pref,
    )

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

    # Count total — apply identical filter chain through the shared helper.
    count_base = (
        select(func.count(func.distinct(Job.id)))
        .outerjoin(JobScore, and_(JobScore.job_id == Job.id, JobScore.user_id == user_id))
        .outerjoin(JobSource, JobSource.id == Job.source_id)
        .outerjoin(JobEntity, JobEntity.job_id == Job.id)
        .where(Job.status.notin_(["duplicate", "raw"]))
    )
    count_base = apply_user_filters(
        count_base,
        target_roles=apply_target_roles,
        blocked_sources=blocked_sources,
        remote_preference=effective_remote_pref,
    )
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
    """Run all free/no-key discovery sources synchronously inside this request.

    Vercel-friendly: returns when each source finishes (or errors). At ~3-8s
    per source the total stays within the 60s limit. Crossover (slowest) is
    excluded here because it can blow the limit alone — it has its own cron
    endpoint at /api/v1/cron/discover-slow."""
    from app.workers.discovery_tasks import (
        _run_adzuna_async, _run_remoteok_async, _run_arbeitnow_async,
        _run_himalayas_async, _run_remotive_async, _run_weworkremotely_async,
        _run_dailyremote_async,
    )
    runners = [
        ("adzuna", _run_adzuna_async),
        ("remoteok", _run_remoteok_async),
        ("arbeitnow", _run_arbeitnow_async),
        ("himalayas", _run_himalayas_async),
        ("remotive", _run_remotive_async),
        ("weworkremotely", _run_weworkremotely_async),
        ("dailyremote", _run_dailyremote_async),
    ]
    results: dict[str, str] = {}
    for name, runner in runners:
        try:
            await runner()
            results[name] = "ok"
        except Exception as e:
            logger.error("Discovery '%s' failed: %s", name, e)
            results[name] = f"error: {type(e).__name__}: {e}"
    return {"status": "complete", "results": results}


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
