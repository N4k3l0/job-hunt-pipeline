from datetime import datetime, timedelta, timezone

from fastapi import APIRouter
from sqlalchemy import select, func, or_

from app.api.deps import CurrentUserId, DbSession
from app.models.job import Job
from app.models.scoring import JobScore
from app.models.tracking import ApplicationTracking
from app.models.tailoring import TailoredApplication
from app.models.candidate import CandidateProfile

router = APIRouter()


def _build_role_keywords(target_roles: list[str] | None) -> list[str]:
    """Build title keywords from target roles."""
    if not target_roles:
        return []
    keywords = []
    for role in target_roles:
        role_lower = role.lower()
        keywords.append(f"%{role_lower}%")
        if "product" in role_lower:
            keywords.extend([
                "%product manager%", "%product lead%", "%product owner%",
                "%head of product%", "%product strateg%", "%product director%",
            ])
        if "data" in role_lower:
            keywords.extend(["%data scientist%", "%data analyst%", "%data engineer%"])
        if "design" in role_lower:
            keywords.extend(["%ux design%", "%ui design%", "%product design%"])
    return list(set(keywords))


@router.get("/overview")
async def get_overview(user_id: CurrentUserId, db: DbSession):
    """Get dashboard analytics overview."""
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)

    # Get user's target roles
    profile_result = await db.execute(
        select(CandidateProfile.target_roles).where(CandidateProfile.user_id == user_id)
    )
    target_roles = profile_result.scalar_one_or_none()
    role_keywords = _build_role_keywords(target_roles)

    # Jobs discovered (filtered by target roles — same logic as inbox)
    jobs_query = select(func.count(Job.id)).where(Job.status.notin_(["duplicate", "raw"]))
    if role_keywords:
        jobs_query = jobs_query.where(or_(*[func.lower(Job.title).like(kw) for kw in role_keywords]))
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
