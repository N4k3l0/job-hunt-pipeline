import logging

from app.services.scoring.pm_scorer import score_pm_path
from app.services.scoring.ai_automation_scorer import score_ai_automation_path
from app.services.scoring.geo_scorer import score_geography

logger = logging.getLogger(__name__)


def compute_job_score(
    job_data: dict,
    job_entities: dict,
    profile: dict,
) -> dict:
    """Compute overall fit score for a job against a candidate profile.

    Runs both PM and AI Automation scoring paths, uses the higher score.

    Args:
        job_data: Normalized job fields (title, company, location, country, remote_type, salary_*, seniority)
        job_entities: Parsed entities (skills, requirements, keywords, visa_notes, sponsorship_available)
        profile: Candidate profile (target_roles, preferred_countries, visa_statuses, remote_preference,
                 salary_min, salary_max, skills list, work_history)

    Returns:
        Dict with all score components, overall_fit, priority, role_path, reasoning
    """
    # Compute geo/visa/remote scores (shared between paths)
    geo = score_geography(
        job_country=job_data.get("country"),
        job_remote_type=job_data.get("remote_type"),
        job_sponsorship=job_entities.get("sponsorship_available"),
        job_visa_notes=job_entities.get("visa_notes"),
        preferred_countries=profile.get("preferred_countries", []),
        visa_statuses=profile.get("visa_statuses", {}),
        remote_preference=profile.get("remote_preference", "any"),
    )

    # Compute salary score (shared)
    salary_score = _score_salary(
        job_min=job_data.get("salary_min"),
        job_max=job_data.get("salary_max"),
        profile_min=profile.get("salary_min"),
        profile_max=profile.get("salary_max"),
    )

    # Run PM scoring path
    pm_scores = score_pm_path(
        title=job_data.get("title", ""),
        job_skills=job_entities.get("skills", []),
        job_requirements=job_entities.get("requirements", []),
        job_keywords=job_entities.get("keywords", []),
        job_seniority=job_data.get("seniority"),
        profile_skills=[s.get("skill_name", "") for s in profile.get("skills", [])],
        profile_work_history=profile.get("work_history", []),
    )

    # Run AI Automation scoring path. Pass the raw description so the
    # skill-overlap bucket can match user skills mentioned in the JD body
    # even when the source's tag list is sparse.
    ai_scores = score_ai_automation_path(
        title=job_data.get("title", ""),
        job_skills=job_entities.get("skills", []),
        job_requirements=job_entities.get("requirements", []),
        job_keywords=job_entities.get("keywords", []),
        job_seniority=job_data.get("seniority"),
        profile_skills=[s.get("skill_name", "") for s in profile.get("skills", [])],
        profile_work_history=profile.get("work_history", []),
        job_description=job_data.get("raw_description", "") or "",
    )

    # Compute totals for each path
    pm_total = (
        pm_scores["title_score"]
        + pm_scores["skill_score"]
        + pm_scores["seniority_score"]
        + pm_scores["industry_score"]
        + geo["geo_score"]
        + geo["remote_score"]
        + geo["visa_score"]
        + salary_score
    )

    ai_total = (
        ai_scores["title_score"]
        + ai_scores["skill_score"]
        + ai_scores["seniority_score"]
        + ai_scores["industry_score"]
        + geo["geo_score"]
        + geo["remote_score"]
        + geo["visa_score"]
        + salary_score
    )

    # Use the higher-scoring path
    if pm_total >= ai_total:
        role_path = "pm"
        path_scores = pm_scores
        overall_fit = pm_total
    else:
        role_path = "ai_automation"
        path_scores = ai_scores
        overall_fit = ai_total

    # Clamp to 0-100
    overall_fit = max(0.0, min(100.0, overall_fit))

    # Determine priority
    if overall_fit >= 80:
        priority = "high"
    elif overall_fit >= 60:
        priority = "medium"
    elif overall_fit >= 40:
        priority = "low"
    else:
        priority = "archive"

    return {
        "role_path": role_path,
        "title_score": path_scores["title_score"],
        "skill_score": path_scores["skill_score"],
        "seniority_score": path_scores["seniority_score"],
        "industry_score": path_scores["industry_score"],
        "geo_score": geo["geo_score"],
        "remote_score": geo["remote_score"],
        "visa_score": geo["visa_score"],
        "salary_score": salary_score,
        "overall_fit": round(overall_fit, 1),
        "priority": priority,
        "reasoning": {
            "path_used": role_path,
            "pm_total": round(pm_total, 1),
            "ai_total": round(ai_total, 1),
            **path_scores.get("reasoning", {}),
            **geo.get("reasoning", {}),
        },
    }


def _score_salary(
    job_min: int | None,
    job_max: int | None,
    profile_min: int | None,
    profile_max: int | None,
) -> float:
    """Score salary fit (0-10 points)."""
    if not job_min and not job_max:
        return 5.0  # Unknown salary, neutral score

    if not profile_min and not profile_max:
        return 5.0  # No preference set

    job_mid = ((job_min or 0) + (job_max or job_min or 0)) / 2
    profile_mid = ((profile_min or 0) + (profile_max or profile_min or 0)) / 2

    if profile_mid == 0:
        return 5.0

    ratio = job_mid / profile_mid

    if ratio >= 1.1:
        return 10.0  # Above expectations
    elif ratio >= 0.9:
        return 8.0  # Within range
    elif ratio >= 0.75:
        return 5.0  # Below but acceptable
    elif ratio >= 0.6:
        return 2.0  # Significantly below
    else:
        return 0.0  # Too far below
