from datetime import datetime, timedelta, timezone

from fastapi import APIRouter
from sqlalchemy import select, func, and_, or_

from app.api.deps import CurrentUserId, DbSession
from app.models.job import Job, JobEntity, JobSource
from app.models.job_state import UserJobState
from app.models.scoring import JobScore
from app.models.tracking import ApplicationTracking
from app.models.tailoring import TailoredApplication
from app.models.candidate import CandidateProfile
from app.services.jobs_filter import apply_user_filters, job_group_key

router = APIRouter()


@router.get("/overview")
async def get_overview(user_id: CurrentUserId, db: DbSession):
    """Get dashboard analytics overview."""
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)

    # Get user's profile (same fields the inbox uses for filtering)
    profile_result = await db.execute(
        select(
            CandidateProfile.id,
            CandidateProfile.target_roles,
            CandidateProfile.blocked_sources,
            CandidateProfile.remote_preference,
            CandidateProfile.preferred_countries,
            CandidateProfile.home_country,
            CandidateProfile.visa_statuses,
            CandidateProfile.salary_min,
            CandidateProfile.salary_currency,
        ).where(CandidateProfile.user_id == user_id)
    )
    profile_row = profile_result.first()
    profile_id = profile_row[0] if profile_row else None
    target_roles = profile_row[1] if profile_row else None
    blocked_sources = profile_row[2] if profile_row else None
    remote_preference = profile_row[3] if profile_row else None
    preferred_countries = profile_row[4] if profile_row else None

    # Skills feed the same title filter as the inbox so the dashboard's
    # 'Discovered' count matches what the user actually sees.
    from app.models.candidate import CandidateSkill
    user_skills: list[str] = []
    if profile_id:
        skills_result = await db.execute(
            select(CandidateSkill.skill_name).where(
                CandidateSkill.profile_id == profile_id,
                CandidateSkill.category.in_(("technical", "tool")),
            )
        )
        user_skills = [row[0] for row in skills_result.all() if row[0]]

    # Jobs discovered — exact same filter chain the inbox applies, so the
    # number on the dashboard always matches what the user actually sees.
    # Each job once, like the inbox: postings of the same job in several
    # cities or from several sources count as one.
    company_key, title_key = job_group_key(Job)
    jobs_query = (
        select(func.count(func.distinct(company_key + "|" + title_key)))
        .outerjoin(JobSource, JobSource.id == Job.source_id)
        .outerjoin(JobEntity, JobEntity.job_id == Job.id)
        .outerjoin(
            UserJobState,
            and_(UserJobState.job_id == Job.id, UserJobState.user_id == user_id),
        )
        .where(Job.status.notin_(["duplicate", "raw", "expired", "dismissed"]))
        .where(or_(UserJobState.status.is_(None), UserJobState.status != "dismissed"))
    )
    jobs_query = apply_user_filters(
        jobs_query,
        target_roles=target_roles,
        skills=user_skills,
        blocked_sources=blocked_sources,
        remote_preference=remote_preference,
        preferred_countries=preferred_countries,
        home_country=profile_row[5] if profile_row else None,
        visa_statuses=profile_row[6] if profile_row else None,
        salary_min=profile_row[7] if profile_row else None,
        salary_currency=profile_row[8] if profile_row else None,
        user_id=user_id,
    )
    jobs_result = await db.execute(jobs_query)
    jobs_discovered = jobs_result.scalar() or 0

    # Jobs shortlisted
    shortlisted_result = await db.execute(
        select(func.count(UserJobState.id)).where(
            UserJobState.user_id == user_id,
            UserJobState.status == "shortlisted",
        )
    )
    jobs_shortlisted = shortlisted_result.scalar() or 0

    # Applications sent
    applied_result = await db.execute(
        select(func.count(ApplicationTracking.id)).where(
            ApplicationTracking.user_id == user_id,
            ApplicationTracking.status.in_(["applied", "interviewing", "offered", "follow_up_due"]),
        )
    )
    applications_sent = applied_result.scalar() or 0

    # Applications this week
    week_result = await db.execute(
        select(func.count(ApplicationTracking.id)).where(
            ApplicationTracking.user_id == user_id,
            ApplicationTracking.applied_at >= week_ago,
        )
    )
    applications_this_week = week_result.scalar() or 0

    # Response rate (interviews / applications)
    interview_result = await db.execute(
        select(func.count(ApplicationTracking.id)).where(
            ApplicationTracking.user_id == user_id,
            ApplicationTracking.status.in_(["interviewing", "offered"]),
        )
    )
    interviews = interview_result.scalar() or 0

    response_rate = (interviews / applications_sent * 100) if applications_sent > 0 else 0
    interview_rate = (interviews / applications_sent * 100) if applications_sent > 0 else 0

    # Review queue count
    review_result = await db.execute(
        select(func.count(TailoredApplication.id)).where(
            TailoredApplication.user_id == user_id,
            TailoredApplication.approval_status == "ready",
        )
    )
    review_queue = review_result.scalar() or 0

    # Last successful discovery — proxy is the newest job's discovered_at
    # across the whole jobs table (not just this user's filtered view, since
    # the cron writes globally and a slow-day filter shouldn't make us
    # report "discovery is stale" when it actually ran). Used by the
    # dashboard's greeting hint to be honest about cron freshness.
    last_disc_result = await db.execute(select(func.max(Job.discovered_at)))
    last_discovery_at = last_disc_result.scalar()

    return {
        "jobs_discovered": jobs_discovered,
        "jobs_shortlisted": jobs_shortlisted,
        "applications_sent": applications_sent,
        "response_rate": round(response_rate, 1),
        "interview_rate": round(interview_rate, 1),
        "applications_this_week": applications_this_week,
        "review_queue": review_queue,
        "last_discovery_at": last_discovery_at.isoformat() if last_discovery_at else None,
    }
