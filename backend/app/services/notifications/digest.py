"""The daily email: new matches, and what's waiting on the user.

It lists the best new inbox jobs since the last email (the inbox's filters,
score 50+, one posting per job), applications that need the user's
answers, recently tailored applications ready to review, and follow-ups
due. Nothing is sent on a day with nothing to say.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from html import escape
from uuid import UUID

from sqlalchemy import and_, exists, func, or_, select

from app.core.config import get_settings
from app.models.auto_apply import AutoApplication
from app.models.job import Job, JobEntity, JobSource
from app.models.job_state import UserJobState
from app.models.scoring import JobScore
from app.models.tailoring import TailoredApplication
from app.models.tracking import ApplicationTracking
from app.models.user import User
from app.services.auto_apply import answers as rules
from app.services.job_state import APPLIED_TRACKING_STATUSES
from app.services.jobs_filter import apply_user_filters, job_group_key, user_filter_kwargs
from app.services.notifications.email import (
    EmailFailed, EmailNotConfigured, api_public_url, email_configured, frontend_url, send_email,
)

logger = logging.getLogger(__name__)

INBOX_MIN_SCORE = 50
TOP_MATCHES = 5
# The first email, or one after a long gap, looks back this far at most.
MAX_LOOKBACK = timedelta(days=3)
# Older tailored drafts aren't brought up again every day.
TAILORED_RECENT = timedelta(days=14)

ACCENT = "#1f9d7a"


@dataclass
class DigestJob:
    id: UUID
    title: str
    company: str
    location: str | None
    score: float


@dataclass
class WaitingApplication:
    id: UUID
    title: str
    company: str
    open_questions: int


@dataclass
class FollowUp:
    title: str
    company: str
    due: date


@dataclass
class Digest:
    name: str
    email: str
    new_match_count: int = 0
    top_matches: list[DigestJob] = field(default_factory=list)
    needs_you: list[WaitingApplication] = field(default_factory=list)
    tailored_ready: int = 0
    follow_ups: list[FollowUp] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.new_match_count or self.needs_you or self.tailored_ready or self.follow_ups)


def unsubscribe_token(user_id: UUID) -> str:
    key = (get_settings().supabase_jwt_secret or "").encode()
    return hmac.new(key, f"digest-unsubscribe:{user_id}".encode(), hashlib.sha256).hexdigest()[:40]


def valid_unsubscribe_token(user_id: UUID, token: str) -> bool:
    return bool(get_settings().supabase_jwt_secret) and hmac.compare_digest(unsubscribe_token(user_id), token or "")


def unsubscribe_url(user_id: UUID) -> str | None:
    base = api_public_url()
    return f"{base}/api/v1/notifications/unsubscribe?u={user_id}&t={unsubscribe_token(user_id)}" if base else None


async def build_digest(db, user: User, *, since: datetime) -> Digest:
    user_id = user.id
    first_name = (user.name or "").strip().split(" ")[0]
    digest = Digest(name=first_name, email=user.email)

    applied = exists().where(
        ApplicationTracking.job_id == Job.id,
        ApplicationTracking.user_id == user_id,
        ApplicationTracking.status.in_(APPLIED_TRACKING_STATUSES),
    )
    query = (
        select(Job.id, Job.title_en, Job.title, Job.company, Job.location, JobScore.overall_fit, *job_group_key(Job))
        .join(JobScore, and_(JobScore.job_id == Job.id, JobScore.user_id == user_id))
        .outerjoin(JobSource, JobSource.id == Job.source_id)
        .outerjoin(JobEntity, JobEntity.job_id == Job.id)
        .outerjoin(UserJobState, and_(UserJobState.job_id == Job.id, UserJobState.user_id == user_id))
        .where(
            Job.status.notin_(["duplicate", "raw", "expired", "dismissed"]),
            or_(UserJobState.status.is_(None), UserJobState.status != "dismissed"),
            JobScore.overall_fit >= INBOX_MIN_SCORE,
            Job.discovered_at >= since,
            ~applied,
        )
        .order_by(JobScore.overall_fit.desc(), Job.discovered_at.desc())
    )
    query = apply_user_filters(query, **(await user_filter_kwargs(db, user_id)))
    seen: set[tuple] = set()
    for row in (await db.execute(query)).all():
        key = (row[6], row[7])
        if key in seen:
            continue
        seen.add(key)
        if len(digest.top_matches) < TOP_MATCHES:
            digest.top_matches.append(DigestJob(
                id=row.id, title=row.title_en or row.title, company=row.company, location=row.location,
                score=row.overall_fit,
            ))
    digest.new_match_count = len(seen)

    waiting = (await db.execute(
        select(AutoApplication, Job)
        .join(Job, Job.id == AutoApplication.job_id)
        .where(AutoApplication.user_id == user_id, AutoApplication.status == "needs_you")
        .order_by(AutoApplication.updated_at.desc())
    )).all()
    for application, job in waiting:
        answers = application.answers or {}
        open_questions = sum(1 for f in application.form or [] if rules.needs_attention(f, answers.get(f["key"])))
        digest.needs_you.append(WaitingApplication(
            id=application.id, title=job.title_en or job.title, company=job.company, open_questions=open_questions,
        ))

    digest.tailored_ready = (await db.execute(
        select(func.count(TailoredApplication.id)).where(
            TailoredApplication.user_id == user_id,
            TailoredApplication.approval_status == "ready",
            TailoredApplication.updated_at >= datetime.now(timezone.utc) - TAILORED_RECENT,
        )
    )).scalar() or 0

    for tracking, job in (await db.execute(
        select(ApplicationTracking, Job)
        .join(Job, Job.id == ApplicationTracking.job_id)
        .where(
            ApplicationTracking.user_id == user_id,
            ApplicationTracking.follow_up_date <= date.today(),
            ApplicationTracking.status.notin_(["rejected", "ghosted", "archived"]),
        )
        .order_by(ApplicationTracking.follow_up_date)
    )).all():
        digest.follow_ups.append(FollowUp(title=job.title_en or job.title, company=job.company, due=tracking.follow_up_date))
    return digest


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def digest_subject(digest: Digest) -> str:
    parts = []
    if digest.new_match_count:
        parts.append(_plural(digest.new_match_count, "new job match", "new job matches"))
    if digest.needs_you:
        parts.append(_plural(len(digest.needs_you), "application needs you", "applications need you"))
    if digest.follow_ups:
        parts.append(_plural(len(digest.follow_ups), "follow-up due", "follow-ups due"))
    if not parts and digest.tailored_ready:
        parts.append(_plural(digest.tailored_ready, "tailored application to review", "tailored applications to review"))
    return ", ".join(parts) if parts else "Nothing new today"


def render_digest(digest: Digest, *, unsubscribe: str | None) -> tuple[str, str, str]:
    """(subject, html, text)."""
    app = frontend_url()
    subject = digest_subject(digest)
    greeting = f"Good morning{', ' + digest.name if digest.name else ''}."

    html_parts: list[str] = []
    text_parts: list[str] = [greeting, ""]

    def section(title: str) -> None:
        html_parts.append(
            f'<h2 style="font-size:15px;margin:28px 0 10px;color:#111;">{escape(title)}</h2>'
        )
        text_parts.extend([title.upper(), ""])

    def button(label: str, href: str) -> str:
        return (
            f'<a href="{escape(href)}" style="display:inline-block;margin-top:12px;padding:9px 14px;border-radius:8px;'
            f'background:{ACCENT};color:#fff;text-decoration:none;font-size:14px;font-weight:600;">{escape(label)}</a>'
        )

    if digest.top_matches:
        more = digest.new_match_count - len(digest.top_matches)
        section(f"New matches ({digest.new_match_count})")
        rows = []
        for job in digest.top_matches:
            link = f"{app}/dashboard/jobs/{job.id}"
            meta = " · ".join(p for p in (job.company, job.location) if p)
            rows.append(
                '<tr><td style="padding:10px 0;border-top:1px solid #eee;vertical-align:top;width:44px;">'
                f'<span style="display:inline-block;min-width:32px;padding:3px 0;border-radius:6px;background:#e8f5f0;'
                f'color:{ACCENT};font:600 13px monospace;text-align:center;">{round(job.score)}</span></td>'
                '<td style="padding:10px 0;border-top:1px solid #eee;">'
                f'<a href="{escape(link)}" style="color:#111;font-size:15px;font-weight:600;text-decoration:none;">{escape(job.title)}</a>'
                f'<div style="color:#666;font-size:13px;margin-top:2px;">{escape(meta)}</div></td></tr>'
            )
            text_parts.append(f"{round(job.score)}  {job.title} — {meta}\n    {link}")
        html_parts.append('<table role="presentation" style="width:100%;border-collapse:collapse;">' + "".join(rows) + "</table>")
        html_parts.append(button("See all in your inbox" if more > 0 else "Open your inbox", f"{app}/dashboard/jobs"))
        text_parts.extend(["", f"Inbox: {app}/dashboard/jobs", ""])

    if digest.needs_you or digest.tailored_ready or digest.follow_ups:
        section("Waiting on you")
        items = []
        for application in digest.needs_you:
            link = f"{app}/dashboard/auto-apply/{application.id}"
            detail = (
                f"{_plural(application.open_questions, 'question', 'questions')} to answer"
                if application.open_questions else "ready to approve"
            )
            items.append(
                f'<li style="margin:6px 0;"><a href="{escape(link)}" style="color:{ACCENT};">'
                f'{escape(application.title)} at {escape(application.company)}</a>'
                f' <span style="color:#666;">— {escape(detail)}</span></li>'
            )
            text_parts.append(f"- Apply for me: {application.title} at {application.company} ({detail}) {link}")
        if digest.tailored_ready:
            link = f"{app}/dashboard/review"
            label = _plural(digest.tailored_ready, "tailored application", "tailored applications")
            items.append(f'<li style="margin:6px 0;"><a href="{escape(link)}" style="color:{ACCENT};">{escape(label)}</a> <span style="color:#666;">ready to review</span></li>')
            text_parts.append(f"- {label} ready to review: {link}")
        for follow_up in digest.follow_ups:
            link = f"{app}/dashboard/applications"
            items.append(
                f'<li style="margin:6px 0;">Follow up on <a href="{escape(link)}" style="color:{ACCENT};">{escape(follow_up.title)} at {escape(follow_up.company)}</a></li>'
            )
            text_parts.append(f"- Follow up: {follow_up.title} at {follow_up.company} {link}")
        html_parts.append('<ul style="padding-left:18px;margin:0;font-size:14px;color:#111;">' + "".join(items) + "</ul>")
        text_parts.append("")

    footer_links = [f'<a href="{escape(app)}/dashboard/profile" style="color:#666;">change email settings</a>']
    text_footer = f"Change email settings: {app}/dashboard/profile"
    if unsubscribe:
        footer_links.append(f'<a href="{escape(unsubscribe)}" style="color:#666;">stop these emails</a>')
        text_footer += f"\nStop these emails: {unsubscribe}"
    html = (
        '<div style="background:#f6f5f2;padding:24px 12px;font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;">'
        '<div style="max-width:560px;margin:0 auto;background:#fff;border-radius:12px;padding:28px 24px;">'
        f'<div style="font:700 13px monospace;letter-spacing:.06em;color:{ACCENT};">JOB HUNT</div>'
        f'<h1 style="font-size:22px;margin:10px 0 0;color:#111;">{escape(greeting)}</h1>'
        + "".join(html_parts)
        + '</div>'
        '<p style="max-width:560px;margin:14px auto 0;color:#888;font-size:12px;text-align:center;">'
        "You get this daily when there's something new. " + " · ".join(footer_links) + "</p></div>"
    )
    text = "\n".join(text_parts) + "\n" + text_footer + "\n"
    return subject, html, text


def digest_window_start(user: User, now: datetime) -> datetime:
    floor = now - MAX_LOOKBACK
    return max(user.last_digest_sent_at, floor) if user.last_digest_sent_at else now - timedelta(days=1)


async def send_due_digests(now: datetime | None = None) -> dict:
    """Send today's email to every user who wants it and hasn't had it,
    once the day's send hour has passed. Days with nothing new are marked
    done without an email."""
    from app.core.database import create_worker_session

    now = now or datetime.now(timezone.utc)
    outcome = {"sent": 0, "nothing_new": 0, "failed": 0, "errors": []}
    if not email_configured():
        outcome["status"] = "email not set up"
        return outcome
    today_send_time = now.replace(hour=get_settings().digest_hour_utc, minute=0, second=0, microsecond=0)
    if now < today_send_time:
        outcome["status"] = "not yet"
        return outcome

    async with create_worker_session()() as db:
        users = (await db.execute(
            select(User).where(
                User.email_digest.is_(True),
                or_(User.last_digest_sent_at.is_(None), User.last_digest_sent_at < today_send_time),
            )
        )).scalars().all()
        for user in users:
            try:
                digest = await build_digest(db, user, since=digest_window_start(user, now))
                if digest.is_empty:
                    outcome["nothing_new"] += 1
                else:
                    unsubscribe = unsubscribe_url(user.id)
                    subject, html, text = render_digest(digest, unsubscribe=unsubscribe)
                    await send_email(to=user.email, subject=subject, html=html, text=text, unsubscribe_url=unsubscribe)
                    outcome["sent"] += 1
                user.last_digest_sent_at = now
                await db.commit()
            except (EmailFailed, EmailNotConfigured) as e:
                await db.rollback()
                outcome["failed"] += 1
                outcome["errors"].append(f"{user.id}: {e}"[:300])
            except Exception as e:  # noqa: BLE001 — one user's problem mustn't stop the others
                logger.exception("Daily email failed for %s", user.id)
                await db.rollback()
                outcome["failed"] += 1
                outcome["errors"].append(f"{user.id}: {type(e).__name__}: {e}"[:300])
    outcome["status"] = "done"
    return outcome
