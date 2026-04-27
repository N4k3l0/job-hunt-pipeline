from datetime import datetime, timedelta, timezone

from fastapi import APIRouter
from sqlalchemy import select, func, and_

from app.api.deps import CurrentUserId, DbSession
from app.models.job import Job, JobSource
from app.models.scoring import JobScore
from app.models.tracking import ApplicationTracking
from app.models.tailoring import TailoredApplication
from app.models.candidate import CandidateProfile
from app.services.jobs_filter import apply_user_filters

router = APIRouter()


@router.get("/overview")
async def get_overview(user_id: CurrentUserId, db: DbSession):
    """Get dashboard analytics overview."""
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)

    # Get user's profile (same fields the inbox uses for filtering)
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
    remote_preference = profile_row[2] if profile_row else None

    # Jobs discovered — exact same filter chain the inbox applies, so the
    # number on the dashboard always matches what the user actually sees.
    jobs_query = (
        select(func.count(func.distinct(Job.id)))
        .outerjoin(JobSource, JobSource.id == Job.source_id)
        .where(Job.status.notin_(["duplicate", "raw"]))
    )
    jobs_query = apply_user_filters(
        jobs_query,
        target_roles=target_roles,
        blocked_sources=blocked_sources,
        remote_preference=remote_preference,
    )
    jobs_result = await db.execute(jobs_query)
    jobs_discovered = jobs_result.scalar() or 0

    # Jobs shortlisted
    shortlisted_result = await db.execute(
        select(func.count(Job.id)).where(Job.status == "shortlisted")
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

    return {
        "jobs_discovered": jobs_discovered,
        "jobs_shortlisted": jobs_shortlisted,
        "applications_sent": applications_sent,
        "response_rate": round(response_rate, 1),
        "interview_rate": round(interview_rate, 1),
        "applications_this_week": applications_this_week,
        "review_queue": review_queue,
    }
