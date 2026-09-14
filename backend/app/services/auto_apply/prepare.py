"""Prepare a user's application for a job, and apply the user's answers."""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.auto_apply import AutoApplication, SavedAnswer
from app.models.candidate import CandidateProfile, Resume
from app.models.job import Job
from app.models.user import User
from app.services.auto_apply import answers as rules
from app.services.auto_apply.ats import detect_ats, resolve_greenhouse_board
from app.services.auto_apply.drafting import draft_answers
from app.services.auto_apply.forms import FormUnavailable, fetch_form, http_client
from app.services.scoring.matching import candidate_years

logger = logging.getLogger(__name__)

LOCKED_STATUSES = ("submitting", "submitted")
DRAFTABLE_KINDS = {"question", "previous_company_contact", "years_experience", "salary"}
MAX_TEXT_ANSWER = 10_000


class AnswerError(ValueError):
    """The user's answers can't be accepted; `fields` names the problems."""

    def __init__(self, message: str, fields: list[str] | None = None):
        super().__init__(message)
        self.fields = fields or []


def _sorted_history(profile: CandidateProfile | None):
    history = list(profile.work_history) if profile else []
    return sorted(history, key=lambda w: (w.end_date is not None, -(w.start_date or date.min).toordinal()))


async def load_applicant(db: AsyncSession, user_id: uuid.UUID) -> tuple[rules.ApplicantFacts, str, Resume | None, dict]:
    """The user's facts for the rules, the same facts as text for drafting,
    their latest resume, and their saved answers."""
    user = await db.get(User, user_id)
    profile = (await db.execute(
        select(CandidateProfile).where(CandidateProfile.user_id == user_id).options(
            selectinload(CandidateProfile.work_history),
            selectinload(CandidateProfile.skills),
            selectinload(CandidateProfile.education),
        )
    )).scalar_one_or_none()
    resume = (await db.execute(
        select(Resume).where(Resume.user_id == user_id)
        .order_by(Resume.parsed_at.is_(None), Resume.created_at.desc()).limit(1)
    )).scalar_one_or_none()

    history = _sorted_history(profile)
    current = history[0] if history else None
    years = candidate_years([
        {"start_date": w.start_date, "end_date": w.end_date} for w in history
    ]) if history else None
    facts = rules.ApplicantFacts(
        full_name=(user.name if user else "") or "",
        email=(user.email if user else "") or "",
        phone=profile.phone if profile else None,
        location=profile.current_location if profile else None,
        home_country=profile.home_country if profile else None,
        visa_statuses=(profile.visa_statuses if profile else None) or {},
        links=(profile.links if profile else None) or {},
        current_company=current.company if current else None,
        current_title=current.title if current else None,
        past_employers=[w.company for w in history],
        years_experience=years,
        salary_min=profile.salary_min if profile else None,
        salary_currency=profile.salary_currency if profile else None,
        has_resume=resume is not None,
    )

    cutoff = datetime.now(timezone.utc) - timedelta(days=rules.SAVED_ANSWER_FRESH_DAYS)
    saved = {
        s.question_key: {**(s.answer or {}), "fresh": s.updated_at is not None and s.updated_at >= cutoff}
        for s in (await db.execute(select(SavedAnswer).where(SavedAnswer.user_id == user_id))).scalars()
    }
    return facts, facts_text(facts, profile, history), resume, saved


def facts_text(facts: rules.ApplicantFacts, profile: CandidateProfile | None, history) -> str:
    lines = [f"Name: {facts.full_name}"]
    if facts.location:
        lines.append(f"Current location: {facts.location}")
    if facts.home_country:
        lines.append(f"Lives in: {rules.COUNTRY_NAMES.get(facts.home_country, facts.home_country)}")
    for code, status in (facts.visa_statuses or {}).items():
        lines.append(f"Work rights in {rules.COUNTRY_NAMES.get(code, code)}: {str(status).replace('_', ' ')}")
    if profile is not None:
        if profile.headline:
            lines.append(f"Headline: {profile.headline}")
        if profile.master_summary:
            lines.append(f"Summary: {profile.master_summary}")
        if profile.target_roles:
            lines.append(f"Looking for: {', '.join(profile.target_roles)}")
        if profile.remote_preference:
            lines.append(f"Work arrangement preference: {profile.remote_preference.replace('_', ' ')}")
    if facts.years_experience is not None:
        lines.append(f"Years of work experience (from resume dates): {facts.years_experience:.1f}")
    if history:
        lines.append("Work history:")
        for w in history[:8]:
            period = f"{w.start_date or '?'} to {w.end_date or 'present'}"
            lines.append(f"- {w.title} at {w.company} ({period})")
            for bullet in (w.bullets or [])[:5]:
                lines.append(f"  • {bullet}")
    if profile is not None and profile.skills:
        lines.append("Skills: " + ", ".join(s.skill_name for s in profile.skills[:60]))
    if profile is not None and profile.education:
        lines.append("Education:")
        for e in profile.education:
            parts = [p for p in (e.degree, e.field) if p]
            lines.append(f"- {' in '.join(parts) or 'Studied'} at {e.institution}" + (f" ({e.graduation_date})" if e.graduation_date else ""))
    return "\n".join(lines)


def _job_country(job: Job) -> str | None:
    if job.country and len(job.country) == 2:
        return job.country.upper()
    eligible = (job.entities.eligible_countries if job.entities else None) or []
    return eligible[0] if len(eligible) == 1 else None


def _status_for(form: list[dict], answers: dict) -> str:
    return "needs_you" if any(rules.needs_attention(f, answers.get(f["key"])) for f in form) else "queued"


async def prepare_application(
    db: AsyncSession,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    *,
    client: httpx.AsyncClient | None = None,
    drafter=None,
) -> AutoApplication:
    drafter = drafter or draft_answers
    job = (await db.execute(
        select(Job).where(Job.id == job_id).options(selectinload(Job.entities))
    )).scalar_one_or_none()
    if job is None:
        raise LookupError("Job not found")

    application = (await db.execute(
        select(AutoApplication).where(AutoApplication.user_id == user_id, AutoApplication.job_id == job_id)
    )).scalar_one_or_none()
    if application is None:
        application = AutoApplication(user_id=user_id, job_id=job_id, status="preparing", answers={})
        db.add(application)
    elif application.status in LOCKED_STATUSES:
        return application
    previous_answers = dict(application.answers or {})

    target = detect_ats(job.apply_url) or detect_ats(job.job_url)
    owns_client = client is None
    client = client or http_client()
    try:
        if target is not None and target.board is None:
            board = await resolve_greenhouse_board(client, job.company, target.job_id)
            target = type(target)(target.ats, board, target.job_id, target.eu) if board else None
        if target is None:
            application.status = "unsupported"
            application.error = "This job's application form isn't on Greenhouse, Lever or Ashby, so it can't be filled in automatically yet."
            await db.commit()
            return application

        application.ats = target.ats
        application.form_url = target.form_url
        try:
            form = await fetch_form(client, target)
        except FormUnavailable as e:
            application.status = "failed"
            application.error = "This posting has closed." if e.closed else f"Couldn't read the application form: {e}"
            await db.commit()
            return application
    finally:
        if owns_client:
            await client.aclose()

    facts, facts_for_drafting, resume, saved = await load_applicant(db, user_id)
    job_facts = rules.JobFacts(company=job.company or "", country=_job_country(job))
    answers = rules.fill_answers(form, facts, job_facts, saved)

    keys = {f["key"] for f in form}
    for key, entry in previous_answers.items():
        if key in keys and entry.get("source") == "user":
            answers[key] = entry

    kinds = rules.kinds(form, job_facts)
    to_draft = [
        f for f in form
        if f["required"] and kinds[f["key"]] in DRAFTABLE_KINDS
        and rules.is_empty((answers.get(f["key"]) or {}).get("value"))
    ]
    if to_draft:
        try:
            drafted = await drafter(to_draft, facts_for_drafting, {
                "title": job.title, "company": job.company, "location": job.location,
                "description": job.raw_description_en or job.raw_description,
            })
            answers.update(drafted)
        except Exception as e:  # noqa: BLE001 — drafting is a convenience; the user can answer themselves
            logger.warning("Drafting answers failed for application %s: %s", application.id, e)

    application.form = form
    application.answers = answers
    application.resume_id = resume.id if resume else None
    application.error = None
    application.status = _status_for(form, answers)
    await db.commit()
    return application


def _clean_value(item: dict, value):
    type_ = item["type"]
    if value is None or value == "" or value == []:
        return None
    if type_ == "file":
        raise AnswerError(f"“{item['label']}” is a file and is filled in from your resume.", [item["key"]])
    if type_ == "boolean":
        if not isinstance(value, bool):
            raise AnswerError(f"“{item['label']}” needs a yes or no answer.", [item["key"]])
        return value
    option_values = {o["value"] for o in item.get("options") or []}
    if type_ == "select":
        if value not in option_values:
            raise AnswerError(f"Choose one of the options for “{item['label']}”.", [item["key"]])
        return value
    if type_ == "multiselect":
        values = value if isinstance(value, list) else [value]
        if not values or any(v not in option_values for v in values):
            raise AnswerError(f"Choose from the options for “{item['label']}”.", [item["key"]])
        return values
    if type_ == "number":
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise AnswerError(f"“{item['label']}” needs a number.", [item["key"]]) from None
        return int(number) if number.is_integer() else number
    text = str(value).strip()
    if len(text) > MAX_TEXT_ANSWER:
        raise AnswerError(f"The answer to “{item['label']}” is too long.", [item["key"]])
    return text or None


async def update_answers(
    db: AsyncSession,
    application: AutoApplication,
    updates: dict,
    *,
    approve: bool,
) -> AutoApplication:
    """Record the user's answers. With `approve`, every question must be
    answered and confirmed, and the application is queued to send."""
    if application.status in LOCKED_STATUSES:
        raise AnswerError("This application has already been sent.")
    if not application.form:
        raise AnswerError("This application has no form to answer.")
    by_key = {f["key"]: f for f in application.form}
    unknown = [k for k in updates if k not in by_key]
    if unknown:
        raise AnswerError("Some answers are for questions that aren't on this form.", unknown)

    answers = dict(application.answers or {})
    for key, raw in updates.items():
        value = _clean_value(by_key[key], raw)
        if value is None:
            answers.pop(key, None)
        else:
            answers[key] = rules.answer(value, "user")
    application.answers = answers

    open_fields = [f for f in application.form if rules.needs_attention(f, answers.get(f["key"]))]
    if approve:
        if open_fields:
            raise AnswerError("Answer or confirm every question before sending.", [f["key"] for f in open_fields])
        application.status = "queued"
        await _remember_answers(db, application)
    elif open_fields:
        application.status = "needs_you"
    elif application.status not in ("queued",):
        application.status = "needs_you"
    await db.commit()
    return application


async def _remember_answers(db: AsyncSession, application: AutoApplication) -> None:
    job = await db.get(Job, application.job_id)
    job_facts = rules.JobFacts(company=(job.company if job else "") or "")
    kinds = rules.kinds(application.form, job_facts)
    profile = (await db.execute(
        select(CandidateProfile).where(CandidateProfile.user_id == application.user_id)
    )).scalar_one_or_none()

    for item in application.form:
        entry = (application.answers or {}).get(item["key"])
        if not entry or entry.get("source") != "user":
            continue
        kind = kinds[item["key"]]
        if profile is not None and kind == "phone" and not profile.phone:
            profile.phone = str(entry["value"])[:40]
        if profile is not None and kind == "location" and not profile.current_location:
            profile.current_location = str(entry["value"])[:255]
        if kind not in rules.REUSABLE_KINDS:
            continue
        stored = rules.saved_answer_for(item, entry["value"])
        if stored is None:
            continue
        statement = insert(SavedAnswer).values(
            id=uuid.uuid4(), user_id=application.user_id, question_key=rules.question_key(item),
            label=item["label"], answer=stored,
        )
        await db.execute(statement.on_conflict_do_update(
            constraint="uq_saved_answers_user_question",
            set_={"answer": stored, "label": item["label"], "updated_at": datetime.now(timezone.utc)},
        ))


async def cancel_application(db: AsyncSession, application: AutoApplication) -> AutoApplication:
    if application.status in LOCKED_STATUSES:
        raise AnswerError("This application has already been sent.")
    application.status = "cancelled"
    await db.commit()
    return application
