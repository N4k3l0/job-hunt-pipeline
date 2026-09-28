"""Prepare a user's application for a job, and apply the user's answers."""

from __future__ import annotations

import asyncio
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
from app.services.auto_apply.apply_links import find_apply_url, has_apply_redirect
from app.services.auto_apply.ats import detect_ats, hiring_system_name, resolve_greenhouse_board
from app.services.auto_apply.drafting import draft_answers
from app.services.auto_apply.forms import FormUnavailable, fetch_form, http_client
from app.llm.style import NOT_READ_YET, read_is_current, read_through, revise_plainly
from app.services.auto_apply.writing import application_document_problems, first_document_problem
from app.services.scoring.matching import candidate_years

logger = logging.getLogger(__name__)

LOCKED_STATUSES = ("submitting", "submitted")
# Not "previous_company_contact": whether someone interviewed or applied
# somewhere before is never in their profile, so a draft could only guess.
DRAFTABLE_KINDS = {"question", "years_experience", "salary"}
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
        earliest_start=profile.earliest_start if profile else None,
        open_to_relocation=profile.open_to_relocation if profile else None,
        languages=(profile.languages if profile else None) or [],
        university=next((e.institution for e in (profile.education if profile else []) if e.institution), None),
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


async def read_answers_through(application: AutoApplication, reader=None, reviser=None, revise: bool = True) -> int:
    """Have the model read every written answer it hasn't read in its
    current words, and keep what it found on the answer. Answers the app
    drafted are then fixed and read again; the user's own words are only
    ever changed by them. Returns how many couldn't be read (AI paused,
    say); those stay "not read yet"."""
    reader = reader or read_through
    form = application.form or []
    answers = dict(application.answers or {})
    todo = [f for f in form if rules.needs_read_through(f, answers.get(f["key"]))]
    if not todo:
        return 0
    results = await asyncio.gather(
        *(reader(answers[f["key"]]["value"], what=f"an answer to the question \"{f['label']}\"") for f in todo),
        return_exceptions=True,
    )
    failed = 0
    for item, found in zip(todo, results):
        if isinstance(found, Exception):
            failed += 1
            logger.warning("Couldn't read the answer to %r through: %s", item["label"], found)
            continue
        answers[item["key"]] = rules.with_read_through(answers[item["key"]], found)
    application.answers = answers
    if not revise:
        return failed

    reviser = reviser or revise_plainly
    drafts = []
    for item in form:
        entry = answers.get(item["key"])
        if (entry or {}).get("source") == "drafted":
            problems = [p for p in rules.answer_writing_problems(item, entry) if p != NOT_READ_YET]
            if problems:
                drafts.append((item, entry, problems))
    if not drafts:
        return failed
    revised = await asyncio.gather(
        *(reviser([entry["value"]], problems, what=f"an answer to the question \"{item['label']}\"")
          for item, entry, problems in drafts),
        return_exceptions=True,
    )
    for (item, entry, _), new in zip(drafts, revised):
        if isinstance(new, Exception) or new == [entry["value"]]:
            continue
        answers[item["key"]] = {k: v for k, v in {**entry, "value": new[0]}.items() if k != "read_through"}
    application.answers = answers
    return await read_answers_through(application, reader=reader, revise=False)


def _status_for(form: list[dict], answers: dict) -> str:
    return "needs_you" if any(rules.needs_attention(f, answers.get(f["key"])) for f in form) else "queued"


def _take_up_posting(job: Job, posting: dict) -> bool:
    """Bring the job's title and description in line with the live posting.
    True when either changed. The description is stored the way the
    company-board source stores it, so an unchanged posting compares equal."""
    from app.services.discovery.curated_service import _strip_html

    changed = False
    title = " ".join((posting.get("title") or "").split())
    if title and title != " ".join((job.title or "").split()):
        job.title, job.title_en = title, None
        changed = True
    description = _strip_html(posting.get("content") or "")
    if len(description) >= 200 and description != (job.raw_description or ""):
        job.raw_description, job.raw_description_en = description, None
        if job.entities is not None:
            job.entities.enriched_at = None  # the job reader reads it again
        changed = True
    return changed


async def _tailor_for(db: AsyncSession, user_id: uuid.UUID, job_id: uuid.UUID, *, force: bool = False) -> None:
    """Write a resume for this job (and a cover letter) unless one is
    already waiting. Never blocks the application: if it fails, the
    profile's own resume is attached instead."""
    from app.core.config import get_settings
    from app.services.auto_apply.resume_pdf import tailored_for_job
    from app.services.tailoring.tailor_service import generate_tailored_application

    if not get_settings().anthropic_api_key:
        return
    if not force and await tailored_for_job(db, user_id, job_id) is not None:
        return
    try:
        await generate_tailored_application(db, str(job_id), str(user_id), with_outreach=False)
        # It only flushes, and the request's session closes without
        # committing: without this the tailored resume was thrown away.
        await db.commit()
    except Exception as e:  # noqa: BLE001 — an application without a tailored resume still works
        await db.rollback()
        logger.warning("Couldn't tailor the resume for job %s: %s", job_id, e)


async def prepare_application(
    db: AsyncSession,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    *,
    client: httpx.AsyncClient | None = None,
    drafter=None,
    tailor: bool = False,
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
        board_page = job.apply_url or job.job_url
        if target is None and has_apply_redirect(board_page):
            try:
                job.apply_url = await find_apply_url(board_page, client) or board_page
            except httpx.HTTPError as e:
                logger.warning("Couldn't follow the apply link for job %s: %s", job.id, e)
            target = detect_ats(job.apply_url)
        if target is not None and target.board is None:
            board = await resolve_greenhouse_board(client, job.company, target.job_id)
            target = type(target)(target.ats, board, target.job_id, target.eu) if board else None
        if target is None:
            application.status = "unsupported"
            system = hiring_system_name(job.apply_url) or hiring_system_name(job.job_url)
            application.error = (
                f"This job's application form is on {system}, which the app can't fill in yet."
                if system else
                "This job's application form isn't on Greenhouse, Lever or Ashby, so it can't be filled in automatically yet."
            )
            await db.commit()
            return application

        application.ats = target.ats
        application.form_url = target.form_url
        posting: dict = {}
        try:
            form = await fetch_form(client, target, posting)
        except FormUnavailable as e:
            application.status = "failed"
            application.error = "This posting has closed." if e.closed else f"Couldn't read the application form: {e}"
            await db.commit()
            return application
    finally:
        if owns_client:
            await client.aclose()

    # Companies rename and rewrite postings. Applying goes by the one that's
    # live now, and a resume written for an older version is written again.
    posting_changed = _take_up_posting(job, posting)

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
    await read_answers_through(application)
    answers = application.answers
    application.resume_id = resume.id if resume else None
    application.error = None
    application.status = _status_for(form, answers)
    await db.commit()

    if posting_changed:
        from app.workers.scoring_tasks import rescore_jobs_for_all_users
        await rescore_jobs_for_all_users([job_id])
    if tailor:
        await _tailor_for(db, user_id, job_id, force=posting_changed)
        await db.refresh(application)  # a failed tailoring rolls back, which expires it
    # Ready to send only when the documents read plainly too.
    if application.status == "queued" and await application_document_problems(db, application):
        application.status = "needs_you"
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
            continue
        previous = answers.get(key) or {}
        answers[key] = rules.answer(value, "user")
        # Sending back an answer unchanged keeps "fine as it is" and what
        # the read-through found. Using the plainer version the app
        # suggested keeps what it found when it read the suggestion.
        if previous.get("value") == value:
            for kept in ("wording_ok", "read_through"):
                if kept in previous:
                    answers[key][kept] = previous[kept]
        elif isinstance(value, str) and read_is_current(previous.get("suggested_read"), value):
            answers[key]["read_through"] = previous["suggested_read"]
    application.answers = answers
    unread = await read_answers_through(application)
    answers = application.answers

    open_fields = [f for f in application.form if rules.needs_attention(f, answers.get(f["key"]))]
    if approve:
        if unread:
            raise AnswerError(
                "The app couldn't read your answers through just now, so it can't check they read plainly. "
                "Try again in a minute."
            )
        wording = [f for f in open_fields if rules.writing_blocks(f, answers.get(f["key"]))]
        if wording:
            first = wording[0]
            problem = rules.answer_writing_problems(first, answers.get(first["key"]))[0]
            raise AnswerError(
                f"“{first['label']}” needs plainer wording before it can be sent. {problem}",
                [f["key"] for f in wording],
            )
        if open_fields:
            raise AnswerError("Answer or confirm every question before sending.", [f["key"] for f in open_fields])
        document = first_document_problem(await application_document_problems(db, application))
        if document:
            raise AnswerError(f"{document} Change the wording on the Review page, then approve again.")
        application.status = "queued"
        await _remember_answers(db, application)
    elif open_fields:
        application.status = "needs_you"
    elif application.status not in ("queued",):
        application.status = "needs_you"
    await db.commit()
    return application


async def _remember_answers(db: AsyncSession, application: AutoApplication) -> None:
    # A select, not db.get: the job is usually loaded already (with the
    # application), and db.get then skips the options, so reading its details
    # below would load them outside async and crash the request. That broke
    # approving any job without a country, like "Remote-Friendly | Seattle".
    job = (await db.execute(
        select(Job).where(Job.id == application.job_id)
        .options(selectinload(Job.entities))
        .execution_options(populate_existing=True)
    )).scalar_one_or_none()
    # The country matters: "do you need sponsorship" has a different answer
    # per country, so the job's country is part of what gets remembered.
    job_facts = rules.JobFacts(company=(job.company if job else "") or "",
                               country=_job_country(job) if job else None)
    kinds = rules.kinds(application.form, job_facts)
    profile = (await db.execute(
        select(CandidateProfile).where(CandidateProfile.user_id == application.user_id)
    )).scalar_one_or_none()

    for item in application.form:
        entry = (application.answers or {}).get(item["key"])
        if not entry or entry.get("source") != "user":
            continue
        kind = kinds[item["key"]]
        if profile is not None:
            _remember_on_profile(profile, item, kind, entry["value"], job_facts)
        if kind not in rules.REUSABLE_KINDS:
            continue
        stored = rules.saved_answer_for(item, entry["value"])
        if stored is None:
            continue
        statement = insert(SavedAnswer).values(
            id=uuid.uuid4(), user_id=application.user_id, question_key=rules.question_key(item, kind),
            label=item["label"], answer=stored,
        )
        await db.execute(statement.on_conflict_do_update(
            constraint="uq_saved_answers_user_question",
            set_={"answer": stored, "label": item["label"], "updated_at": datetime.now(timezone.utc)},
        ))


def _remember_on_profile(profile: CandidateProfile, item: dict, kind: str, value, job: rules.JobFacts) -> None:
    """Keep the answers that are facts about the person, not about the job.
    Work rights are kept per country: the answer for the UK says nothing
    about the US."""
    text = str(value)
    if kind == "phone" and not profile.phone:
        profile.phone = text[:40]
    elif kind == "location" and not profile.current_location:
        profile.current_location = text[:255]
    elif kind == "start_date" and not profile.earliest_start:
        profile.earliest_start = _option_label(item, value)[:120]
    elif kind == "relocation" and profile.open_to_relocation is None:
        said_yes = rules.normalize_label(_option_label(item, value)) in ("yes", "true")
        profile.open_to_relocation = value is True or said_yes
    elif kind == "languages" and not profile.languages:
        labels = [_option_label(item, v) for v in (value if isinstance(value, list) else [value])]
        profile.languages = [label for label in labels if label]
    elif kind in ("work_authorization", "sponsorship"):
        country = rules.question_country(item, job)
        statuses = dict(profile.visa_statuses or {})
        if country and country not in statuses:
            said_yes = value is True or rules.normalize_label(_option_label(item, value)) in ("yes", "true")
            needs_sponsorship = said_yes if kind == "sponsorship" else not said_yes
            statuses[country] = "need_sponsorship" if needs_sponsorship else "work_visa"
            profile.visa_statuses = statuses


def _option_label(item: dict, value) -> str:
    """What the user picked, as the words on the form."""
    for option in item.get("options") or []:
        if option["value"] == value:
            return option["label"]
    return str(value)


async def cancel_application(db: AsyncSession, application: AutoApplication) -> AutoApplication:
    if application.status in LOCKED_STATUSES:
        raise AnswerError("This application has already been sent.")
    application.status = "cancelled"
    await db.commit()
    return application
