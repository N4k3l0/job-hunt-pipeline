import logging
import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.job import Job
from app.models.candidate import CandidateProfile, Resume, CandidateBullet, SampleApplication
from app.models.tailoring import TailoredApplication
from app.llm.client import llm_client
from app.llm.prompts.tailor_resume import (
    SYSTEM_PROMPT,
    TAILOR_RESUME_PROMPT,
    TAILOR_TOOL,
    COVER_LETTER_PROMPT,
    OUTREACH_PROMPT,
    ANSWER_PROMPT,
)

logger = logging.getLogger(__name__)


# Cap injected examples per kind. Past 3 the prompt gets long for marginal
# style improvement, and Claude starts pattern-matching too literally.
_MAX_SAMPLES_INJECTED = 3
_MAX_SAMPLE_CHARS_INJECTED = 4000


async def _load_samples_by_kind(db: AsyncSession, user_id: str) -> dict[str, list[str]]:
    """Pull the user's writing samples grouped by kind. Used to mimic
    voice when generating new drafts. Returns an empty mapping when the
    user has no samples — generation falls back to default behavior."""
    result = await db.execute(
        select(SampleApplication)
        .where(SampleApplication.user_id == user_id)
        .order_by(SampleApplication.created_at.desc())
    )
    by_kind: dict[str, list[str]] = {}
    for s in result.scalars().all():
        kind_list = by_kind.setdefault(s.kind, [])
        if len(kind_list) >= _MAX_SAMPLES_INJECTED:
            continue
        snippet = (s.content or "").strip()[:_MAX_SAMPLE_CHARS_INJECTED]
        if snippet:
            kind_list.append(snippet)
    return by_kind


_PREAMBLE_RE = re.compile(
    r"^\s*(?:"
    r"here(?:'s| is)?\s+(?:a\s+)?(?:draft|the\s+(?:draft|message|letter|outreach|cover))[^\n]*?[:\-]?\s*\n+"
    r"|"
    r"i(?:'ve|\s+have)?\s+(?:drafted|written|put\s+together)[^\n]*?[:\-]?\s*\n+"
    r"|"
    r"i'd\s+be\s+happy[^\n]*?[:\-]?\s*\n+"
    r"|"
    r"sure[,!]?\s+here(?:'s| is)?[^\n]*?[:\-]?\s*\n+"
    r"|"
    r"draft\s*\d*\s*[:\-]\s*\n+"
    r")",
    re.I,
)
_TRAILING_RE = re.compile(
    r"\n+\s*(?:"
    r"let\s+me\s+know\s+if[^$]*"
    r"|"
    r"happy\s+to\s+(?:adjust|tweak|iterate|revise)[^$]*"
    r"|"
    r"(?:character|word)\s+count[^$]*"
    r"|"
    r"\(?\s*\d+\s*(?:character|word|char)s?\b[^$]*"
    r"|"
    r"feel\s+free\s+to[^$]*"
    r"|"
    r"---+\s*\n+(?:notes?|alt(?:ernative)?s?|variants?)[^$]*"
    r")$",
    re.I,
)


def _strip_llm_fluff(text: str) -> str:
    """Defensive cleanup: strip common preambles and trailing commentary
    the model sometimes adds even when the prompt says 'only the message'.

    Conservative — only removes lines that match well-known LLM tells.
    Real opening sentences like 'Hi {recruiter},' or 'Dear hiring team,'
    don't match any of the patterns.
    """
    if not text:
        return text
    cleaned = _PREAMBLE_RE.sub("", text, count=1)
    cleaned = _TRAILING_RE.sub("", cleaned, count=1)
    # Strip stray opening / closing code fences just in case the model
    # wrapped the message in ``` for some reason.
    cleaned = re.sub(r"^```[a-z]*\n", "", cleaned)
    cleaned = re.sub(r"\n```\s*$", "", cleaned)
    return cleaned.strip()


def _style_examples_block(samples: list[str], artifact_label: str) -> str:
    """Render a <style_examples> block to prepend to the user prompt.
    Empty string when no samples — caller can string-concat unconditionally.

    Important: this teaches VOICE, not facts. The system prompt's hard
    rule against fabricating experience / metrics / employers still
    applies — Claude should mimic rhythm, tone, openers, closers, but
    NEVER lift specific claims from these examples into the new draft.
    """
    if not samples:
        return ""
    rendered = "\n\n".join(
        f"<example index=\"{i + 1}\">\n{s}\n</example>"
        for i, s in enumerate(samples)
    )
    return (
        f"<style_examples artifact=\"{artifact_label}\">\n"
        f"The candidate has written {artifact_label}s like the ones below. "
        f"Match their VOICE — sentence rhythm, tone, openers, common phrases, "
        f"how they frame achievements. Do NOT copy facts, employers, or "
        f"metrics from these examples; only the writing style.\n\n"
        f"{rendered}\n"
        f"</style_examples>\n\n"
    )


async def generate_tailored_application(
    db: AsyncSession,
    job_id: str,
    user_id: str,
    tailored_id: str | None = None,
    progress_callback=None,
) -> TailoredApplication:
    """Run the full tailoring pipeline for a job.

    If `tailored_id` is provided, updates that placeholder row in-place instead
    of inserting a new one. `progress_callback(step: str)` is awaited between
    major steps so the UI can show live progress.
    """
    async def _step(label: str):
        if progress_callback:
            await progress_callback(label)

    # Load job with entities
    job_result = await db.execute(
        select(Job).where(Job.id == job_id).options(selectinload(Job.entities))
    )
    job = job_result.scalar_one_or_none()
    if not job:
        raise ValueError(f"Job {job_id} not found")

    # Load profile with relations
    profile_result = await db.execute(
        select(CandidateProfile)
        .where(CandidateProfile.user_id == user_id)
        .options(
            selectinload(CandidateProfile.work_history),
            selectinload(CandidateProfile.skills),
            selectinload(CandidateProfile.bullets),
        )
    )
    profile = profile_result.scalar_one_or_none()
    if not profile:
        raise ValueError(f"No profile for user {user_id}")

    # Select best base resume
    resume_result = await db.execute(
        select(Resume).where(Resume.user_id == user_id).order_by(Resume.created_at.desc())
    )
    resumes = resume_result.scalars().all()
    base_resume = _select_best_resume(resumes, job) if resumes else None

    # Build context for prompts
    job_skills = job.entities.skills if job.entities else []
    job_requirements = job.entities.requirements if job.entities else []
    job_keywords = job.entities.keywords if job.entities else []
    job_questions = job.entities.application_questions if job.entities else []

    work_history_text = _format_work_history(profile.work_history)
    skills_text = ", ".join(s.skill_name for s in profile.skills)

    # Pull the user's writing samples once — Claude will read them as
    # style examples when drafting each artifact below.
    samples_by_kind = await _load_samples_by_kind(db, user_id)

    # ── Step 1: Tailor resume ─────────────────────────────────────────────
    logger.info("Tailoring resume for job %s", job_id)
    await _step("Tailoring resume")

    resume_prompt = (
        _style_examples_block(samples_by_kind.get("summary", []), "summary")
        + TAILOR_RESUME_PROMPT.format(
            job_title=job.title,
            job_company=job.company,
            job_requirements="; ".join(job_requirements[:15]),
            job_skills=", ".join(job_skills[:20]),
            job_keywords=", ".join(job_keywords[:20]),
            candidate_headline=profile.headline or "",
            candidate_summary=profile.master_summary or "",
            work_history_text=work_history_text,
            skills_text=skills_text,
        )
    )

    tailored_resume = await llm_client.generate_structured(
        task_type="tailoring",
        system_prompt=SYSTEM_PROMPT,
        user_prompt=resume_prompt,
        tools=[TAILOR_TOOL],
    )

    # ── Step 2: Generate cover letter ─────────────────────────────────────
    logger.info("Generating cover letter for job %s", job_id)
    await _step("Writing cover letter")

    top_exp = "\n".join(
        f"- {e.get('company')}: {'; '.join(e.get('bullets', [])[:2])}"
        for e in tailored_resume.get("selected_experience", [])[:3]
    )

    cover_letter_raw = await llm_client.generate(
        task_type="tailoring",
        system_prompt=SYSTEM_PROMPT,
        user_prompt=(
            _style_examples_block(samples_by_kind.get("cover_letter", []), "cover letter")
            + COVER_LETTER_PROMPT.format(
                job_title=job.title,
                job_company=job.company,
                job_requirements="; ".join(job_requirements[:10]),
                candidate_summary=tailored_resume.get("tailored_summary", ""),
                top_experience=top_exp,
            )
        ),
    )
    cover_letter = _strip_llm_fluff(cover_letter_raw)

    # ── Step 3: Generate recruiter outreach ───────────────────────────────
    logger.info("Generating outreach for job %s", job_id)
    await _step("Drafting outreach")

    # Load the user's display name for sign-off + outreach context.
    # Previously the outreach prompt only saw a list of pre-computed
    # "strongest matches" with no real employer / project / metric
    # context, so the model would refuse to draft and ask for more info.
    # Now we pass the same name + summary + top_experience the cover-
    # letter prompt gets so the model has real material to work from.
    from app.models.user import User
    user_row = (await db.execute(
        select(User.name).where(User.id == user_id)
    )).first()
    candidate_name = (user_row[0] if user_row else None) or "the candidate"

    outreach_raw = await llm_client.generate(
        task_type="tailoring",
        system_prompt=SYSTEM_PROMPT,
        user_prompt=(
            _style_examples_block(samples_by_kind.get("outreach", []), "outreach message")
            + OUTREACH_PROMPT.format(
                job_title=job.title,
                job_company=job.company,
                candidate_name=candidate_name,
                candidate_summary=(
                    tailored_resume.get("tailored_summary")
                    or profile.master_summary
                    or profile.headline
                    or ""
                ),
                top_experience=top_exp,
                strongest_matches="; ".join(tailored_resume.get("strongest_matches", [])),
            )
        ),
        max_tokens=500,
    )
    outreach = _strip_llm_fluff(outreach_raw)

    # ── Step 4: Generate screening answers (if applicable) ────────────────
    short_answers = {}
    if job_questions:
        logger.info("Generating %d screening answers for job %s", len(job_questions), job_id)
        await _step("Answering screening questions")
        relevant_exp = top_exp
        for q in job_questions[:5]:  # Limit to 5 questions
            answer = await llm_client.generate(
                task_type="tailoring",
                system_prompt=SYSTEM_PROMPT,
                user_prompt=ANSWER_PROMPT.format(
                    job_title=job.title,
                    job_company=job.company,
                    question=q,
                    candidate_summary=tailored_resume.get("tailored_summary", ""),
                    relevant_experience=relevant_exp,
                ),
                max_tokens=500,
            )
            short_answers[q] = answer

    # ── Store results ─────────────────────────────────────────────────────
    keyword_matches = {
        "matched": tailored_resume.get("matched_keywords", []),
        "unmatched": tailored_resume.get("unmatched_keywords", []),
    }
    validation_notes = {
        "strongest_matches": tailored_resume.get("strongest_matches", []),
        "gaps": tailored_resume.get("gaps", []),
    }

    if tailored_id:
        # Update placeholder row created by the API endpoint.
        existing = await db.execute(
            select(TailoredApplication).where(TailoredApplication.id == tailored_id)
        )
        application = existing.scalar_one_or_none()
        if not application:
            raise ValueError(f"Placeholder tailored application {tailored_id} not found")
        application.base_resume_id = base_resume.id if base_resume else None
        application.tailored_resume_json = tailored_resume
        application.tailored_summary = tailored_resume.get("tailored_summary")
        application.cover_letter = cover_letter
        application.recruiter_message = outreach
        application.short_answers = short_answers if short_answers else None
        application.keyword_matches = keyword_matches
        application.validation_notes = validation_notes
        application.approval_status = "ready"
        application.progress_step = None
    else:
        application = TailoredApplication(
            job_id=job_id,
            user_id=user_id,
            base_resume_id=base_resume.id if base_resume else None,
            tailored_resume_json=tailored_resume,
            tailored_summary=tailored_resume.get("tailored_summary"),
            cover_letter=cover_letter,
            recruiter_message=outreach,
            short_answers=short_answers if short_answers else None,
            keyword_matches=keyword_matches,
            validation_notes=validation_notes,
            approval_status="ready",
        )
        db.add(application)
    await db.flush()

    logger.info(
        "Tailored application created for job %s (id=%s): %d matched keywords, %d gaps",
        job_id,
        application.id,
        len(tailored_resume.get("matched_keywords", [])),
        len(tailored_resume.get("gaps", [])),
    )

    return application


def _select_best_resume(resumes: list[Resume], job: Job) -> Resume | None:
    """Select the best base resume for a job based on tags."""
    if not resumes:
        return None
    if len(resumes) == 1:
        return resumes[0]

    title_lower = job.title.lower()
    # Try to match by tags
    for resume in resumes:
        if not resume.tags:
            continue
        tags_lower = [t.lower() for t in resume.tags]
        if "ai" in title_lower or "automation" in title_lower:
            if any("ai" in t or "automation" in t for t in tags_lower):
                return resume
        if "product" in title_lower:
            if any("pm" in t or "product" in t for t in tags_lower):
                return resume

    # Default to most recent
    return resumes[0]


def _format_work_history(work_history) -> str:
    """Format work history entries for the prompt."""
    entries = []
    for w in sorted(work_history, key=lambda x: x.sort_order):
        dates = ""
        if w.start_date:
            dates = str(w.start_date)
            if w.end_date:
                dates += f" to {w.end_date}"
            else:
                dates += " to Present"

        bullets = "\n".join(f"  - {b}" for b in (w.bullets or []))
        skills = ", ".join(w.skills or [])

        entry = f"### {w.title} at {w.company}"
        if dates:
            entry += f" ({dates})"
        entry += f"\nSkills: {skills}\n{bullets}"
        entries.append(entry)

    return "\n\n".join(entries)
