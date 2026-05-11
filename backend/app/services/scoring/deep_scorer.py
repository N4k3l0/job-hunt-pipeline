import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.job import Job
from app.models.candidate import CandidateProfile, Resume
from app.models.scoring import JobScore
from app.llm.client import llm_client, MODELS
from app.llm.prompts.deep_score import (
    DEEP_SCORE_SYSTEM_PROMPT,
    DEEP_SCORE_USER_PROMPT,
    DEEP_SCORE_TOOL,
)

logger = logging.getLogger(__name__)


async def run_deep_score(
    db: AsyncSession,
    job_id: str,
    user_id: str,
    force: bool = False,
) -> dict:
    """Run LLM-based deep scoring for a job against a user's profile.

    Args:
        db: Database session
        job_id: The job to score against
        user_id: The user whose profile to use
        force: If True, re-run even if a cached deep score exists

    Returns:
        The deep score assessment dict
    """
    # Check for existing deep score (cached)
    score_result = await db.execute(
        select(JobScore).where(
            JobScore.job_id == job_id,
            JobScore.user_id == user_id,
        )
    )
    score_record = score_result.scalar_one_or_none()

    if score_record and score_record.deep_score_json and not force:
        logger.info("Returning cached deep score for job %s", job_id)
        return score_record.deep_score_json

    # Load job with entities
    job_result = await db.execute(
        select(Job)
        .where(Job.id == job_id)
        .options(selectinload(Job.entities))
    )
    job = job_result.scalar_one_or_none()
    if not job:
        raise ValueError(f"Job {job_id} not found")

    # Load candidate profile with relations
    profile_result = await db.execute(
        select(CandidateProfile)
        .where(CandidateProfile.user_id == user_id)
        .options(
            selectinload(CandidateProfile.work_history),
            selectinload(CandidateProfile.skills),
            selectinload(CandidateProfile.education),
        )
    )
    profile = profile_result.scalar_one_or_none()
    if not profile:
        raise ValueError(f"No profile found for user {user_id}")

    # Load most recent resume for additional context
    resume_result = await db.execute(
        select(Resume)
        .where(Resume.user_id == user_id)
        .order_by(Resume.created_at.desc())
        .limit(1)
    )
    resume = resume_result.scalar_one_or_none()

    # Build prompt context
    work_history_text = _format_work_history(profile.work_history)
    skills_text = _format_skills(profile.skills)
    education_text = _format_education(profile.education)

    job_skills = job.entities.skills if job.entities else []
    job_requirements = job.entities.requirements if job.entities else []
    job_nice_to_have = job.entities.nice_to_have if job.entities else []
    exp_min = job.entities.years_experience_min if job.entities else None
    exp_max = job.entities.years_experience_max if job.entities else None

    experience_range = "Not specified"
    if exp_min and exp_max:
        experience_range = f"{exp_min}-{exp_max} years"
    elif exp_min:
        experience_range = f"{exp_min}+ years"
    elif exp_max:
        experience_range = f"Up to {exp_max} years"

    user_prompt = DEEP_SCORE_USER_PROMPT.format(
        job_title=job.title,
        job_company=job.company,
        job_location=job.location or "Not specified",
        job_remote_type=job.remote_type or "Not specified",
        job_seniority=job.seniority or "Not specified",
        job_description=job.raw_description or "No description available",
        job_skills=", ".join(job_skills[:30]) if job_skills else "Not specified",
        job_requirements="; ".join(job_requirements[:20]) if job_requirements else "Not specified",
        job_nice_to_have="; ".join(job_nice_to_have[:15]) if job_nice_to_have else "Not specified",
        job_experience_range=experience_range,
        candidate_headline=profile.headline or "Not provided",
        candidate_summary=profile.master_summary or "Not provided",
        work_history_text=work_history_text or "No work history provided",
        skills_text=skills_text or "No skills listed",
        education_text=education_text or "No education listed",
    )

    # Call Claude via structured tool use
    logger.info("Running deep score for job %s (user %s)", job_id, user_id)

    deep_score = await llm_client.generate_structured(
        task_type="scoring",
        system_prompt=DEEP_SCORE_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        tools=[DEEP_SCORE_TOOL],
        max_tokens=4096,
    )

    # Validate we got a proper structured response (not a fallback text blob)
    if "text" in deep_score and "overall_fit_score" not in deep_score:
        logger.error("Deep score returned text instead of structured output: %s", deep_score["text"][:200])
        raise RuntimeError("LLM did not return structured deep score output")

    # Derive recommendation from overall_fit_score so the badge always
    # aligns with the number. Claude returns both fields but they drift —
    # users saw 75-scoring jobs labelled 'strong_apply' while 82-scoring
    # ones were just 'apply', which made the UI feel arbitrary. We trust
    # the score (numeric, comparable) over the verbal label (independent
    # LLM judgement).
    score = deep_score.get("overall_fit_score")
    if isinstance(score, (int, float)):
        if score >= 80:
            deep_score["recommendation"] = "strong_apply"
        elif score >= 65:
            deep_score["recommendation"] = "apply"
        elif score >= 45:
            deep_score["recommendation"] = "maybe"
        else:
            deep_score["recommendation"] = "skip"

    # Add metadata
    deep_score["scored_at"] = datetime.now(timezone.utc).isoformat()
    # Metadata only — actual model is selected by llm_client via MODELS map.
    # Kept for transparency in the cached deep_score_json blob.
    deep_score["model"] = MODELS.get("scoring", "claude-sonnet-4-6")

    # Cache the result on the JobScore record
    if score_record:
        score_record.deep_score_json = deep_score
        await db.flush()
        logger.info(
            "Deep score cached for job %s: overall_fit=%d, recommendation=%s",
            job_id,
            deep_score.get("overall_fit_score", -1),
            deep_score.get("recommendation", "unknown"),
        )
    else:
        # No JobScore record exists yet — create a minimal one to hold the deep score
        score_record = JobScore(
            job_id=job_id,
            user_id=user_id,
            role_path="unknown",
            deep_score_json=deep_score,
        )
        db.add(score_record)
        await db.flush()
        logger.info(
            "Created new JobScore with deep score for job %s: overall_fit=%d, recommendation=%s",
            job_id,
            deep_score.get("overall_fit_score", -1),
            deep_score.get("recommendation", "unknown"),
        )

    return deep_score


def _format_work_history(work_history) -> str:
    """Format work history entries for the deep scoring prompt."""
    if not work_history:
        return ""

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
        if w.description:
            entry += f"\n{w.description}"
        entry += f"\nSkills used: {skills}" if skills else ""
        if bullets:
            entry += f"\nKey achievements:\n{bullets}"
        entries.append(entry)

    return "\n\n".join(entries)


def _format_skills(skills) -> str:
    """Format candidate skills for the prompt, grouped by category."""
    if not skills:
        return ""

    # Group by category
    categories: dict[str, list[str]] = {}
    for s in skills:
        cat = s.category or "Other"
        label = s.skill_name
        if s.proficiency:
            label += f" ({s.proficiency})"
        if s.years_experience:
            label += f" [{s.years_experience}y]"
        categories.setdefault(cat, []).append(label)

    lines = []
    for cat, skill_list in sorted(categories.items()):
        lines.append(f"**{cat}:** {', '.join(skill_list)}")

    return "\n".join(lines)


def _format_education(education) -> str:
    """Format education entries for the prompt."""
    if not education:
        return ""

    entries = []
    for e in education:
        entry = ""
        if e.degree and e.field:
            entry = f"{e.degree} in {e.field}"
        elif e.degree:
            entry = e.degree
        elif e.field:
            entry = e.field

        entry += f" — {e.institution}"
        if e.graduation_date:
            entry += f" ({e.graduation_date})"
        entries.append(entry)

    return "\n".join(entries)
