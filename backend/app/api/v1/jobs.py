import logging
from datetime import datetime, timezone
from uuid import UUID

import httpx
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func, and_
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUserId, DbSession
from app.models.job import Job, JobContact, JobEntity, JobSource
from app.models.scoring import JobScore
from app.models.candidate import CandidateProfile
from app.models.tracking import ApplicationTracking
from app.services.discovery.ats_resolver import find_direct_apply, is_ats_url, _is_aggregator

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
    # Default to 50 so the inbox surfaces actual matches, not noise.
    # Frontend can pass min_score=0 to show everything (including unscored
    # jobs, which appear with overall_fit IS NULL — see filter below).
    min_score: float | None = 50,
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
        .where(Job.status.notin_(["duplicate", "raw", "expired", "dismissed"]))
    )

    # Pull profile preferences once and run them through the shared filter
    # (same code path the dashboard's /analytics/overview uses, so the counts
    # always agree).
    from sqlalchemy import or_  # still used by role_type override below
    from app.services.jobs_filter import apply_user_filters
    from app.models.candidate import CandidateSkill
    profile_result = await db.execute(
        select(
            CandidateProfile.id,
            CandidateProfile.target_roles,
            CandidateProfile.blocked_sources,
            CandidateProfile.remote_preference,
        ).where(CandidateProfile.user_id == user_id)
    )
    profile_row = profile_result.first()
    profile_id = profile_row[0] if profile_row else None
    target_roles = profile_row[1] if profile_row else None
    blocked_sources = profile_row[2] if profile_row else None
    profile_remote_pref = profile_row[3] if profile_row else None

    # Skills also feed the title filter, so a 'Python Developer' role
    # surfaces for someone whose target_roles say AI Engineer but whose
    # skills include Python.
    user_skills: list[str] = []
    if profile_id:
        skills_result = await db.execute(
            select(CandidateSkill.skill_name).where(
                CandidateSkill.profile_id == profile_id,
                CandidateSkill.category.in_(("technical", "tool")),
            )
        )
        user_skills = [row[0] for row in skills_result.all() if row[0]]

    # role_type query param overrides the profile's target_roles.
    apply_target_roles = target_roles if not role_type else None
    # Explicit remote_type / remote_only query params override profile pref.
    effective_remote_pref = (
        None if (remote_type or remote_only) else profile_remote_pref
    )

    query = apply_user_filters(
        query,
        target_roles=apply_target_roles,
        skills=user_skills if not role_type else None,
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
    # Only apply min_score if the user has scored jobs at all. A new
    # account with no scores yet would otherwise see an empty inbox
    # because LEFT JOINs leave overall_fit IS NULL, and NULL >= 50 is
    # false. Falling back to the apply_user_filters relevance filter
    # keeps the inbox useful while scoring catches up.
    has_scores = False
    if min_score is not None:
        has_scores_q = select(func.count()).select_from(JobScore).where(
            JobScore.user_id == user_id
        )
        has_scores = ((await db.execute(has_scores_q)).scalar() or 0) > 0
        if has_scores:
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
        .where(Job.status.notin_(["duplicate", "raw", "expired", "dismissed"]))
    )
    count_base = apply_user_filters(
        count_base,
        target_roles=apply_target_roles,
        skills=user_skills if not role_type else None,
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
    if min_score is not None and has_scores:
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
        # Profile or job missing — caller can fix by setting up profile.
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        logger.error("Deep scoring failed for job %s: %s", job_id, e)
        raise HTTPException(
            status_code=502,
            detail=f"Deep scoring failed — {e}",
        )
    except Exception as e:  # noqa: BLE001
        # Anthropic API errors, network issues, validation problems —
        # surface the actual message so the frontend toast can show it.
        # Used to swallow these as generic 500s and the user just saw
        # 'Analysis failed' with no clue what was wrong.
        logger.exception("Deep scoring unexpected failure for job %s", job_id)
        raise HTTPException(
            status_code=500,
            detail=f"{type(e).__name__}: {e}",
        )


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


@router.post("/{job_id}/apply")
async def resolve_apply_url(job_id: UUID, user_id: CurrentUserId, db: DbSession):
    """Resolve the best apply URL (no tracking side-effects).

    The frontend opens a placeholder window first (so the popup blocker is
    happy), then POSTs here to get back `{ url, is_direct_ats }`, then
    rewrites the popup to that URL.

    Crucially: clicking "Apply directly" does NOT mark the job as applied.
    The user might find the role doesn't exist, isn't eligible for their
    region, or just decides to skip. They have to explicitly press
    "I applied" (POST /{job_id}/mark-applied) once they've actually
    submitted the application.

    Resolution order (cheapest first):
      1. apply_url / job_url is already on a known free ATS → use it.
      2. Follow the source URL's redirect chain — many aggregators 30x
         straight to the ATS for free.
      3. Slug-guess across Greenhouse → Lever → Ashby → SmartRecruiters
         using the company name. Cache on the job row.
      4. Fall back to whatever source URL we have.
    """
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    source = job.apply_url or job.job_url
    resolved = await find_direct_apply(
        company=job.company or "",
        title=job.title or "",
        source_url=source,
    )
    if resolved and resolved != job.apply_url and not _is_aggregator(resolved):
        # Cache any verified non-aggregator URL — Claude can return company
        # careers-page URLs that aren't on the strict ATS host list but are
        # still canonical direct-apply links worth caching.
        job.apply_url = resolved
        await db.commit()
    final_url = resolved or source

    # If the only URL we have is still on an aggregator (resolver came up
    # empty), refuse to send the user there. We don't want to fall back to
    # a Google search either — that just kicks the same problem to the
    # user. Return a 422 with company/title context so the frontend can
    # render an explicit "couldn't find a direct posting" message and
    # offer a manual escape hatch.
    if final_url and _is_aggregator(final_url):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "no_direct_posting",
                "message": "Couldn't find a direct posting for this role on a free ATS or the company's careers page.",
                "company": job.company,
                "title": job.title,
                "aggregator_url": final_url,
            },
        )

    if not final_url:
        raise HTTPException(status_code=404, detail="No URL available for this job")
    return {
        "url": final_url,
        "is_direct_ats": is_ats_url(final_url),
    }


@router.post("/{job_id}/mark-applied")
async def mark_applied(job_id: UUID, user_id: CurrentUserId, db: DbSession):
    """Explicit user action: 'I just submitted this application.'

    Creates / updates the ApplicationTracking row to status='applied' and
    flips the job's own status so the inbox stops surfacing it as fresh.
    Idempotent: re-pressing won't downgrade an interview/offer/rejected.
    """
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    existing = await db.execute(
        select(ApplicationTracking).where(
            ApplicationTracking.job_id == job_id,
            ApplicationTracking.user_id == user_id,
        )
    )
    tracking = existing.scalar_one_or_none()
    if tracking is None:
        tracking = ApplicationTracking(
            job_id=job_id,
            user_id=user_id,
            status="applied",
            applied_at=datetime.now(timezone.utc),
        )
        db.add(tracking)
    else:
        if tracking.status not in ("interviewing", "offered", "rejected"):
            tracking.status = "applied"
            if not tracking.applied_at:
                tracking.applied_at = datetime.now(timezone.utc)

    if job.status not in ("applied", "shortlisted"):
        job.status = "applied"

    await db.commit()
    await db.refresh(tracking)
    return {
        "tracking_id": str(tracking.id),
        "status": tracking.status,
        "applied_at": tracking.applied_at.isoformat() if tracking.applied_at else None,
    }


@router.post("/{job_id}/unmark-applied")
async def unmark_applied(job_id: UUID, user_id: CurrentUserId, db: DbSession):
    """Roll back an accidental 'I applied' click. Removes the tracking row
    iff its status is still 'applied' (won't touch interview/offer history)."""
    result = await db.execute(
        select(ApplicationTracking).where(
            ApplicationTracking.job_id == job_id,
            ApplicationTracking.user_id == user_id,
        )
    )
    tracking = result.scalar_one_or_none()
    if tracking and tracking.status == "applied":
        await db.delete(tracking)

    job_result = await db.execute(select(Job).where(Job.id == job_id))
    job = job_result.scalar_one_or_none()
    if job and job.status == "applied":
        job.status = "discovered"

    await db.commit()
    return {"status": "rolled_back"}


def _serialize_contact(contact: JobContact) -> dict:
    return {
        "name": contact.name,
        "title": contact.title,
        "linkedin_url": contact.linkedin_url,
        "email_guess": contact.email_guess,
        "confidence": contact.confidence,
        "source_notes": contact.source_notes,
        "citations": contact.citations or [],
        "searched_at": contact.searched_at.isoformat() if contact.searched_at else None,
        "cached": True,
    }


@router.get("/{job_id}/contact")
async def get_contact(job_id: UUID, user_id: CurrentUserId, db: DbSession):
    """Return the cached decision-maker lookup for this job, if any.
    Lookups are cached at the job level (one row per job) since two
    users at the same company+role would get the same result."""
    job_result = await db.execute(select(Job).where(Job.id == job_id))
    job = job_result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    contact_result = await db.execute(
        select(JobContact).where(JobContact.job_id == job_id)
    )
    contact = contact_result.scalar_one_or_none()
    if not contact:
        return {"contact": None}
    return {"contact": _serialize_contact(contact)}


@router.post("/{job_id}/find-contact")
async def find_contact(
    job_id: UUID,
    user_id: CurrentUserId,
    db: DbSession,
    force: bool = Query(False, description="Bypass cache and re-search"),
):
    """Run a Claude + web_search lookup for the hiring manager / decision
    maker for this role. Result is cached on the job (one row per job).
    Pass ?force=true to refresh."""
    job_result = await db.execute(select(Job).where(Job.id == job_id))
    job = job_result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    contact_result = await db.execute(
        select(JobContact).where(JobContact.job_id == job_id)
    )
    contact = contact_result.scalar_one_or_none()

    if contact and not force:
        return {"contact": _serialize_contact(contact)}

    from app.services.outreach.contact_finder import find_contact_for_job
    try:
        result = await find_contact_for_job(
            company=job.company,
            role=job.title,
            location=job.location,
        )
    except Exception as e:  # noqa: BLE001
        logger.error("find_contact_for_job failed for %s: %s", job_id, e)
        raise HTTPException(status_code=502, detail=f"Contact lookup failed: {e}")

    if contact is None:
        contact = JobContact(job_id=job_id)
        db.add(contact)

    contact.name = result.get("name")
    contact.title = result.get("title")
    contact.linkedin_url = result.get("linkedin_url")
    contact.email_guess = result.get("email_guess")
    contact.confidence = result.get("confidence")
    contact.source_notes = result.get("source_notes")
    contact.citations = result.get("citations") or []
    contact.searched_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(contact)
    payload = _serialize_contact(contact)
    payload["cached"] = False
    return {"contact": payload}


# ── Bullet tailoring ────────────────────────────────────────────────────────


_TAILOR_BULLETS_TOOL = {
    "name": "rank_and_rewrite_bullets",
    "description": (
        "Rank the candidate's resume bullets by relevance to the target job, "
        "and rewrite each one to emphasize the angle that this specific role "
        "cares about. Never invent facts."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "ranked_bullets": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "bullet_id": {
                            "type": "string",
                            "description": "The id field copied verbatim from the input bullet.",
                        },
                        "relevance": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 5,
                            "description": (
                                "5 = direct hit on a stated requirement; "
                                "4 = strong match; 3 = useful supporting evidence; "
                                "2 = tangential; 1 = irrelevant — leave it but flag it."
                            ),
                        },
                        "tailored": {
                            "type": "string",
                            "description": (
                                "Rewritten bullet emphasizing the angle this job cares about. "
                                "Must cover the SAME achievement as the original — never invent "
                                "a tool, metric, employer, or outcome that isn't in the original."
                            ),
                        },
                        "why_it_matches": {
                            "type": "string",
                            "description": (
                                "One sentence: which JD requirement / skill / responsibility "
                                "does this bullet hit? Be specific."
                            ),
                        },
                    },
                    "required": ["bullet_id", "relevance", "tailored", "why_it_matches"],
                },
            },
        },
        "required": ["ranked_bullets"],
    },
}


_TAILOR_BULLETS_SYSTEM = (
    "You rank a candidate's resume bullets by relevance to a specific job posting "
    "and rewrite each one to emphasize the angle that job cares about.\n\n"
    "Hard rules:\n"
    "- The tailored rewrite covers the SAME achievement as the original. Never invent "
    "  tools, metrics, employers, or outcomes the candidate didn't state.\n"
    "- Emphasize keywords, skills, and outcomes that match the job's requirements.\n"
    "- Match the candidate's voice. If style examples are provided, mimic their "
    "  rhythm, tone, openers, and how they frame achievements.\n"
    "- Score relevance 1–5: 5 = direct hit on a stated requirement; 4 = strong match; "
    "  3 = useful supporting evidence; 2 = tangential; 1 = irrelevant.\n"
    "- Return EVERY bullet you were given, in descending relevance order.\n\n"
    "Call rank_and_rewrite_bullets exactly once with all of them."
)


@router.post("/{job_id}/tailor-bullets")
async def tailor_bullets(
    job_id: UUID,
    user_id: CurrentUserId,
    db: DbSession,
):
    """Rank + rewrite the user's resume bullets for a specific job.

    Reuses the bullet bank populated by the resume parser plus the user's
    writing samples (so rewrites match their voice). Returns one row per
    original bullet with: original text, tailored rewrite, relevance score
    (1-5), and a one-sentence justification.

    Strict guardrails: the LLM is told never to invent facts. It rewrites
    the same achievement under a different emphasis — same employer, same
    metrics, same scope.
    """
    from app.models.candidate import CandidateProfile, CandidateBullet
    from app.llm.client import llm_client
    from app.services.tailoring.tailor_service import (
        _load_samples_by_kind, _style_examples_block,
    )

    # Load job + entities for the JD context.
    job_result = await db.execute(
        select(Job).where(Job.id == job_id).options(selectinload(Job.entities))
    )
    job = job_result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Load profile + bullets.
    profile_result = await db.execute(
        select(CandidateProfile).where(CandidateProfile.user_id == user_id)
    )
    profile = profile_result.scalar_one_or_none()
    if not profile:
        raise HTTPException(
            status_code=400,
            detail="Set up your profile first — Profile → Resumes.",
        )

    bullets_result = await db.execute(
        select(CandidateBullet)
        .where(CandidateBullet.profile_id == profile.id)
        .order_by(CandidateBullet.created_at.desc())
    )
    bullets = bullets_result.scalars().all()
    if not bullets:
        raise HTTPException(
            status_code=400,
            detail=(
                "No bullets to tailor — upload a resume on Profile → Resumes "
                "and the parser will populate your bullet bank."
            ),
        )

    # Cap the prompt — beyond ~30 bullets the LLM context wastes the budget
    # on bullets that clearly won't make any cut anyway.
    bullets = list(bullets)[:30]

    # Pull the user's writing samples — summary samples teach voice for
    # achievement bullets specifically.
    samples_by_kind = await _load_samples_by_kind(db, str(user_id))
    style_block = _style_examples_block(
        samples_by_kind.get("summary", []) + samples_by_kind.get("cover_letter", []),
        "achievement bullet",
    )

    # JD context: pull entity-extracted skills / requirements / keywords if
    # we have them; fall back to raw description otherwise.
    job_skills = (job.entities.skills if job.entities else None) or []
    job_requirements = (job.entities.requirements if job.entities else None) or []
    job_keywords = (job.entities.keywords if job.entities else None) or []

    # Bullet input format — ID is the stable key the LLM echoes back so we
    # can map rewrites to originals reliably.
    bullets_payload = "\n".join(
        f'- id="{b.id}" text="{(b.text or "").strip()}" '
        f'tags={(b.domain_tags or [])} keywords={(b.keywords or [])[:6]}'
        for b in bullets
    )

    user_prompt = (
        f"{style_block}"
        "## Job\n"
        f"Title: {job.title}\n"
        f"Company: {job.company}\n"
        f"Required skills: {', '.join(job_skills[:20]) or '(unspecified)'}\n"
        f"Requirements: {'; '.join(job_requirements[:15]) or '(unspecified)'}\n"
        f"Keywords: {', '.join(job_keywords[:20]) or '(unspecified)'}\n"
        f"Description excerpt:\n{(job.raw_description or '')[:2000]}\n\n"
        "## Candidate context\n"
        f"Headline: {profile.headline or '(none)'}\n"
        f"Summary: {profile.master_summary or '(none)'}\n\n"
        "## Bullets to rank + rewrite\n"
        f"{bullets_payload}\n"
    )

    try:
        result = await llm_client.generate_structured(
            task_type="tailoring",
            system_prompt=_TAILOR_BULLETS_SYSTEM,
            user_prompt=user_prompt,
            tools=[_TAILOR_BULLETS_TOOL],
            max_tokens=4096,
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("Bullet tailoring failed for job %s", job_id)
        raise HTTPException(status_code=502, detail=f"Bullet tailoring failed: {type(e).__name__}: {e}")

    # Map LLM output back to originals so the frontend gets full context.
    bullet_map = {str(b.id): b for b in bullets}
    out: list[dict] = []
    for r in result.get("ranked_bullets", []):
        bid = str(r.get("bullet_id", ""))
        original = bullet_map.get(bid)
        if not original:
            continue
        out.append({
            "id": bid,
            "original": original.text,
            "tailored": r.get("tailored") or "",
            "relevance": int(r.get("relevance") or 1),
            "why_it_matches": r.get("why_it_matches") or "",
        })

    # If the LLM dropped any bullets, append them at the end with relevance=0
    # so the user can still see they exist (and re-tailor if needed).
    seen = {row["id"] for row in out}
    for b in bullets:
        if str(b.id) not in seen:
            out.append({
                "id": str(b.id),
                "original": b.text,
                "tailored": b.text,
                "relevance": 0,
                "why_it_matches": "(not ranked by the model)",
            })

    return {"bullets": out, "job_id": str(job_id)}
