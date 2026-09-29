"""The app prepares applications by itself.

Two kinds of work, on every scheduler run (`/cron/prepare-applications`):

- Applications waiting for the AI: "Apply for me" pressed while the AI was
  paused (the credit ran out) waits in "preparing" and is finished here
  once the AI is back, so nobody has to press it again.
- The user's best new matches: users who turn it on (Applications page, 1
  to 5 a day) get their best new jobs on Greenhouse, Lever or Ashby
  prepared for them: form read, answers filled in, resume written. They
  land in Needs you; nothing is ever sent without the user.

Each prepare takes up to a minute and costs about $0.15 of AI, so a run
does a few and the next run carries on. Automatic preparing stops when
the recorded credit is nearly gone (services/ai_credit.py).
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, or_, select

from app.core.database import create_worker_session
from app.models.auto_apply import AutoApplication
from app.models.candidate import CandidateProfile, CandidateSkill
from app.models.job import Job, JobEntity, JobSource
from app.models.job_state import UserJobState
from app.models.scoring import JobScore
from app.models.tracking import ApplicationTracking
from app.models.user import User
from app.services.auto_apply.ats import detect_ats
from app.services.jobs_filter import apply_user_filters

logger = logging.getLogger(__name__)

# The choices on the Applications page; 0 is off.
PER_DAY_CHOICES = (0, 1, 2, 3, 5)
PREFERENCE_KEY = "auto_prepare_per_day"
MIN_SCORE = 70.0
# A job the app hasn't seen listed for a week may have closed.
FRESH_DAYS = 7
MAX_AGE_DAYS = 30
# One application per company at a time: a second one inside this window
# would look like a spray.
SAME_COMPANY_DAYS = 30
# Left alone this long, a "preparing" application isn't being worked on.
WAITING_MINUTES = 10
COST_EACH_USD = 0.15

# Forms the app fills in, as a database pattern; detect_ats has the last word.
_SUPPORTED_FORM = r"://((job-boards|boards)(\.eu)?\.greenhouse\.io|jobs(\.eu)?\.lever\.co|jobs\.ashbyhq\.com)/"


def per_day(user: User) -> int:
    value = (user.preferences or {}).get(PREFERENCE_KEY) or 0
    return value if value in PER_DAY_CHOICES else 0


def _start_of_day(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


async def prepared_today(db, user_id: uuid.UUID, now: datetime) -> int:
    """Applications the app picked for the user today. Ones that couldn't
    be prepared (the form was gone, say) don't use up the day."""
    return (await db.execute(
        select(func.count()).select_from(AutoApplication).where(
            AutoApplication.user_id == user_id,
            AutoApplication.result["prepared_by"].astext == "app",
            AutoApplication.created_at >= _start_of_day(now),
            AutoApplication.status.notin_(("failed", "unsupported")),
        )
    )).scalar() or 0


async def pick_jobs_to_prepare(db, user_id: uuid.UUID, *, limit: int, now: datetime | None = None) -> list[uuid.UUID]:
    """The user's best new matches that the app can apply to: in their
    inbox (same filters), scoring MIN_SCORE or more, listed in the last
    week, on a form the app fills in, not dismissed, not applied to, no
    application yet, and at most one per company."""
    if limit <= 0:
        return []
    now = now or datetime.now(timezone.utc)
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

    has_application = select(AutoApplication.job_id).where(AutoApplication.user_id == user_id)
    tracked = select(ApplicationTracking.job_id).where(ApplicationTracking.user_id == user_id)
    form_url = func.coalesce(Job.apply_url, Job.job_url)
    query = (
        select(Job.id, Job.company, form_url)
        .join(JobScore, and_(JobScore.job_id == Job.id, JobScore.user_id == user_id))
        .outerjoin(JobSource, JobSource.id == Job.source_id)
        .outerjoin(JobEntity, JobEntity.job_id == Job.id)
        .outerjoin(UserJobState, and_(UserJobState.job_id == Job.id, UserJobState.user_id == user_id))
        .where(
            Job.status.notin_(["duplicate", "raw", "expired", "dismissed"]),
            Job.discovered_at >= now - timedelta(days=MAX_AGE_DAYS),
            func.coalesce(Job.last_seen_at, Job.discovered_at) >= now - timedelta(days=FRESH_DAYS),
            JobScore.overall_fit >= MIN_SCORE,
            form_url.op("~*")(_SUPPORTED_FORM),
            or_(UserJobState.status.is_(None), UserJobState.status != "dismissed"),
            Job.id.notin_(has_application),
            Job.id.notin_(tracked),
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
    candidates = (await db.execute(
        query.order_by(JobScore.overall_fit.desc(), Job.discovered_at.desc()).limit(limit * 10)
    )).all()

    recent_companies = {
        (company or "").strip().lower()
        for company in (await db.execute(
            select(Job.company)
            .join(AutoApplication, AutoApplication.job_id == Job.id)
            .where(
                AutoApplication.user_id == user_id,
                AutoApplication.created_at >= now - timedelta(days=SAME_COMPANY_DAYS),
                AutoApplication.status != "cancelled",
            )
        )).scalars().all()
    }
    picked: list[uuid.UUID] = []
    for job_id, company, url in candidates:
        key = (company or "").strip().lower()
        target = detect_ats(url)
        if target is None or target.board is None or not key or key in recent_companies:
            continue
        recent_companies.add(key)
        picked.append(job_id)
        if len(picked) == limit:
            break
    return picked


async def run(
    *,
    limit: int = 3,
    time_budget_seconds: float = 150.0,
    now: datetime | None = None,
    preparer=None,
    session_factory=None,
) -> dict:
    """Finish applications waiting for the AI, then prepare users' best
    matches, at most `limit` in all. Stops starting new ones once the time
    budget is spent; the next run carries on."""
    from app.llm.client import credits_paused
    from app.services.ai_credit import RESERVE_USD, credit_left
    from app.services.auto_apply.prepare import prepare_application

    preparer = preparer or prepare_application
    session_factory = session_factory or create_worker_session()
    now = now or datetime.now(timezone.utc)
    started = time.monotonic()
    outcome = {"finished": 0, "prepared": 0, "failed": 0, "paused": False, "low_credit": False, "errors": []}

    def time_left() -> bool:
        return time.monotonic() - started < time_budget_seconds

    if credits_paused():
        outcome["paused"] = True
        return outcome

    async with session_factory() as db:
        waiting = (await db.execute(
            select(AutoApplication.user_id, AutoApplication.job_id)
            .where(
                AutoApplication.status == "preparing",
                AutoApplication.updated_at < now - timedelta(minutes=WAITING_MINUTES),
            )
            .order_by(AutoApplication.updated_at)
            .limit(limit)
        )).all()

    async def prepare(user_id, job_id, counter: str, **kwargs) -> None:
        try:
            async with session_factory() as db:
                application = await preparer(db, user_id, job_id, tailor=True, **kwargs)
                done = application.status not in ("preparing", "failed")
            outcome[counter if done else "failed"] += 1
        except Exception as e:  # noqa: BLE001 — one application mustn't stop the others
            logger.exception("Preparing job %s for user %s failed", job_id, user_id)
            outcome["failed"] += 1
            outcome["errors"].append(f"{type(e).__name__}: {e}"[:200])

    for user_id, job_id in waiting:
        if not time_left() or credits_paused():
            break
        await prepare(user_id, job_id, "finished")
    budget = limit - outcome["finished"] - outcome["failed"]

    async with session_factory() as db:
        left = await credit_left(db)
        if left is not None and left < RESERVE_USD:
            outcome["low_credit"] = True
            return outcome
        users = [u for u in (await db.execute(select(User))).scalars().all() if per_day(u) > 0]
        by_user: dict[uuid.UUID, list[uuid.UUID]] = {}
        for user in users:
            remaining = per_day(user) - await prepared_today(db, user.id, now)
            by_user[user.id] = await pick_jobs_to_prepare(db, user.id, limit=min(remaining, budget), now=now)

    # Take turns between users, so one user's day doesn't use the whole run.
    turns = []
    while any(by_user.values()):
        for user_id, jobs in by_user.items():
            if jobs:
                turns.append((user_id, jobs.pop(0)))

    for user_id, job_id in turns[:max(0, budget)]:
        if not time_left() or credits_paused():
            break
        await prepare(user_id, job_id, "prepared", prepared_by="app")
    outcome["paused"] = credits_paused()
    return outcome
