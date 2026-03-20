import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.job import Job
from app.models.candidate import CandidateProfile, Resume, CandidateBullet
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


async def generate_tailored_application(
    db: AsyncSession,
    job_id: str,
    user_id: str,
) -> TailoredApplication:
    """Run the full tailoring pipeline for a job.

    Steps:
    1. Load job + profile data
    2. Select best base resume
    3. Generate tailored resume content
    4. Generate cover letter
    5. Generate recruiter outreach
    6. Generate screening question answers (if applicable)
    7. Store all materials

    Returns the TailoredApplication record.
    """
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

    # ── Step 1: Tailor resume ─────────────────────────────────────────────
    logger.info("Tailoring resume for job %s", job_id)

    resume_prompt = TAILOR_RESUME_PROMPT.format(
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

    tailored_resume = await llm_client.generate_structured(
        task_type="tailoring",
        system_prompt=SYSTEM_PROMPT,
        user_prompt=resume_prompt,
        tools=[TAILOR_TOOL],
    )

    # ── Step 2: Generate cover letter ─────────────────────────────────────
    logger.info("Generating cover letter for job %s", job_id)

    top_exp = "\n".join(
        f"- {e.get('company')}: {'; '.join(e.get('bullets', [])[:2])}"
        for e in tailored_resume.get("selected_experience", [])[:3]
    )

    cover_letter = await llm_client.generate(
        task_type="tailoring",
        system_prompt=SYSTEM_PROMPT,
        user_prompt=COVER_LETTER_PROMPT.format(
            job_title=job.title,
            job_company=job.company,
            job_requirements="; ".join(job_requirements[:10]),
            candidate_summary=tailored_resume.get("tailored_summary", ""),
            top_experience=top_exp,
        ),
    )

    # ── Step 3: Generate recruiter outreach ───────────────────────────────
    logger.info("Generating outreach for job %s", job_id)

    outreach = await llm_client.generate(
        task_type="tailoring",
        system_prompt=SYSTEM_PROMPT,
        user_prompt=OUTREACH_PROMPT.format(
            job_title=job.title,
            job_company=job.company,
            strongest_matches="; ".join(tailored_resume.get("strongest_matches", [])),
        ),
        max_tokens=500,
    )

    # ── Step 4: Generate screening answers (if applicable) ────────────────
    short_answers = {}
    if job_questions:
        logger.info("Generating %d screening answers for job %s", len(job_questions), job_id)
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
    application = TailoredApplication(
        job_id=job_id,
        user_id=user_id,
        base_resume_id=base_resume.id if base_resume else None,
        tailored_resume_json=tailored_resume,
        tailored_summary=tailored_resume.get("tailored_summary"),
        cover_letter=cover_letter,
        recruiter_message=outreach,
        short_answers=short_answers if short_answers else None,
        keyword_matches={
            "matched": tailored_resume.get("matched_keywords", []),
            "unmatched": tailored_resume.get("unmatched_keywords", []),
        },
        validation_notes={
            "strongest_matches": tailored_resume.get("strongest_matches", []),
            "gaps": tailored_resume.get("gaps", []),
        },
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
