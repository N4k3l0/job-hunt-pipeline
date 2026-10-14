"""The note a user sends a person after applying.

Once an application is sent (by the app, the extension, or "I applied" on
the job page), the app finds the person to write to (contact_finder.py:
the hiring manager for the role, then the department head, then a
recruiter; one lookup per job, shared by everyone) and writes a note short
enough for a LinkedIn connection request. The app never sends it: LinkedIn
doesn't allow that, and the user reads it first. They copy it, send it
from their own LinkedIn and press "I sent it", or "Skip".

One OutreachLog row per user and job, `status` drafted, sent or skipped.
The note gets the same writing check as application answers, and never
says an app wrote or sent anything: the user doesn't want employers to
know. A lookup is about 10 to 15 cents (Sonnet with up to 5 web searches),
so the site only starts one by itself for an application sent in the last
`AUTO_DAYS`; older ones wait for the user to ask.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.client import LLMCreditsExhausted
from app.llm.prompts.tailor_resume import OUTREACH_PROMPT, SYSTEM_PROMPT
from app.llm.style import plain_english, read_through, revise_plainly, without_dashes, writing_problems
from app.models.job import Job, JobContact
from app.models.tailoring import TailoredApplication
from app.models.tracking import ApplicationTracking, OutreachLog
from app.models.user import User

logger = logging.getLogger(__name__)

CHANNEL = "linkedin"
MAX_CHARS = 300  # LinkedIn's limit for a note on a connection request
STATUSES = ("drafted", "sent", "skipped")
# Still waiting to hear back: a note can still help.
WAITING = ("applied", "follow_up_due")
AUTO_DAYS = 7
FIX_ROUNDS = 3

NOTE_RULES = """

## When
The candidate has just applied for this role. Say so in a few words.

## Never
- Never say or hint that an app, a tool or AI wrote, filled in or sent the
  application or this note. Talking about software the candidate built is fine.
- At most 300 characters, counting spaces. Shorter is better."""


class NotSentYet(RuntimeError):
    """A note only makes sense once the application has gone."""


async def sent_application(db: AsyncSession, user_id: uuid.UUID, job_id: uuid.UUID) -> ApplicationTracking | None:
    """The user's tracking row for this job, if they're waiting to hear back."""
    return (await db.execute(
        select(ApplicationTracking).where(
            ApplicationTracking.user_id == user_id,
            ApplicationTracking.job_id == job_id,
            ApplicationTracking.status.in_(WAITING),
        ).order_by(ApplicationTracking.updated_at.desc()).limit(1)
    )).scalar_one_or_none()


async def note_for(db: AsyncSession, user_id: uuid.UUID, job_id: uuid.UUID) -> OutreachLog | None:
    return (await db.execute(
        select(OutreachLog).where(
            OutreachLog.user_id == user_id, OutreachLog.job_id == job_id, OutreachLog.channel == CHANNEL,
        ).order_by(OutreachLog.created_at.desc()).limit(1)
    )).scalar_one_or_none()


async def notes_for(db: AsyncSession, user_id: uuid.UUID, job_ids: list[uuid.UUID]) -> dict[uuid.UUID, OutreachLog]:
    """The user's notes for these jobs, by job."""
    if not job_ids:
        return {}
    rows = (await db.execute(
        select(OutreachLog).where(
            OutreachLog.user_id == user_id, OutreachLog.job_id.in_(job_ids), OutreachLog.channel == CHANNEL,
        ).order_by(OutreachLog.created_at)
    )).scalars().all()
    return {row.job_id: row for row in rows}


async def find_contact(db: AsyncSession, job: Job, *, force: bool = False) -> JobContact:
    """The person to write to about this job: looked up once, then kept on
    the job for everyone. `force` looks again. Raises if the lookup fails."""
    from app.services.outreach.contact_finder import find_contact_for_job

    contact = (await db.execute(select(JobContact).where(JobContact.job_id == job.id))).scalar_one_or_none()
    if contact is not None and not force:
        return contact
    result = await find_contact_for_job(company=job.company, role=job.title, location=job.location)
    if contact is None:
        contact = JobContact(job_id=job.id)
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
    return contact


def note_problems(text: str | None) -> list[str]:
    """What to change before sending, without asking the model."""
    problems = writing_problems(text)
    length = len(text or "")
    if length > MAX_CHARS:
        problems.append(
            f"It's {length} characters. LinkedIn only allows {MAX_CHARS} in a connection note, so make it shorter."
        )
    return problems


async def write_note(db: AsyncSession, user_id: uuid.UUID, job: Job, contact: JobContact | None, llm=None) -> str:
    """A short note from the user's real work, checked like an answer."""
    if llm is None:
        from app.llm.client import llm_client as llm
    from app.services.auto_apply.prepare import load_applicant

    user = await db.get(User, user_id)
    tailored = (await db.execute(
        select(TailoredApplication)
        .where(TailoredApplication.user_id == user_id, TailoredApplication.job_id == job.id)
        .order_by(TailoredApplication.created_at.desc()).limit(1)
    )).scalar_one_or_none()
    _facts, facts_text, _resume, _saved = await load_applicant(db, user_id)
    summary = (tailored.tailored_summary if tailored else None) or facts_text[:1500]
    role = job.title_en or job.title or ""
    prompt = OUTREACH_PROMPT.format(
        job_title=role,
        job_company=job.company or "",
        candidate_name=(user.name if user else "") or "",
        candidate_summary=summary,
        top_experience=facts_text[:2000],
        strongest_matches=", ".join((tailored.tailored_resume_json or {}).get("strongest_matches", []))
        if tailored and tailored.tailored_resume_json else "",
    ) + NOTE_RULES
    if contact is not None and contact.name:
        prompt += f"\n\n## Who it's going to\n{contact.name}"
        if contact.title:
            prompt += f", {contact.title}"
        prompt += "\nOpen with their first name."

    drafted = await llm.generate(task_type="tailoring", system_prompt=SYSTEM_PROMPT, user_prompt=prompt, max_tokens=500)
    text = (await without_dashes(drafted.strip(), llm)).strip()

    who = f"{contact.name}, {contact.title}" if contact is not None and contact.name else "someone at the company"
    what = f"a short LinkedIn note to {who}, sent after applying for {role} at {job.company}"
    for round_ in range(FIX_ROUNDS):
        try:
            found = await read_through(text, what=what)
        except LLMCreditsExhausted:
            raise
        except Exception:  # noqa: BLE001
            found = []
        problems = note_problems(text) + found
        if not problems or round_ == FIX_ROUNDS - 1:
            break
        revised = await revise_plainly([text], problems, what=what)
        if revised == [text]:
            break
        text = plain_english(revised[0]).strip()
    return text


async def prepare_note(
    db: AsyncSession, user_id: uuid.UUID, job_id: uuid.UUID, *, look_again: bool = False, llm=None,
) -> OutreachLog:
    """Find the person and write the note. A note already written is kept
    unless the user asks to look again, so opening the page twice costs
    nothing. If no one is found, the note is still written."""
    if await sent_application(db, user_id, job_id) is None:
        raise NotSentYet("Send the application first, then write to someone about it.")
    log = await note_for(db, user_id, job_id)
    if log is not None and log.message and not look_again:
        return log

    job = await db.get(Job, job_id)
    contact = None
    try:
        contact = await find_contact(db, job, force=look_again)
    except LLMCreditsExhausted:
        raise
    except Exception as e:  # noqa: BLE001
        logger.warning("Contact lookup failed for job %s: %s", job_id, e)
        await db.rollback()
        job = await db.get(Job, job_id, populate_existing=True)
        log = await note_for(db, user_id, job_id)
        contact = (await db.execute(select(JobContact).where(JobContact.job_id == job_id))).scalar_one_or_none()

    text = await write_note(db, user_id, job, contact, llm=llm)
    if log is None:
        log = OutreachLog(user_id=user_id, job_id=job_id, channel=CHANNEL)
        db.add(log)
    log.recipient = (contact.linkedin_url or contact.name) if contact is not None else None
    log.message = text
    log.status = "drafted"
    log.sent_at = None
    await db.commit()
    await db.refresh(log)
    return log


async def update_note(
    db: AsyncSession, user_id: uuid.UUID, job_id: uuid.UUID, *, message: str | None = None, status: str | None = None,
) -> OutreachLog:
    """Save the user's edits, or mark the note sent, skipped, or back to
    drafted. Skipping works before anything was written, at no cost."""
    if status is not None and status not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}")
    if await sent_application(db, user_id, job_id) is None:
        raise NotSentYet("Send the application first, then write to someone about it.")
    log = await note_for(db, user_id, job_id)
    if log is None:
        log = OutreachLog(user_id=user_id, job_id=job_id, channel=CHANNEL, status="drafted")
        db.add(log)
    if message is not None:
        log.message = plain_english(message).strip()
    if status is not None:
        log.status = status
        log.sent_at = datetime.now(timezone.utc) if status == "sent" else None
    await db.commit()
    await db.refresh(log)
    return log


def _linkedin_job(job: Job) -> str | None:
    for url in (job.job_url, job.apply_url):
        host = (urlparse(url or "").hostname or "").lower()
        if host == "linkedin.com" or host.endswith(".linkedin.com"):
            return url
    return None


async def view(db: AsyncSession, user_id: uuid.UUID, job_id: uuid.UUID) -> dict:
    """Everything the message step shows for one job."""
    job = await db.get(Job, job_id)
    tracking = await sent_application(db, user_id, job_id)
    log = await note_for(db, user_id, job_id)
    contact = (await db.execute(select(JobContact).where(JobContact.job_id == job_id))).scalar_one_or_none()
    applied_at = tracking.applied_at if tracking is not None else None
    recent = applied_at is not None and applied_at >= datetime.now(timezone.utc) - timedelta(days=AUTO_DAYS)
    company = (job.company if job else "") or ""
    message = log.message if log is not None else None
    return {
        "job_id": str(job_id),
        "company": company,
        "can_message": tracking is not None,
        # Written by itself when the page opens, only for recent ones.
        "auto": tracking is not None and recent and (log is None or (not log.message and log.status == "drafted")),
        "status": log.status if log is not None else None,
        "message": message,
        "chars": len(message or ""),
        "max_chars": MAX_CHARS,
        "problems": note_problems(message) if message else [],
        "sent_at": log.sent_at.isoformat() if log is not None and log.sent_at else None,
        "contact": {
            "name": contact.name,
            "title": contact.title,
            "linkedin_url": contact.linkedin_url,
            "confidence": contact.confidence,
            "source_notes": contact.source_notes,
        } if contact is not None and (contact.name or contact.linkedin_url) else None,
        "people_search_url": f"https://www.linkedin.com/search/results/people/?keywords={quote(company)}",
        "linkedin_job_url": _linkedin_job(job) if job else None,
    }
