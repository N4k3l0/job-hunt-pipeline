import logging

from app.services.jobs_filter import country_filter_codes
from app.services.scoring.embedder import cosine_similarity
from app.services.scoring.geo_scorer import score_geography
from app.services.scoring.matching import (
    LEVEL_GAP_SCORES,
    domain_match,
    expand_skills,
    seniority_match,
    skill_match,
    title_match,
)

logger = logging.getLogger(__name__)

# The version stored in job_scores. PROPOSED_SCORE_VERSION is scored live
# next to it on the Rate matches page (services/scoring/evaluation.py), so
# a change is measured against the user's own ratings before it replaces
# the stored scores.
SCORE_VERSION = 2
PROPOSED_SCORE_VERSION = 3

# Weights of the rule-based components; they sum to 1.
WEIGHTS = {"title": 0.30, "skills": 0.35, "seniority": 0.20, "domain": 0.05, "remote": 0.10}

# Version 3 gives no points for what isn't known. A component the job
# doesn't state (its level, its remote policy) counts as 0; a component the
# profile has nothing for (no skills, no remote preference, no industries)
# is left out and the other weights share its weight.
STRICT_LEVEL_GAP_SCORES = (1.0, 0.7, 0.2, 0.0)
# Version 3: a job needs a real title or skills match to reach the inbox
# (default minimum 50). Otherwise its score stops here.
RELEVANCE_MIN = 0.5
IRRELEVANT_MAX_SCORE = 45.0
# When both the job and the profile have embeddings, the overall score
# blends in resume-to-job similarity at this share.
SEMANTIC_SHARE = 0.4

# Axis maxima the dashboard displays each component against.
AXIS_MAX = {"title": 20, "skills": 25, "seniority": 15, "domain": 10}


def compute_job_score(
    job_data: dict,
    job_entities: dict,
    profile: dict,
    *,
    version: int = SCORE_VERSION,
) -> dict:
    """Score how well a job fits a candidate, for any profession.

    Args:
        job_data: title, company, country, remote_type, salary_*, seniority, raw_description
        job_entities: skills, nice_to_have, requirements, keywords, years_experience_min,
            visa_notes, sponsorship_available, embedding
        profile: target_roles, preferred_countries, visa_statuses, remote_preference,
            salary_min, salary_max, skills, work_history, embedding
        version: 2 gives unknown components a middle score; 3 gives them nothing.

    Returns:
        Dict with the JobScore columns: per-axis scores, overall_fit (0-100),
        priority, role_path and reasoning.
    """
    strict = version >= 3
    title = job_data.get("title") or ""
    description = job_data.get("raw_description") or ""
    work_history = profile.get("work_history") or []

    geo = score_geography(
        job_country=job_data.get("country"),
        job_remote_type=job_data.get("remote_type"),
        job_sponsorship=job_entities.get("sponsorship_available"),
        job_visa_notes=job_entities.get("visa_notes"),
        preferred_countries=country_filter_codes(profile.get("preferred_countries")) or [],
        visa_statuses=profile.get("visa_statuses") or {},
        remote_preference=profile.get("remote_preference") or "any",
    )
    salary_score = _score_salary(
        job_min=job_data.get("salary_min"),
        job_max=job_data.get("salary_max"),
        profile_min=profile.get("salary_min"),
        profile_max=profile.get("salary_max"),
    )

    title_value, matched_role = title_match(
        title,
        profile.get("target_roles"),
        [w.get("title") for w in work_history if w.get("title")],
        interests=profile.get("search_keywords"),
    )

    candidate_skills = [s.get("skill_name", "") for s in profile.get("skills") or []]
    for entry in work_history:
        candidate_skills.extend(entry.get("skills") or [])
    skills_value, skills_matched, skills_missing = skill_match(
        job_entities.get("skills"),
        description,
        candidate_skills,
        nice_to_have=job_entities.get("nice_to_have"),
    )

    seniority_value, seniority_detail = seniority_match(
        job_data.get("seniority"),
        title,
        job_entities.get("years_experience_min"),
        work_history,
        gap_scores=STRICT_LEVEL_GAP_SCORES if strict else LEVEL_GAP_SCORES,
    )

    domain_tags: list[str] = []
    for entry in work_history:
        domain_tags.extend(entry.get("domain_tags") or [])
    # Keywords before the description: only the start of the text is searched.
    job_text = " ".join([title, " ".join(job_entities.get("keywords") or []), description])
    domain_value, domain_hits = domain_match(job_text, domain_tags)

    remote_value = geo["remote_score"] / 5.0

    components = {
        "title": title_value,
        "skills": skills_value,
        "seniority": seniority_value,
        "domain": domain_value,
        "remote": remote_value,
    }
    relevant = True
    if strict:
        has_roles = bool(
            profile.get("target_roles") or profile.get("search_keywords")
            or any(w.get("title") for w in work_history)
        )
        has_skills = bool(expand_skills(candidate_skills))
        remote_preference = profile.get("remote_preference") or "any"
        components = {
            "title": title_value if has_roles else None,
            "skills": skills_value if has_skills else None,
            "seniority": (
                None if seniority_detail["candidate_level"] is None
                else 0.0 if seniority_detail["job_level"] is None
                else seniority_value
            ),
            "domain": domain_value if any(t and len(t.strip()) >= 3 for t in domain_tags) else None,
            "remote": (
                None if remote_preference == "any"
                else 0.0 if not job_data.get("remote_type")
                else remote_value
            ),
        }
        if has_roles or has_skills:
            relevant = (components["title"] or 0) >= RELEVANCE_MIN or (components["skills"] or 0) >= RELEVANCE_MIN

    counted = {name: value for name, value in components.items() if value is not None}
    counted_weight = sum(WEIGHTS[name] for name in counted)
    rule_overall = (
        100.0 * sum(WEIGHTS[name] * value for name, value in counted.items()) / counted_weight
        if counted_weight else 0.0
    )
    if not relevant:
        rule_overall = min(rule_overall, IRRELEVANT_MAX_SCORE)

    # pgvector < 0.5 returns numpy arrays, which raise on truthiness
    # checks — always compare against None.
    profile_vec = profile.get("embedding")
    job_vec = job_entities.get("embedding")
    semantic_mode = profile_vec is not None and job_vec is not None
    semantic_score = 0.0
    overall_fit = rule_overall
    if semantic_mode:
        semantic_score = cosine_similarity(profile_vec, job_vec)
        # Voyage cosines for real pairs sit around 0.30-0.85; stretch that
        # range to 0-1 so it separates weak from strong matches.
        stretched = max(0.0, min(1.0, (semantic_score - 0.30) / 0.55))
        overall_fit = (1 - SEMANTIC_SHARE) * rule_overall + SEMANTIC_SHARE * 100.0 * stretched

    overall_fit = max(0.0, min(100.0, overall_fit))

    if overall_fit >= 80:
        priority = "high"
    elif overall_fit >= 60:
        priority = "medium"
    elif overall_fit >= 40:
        priority = "low"
    else:
        priority = "archive"

    if components["seniority"] is not None:
        seniority_value = components["seniority"]
    return {
        "role_path": "general",
        "title_score": round(title_value * AXIS_MAX["title"], 1),
        "skill_score": round(skills_value * AXIS_MAX["skills"], 1),
        "seniority_score": round(seniority_value * AXIS_MAX["seniority"], 1),
        "industry_score": round(domain_value * AXIS_MAX["domain"], 1),
        "geo_score": geo["geo_score"],
        "remote_score": geo["remote_score"],
        "visa_score": geo["visa_score"],
        "salary_score": salary_score,
        "semantic_score": round(semantic_score, 4),
        "overall_fit": round(overall_fit, 1),
        "priority": priority,
        "score_version": version,
        "reasoning": {
            "scoring_mode": "semantic" if semantic_mode else "rule-based",
            "semantic_cosine": round(semantic_score, 4) if semantic_mode else None,
            "rule_overall": round(rule_overall, 1),
            # Version 3: the components the score is made of, and whether the
            # job matched the candidate's roles or skills.
            **({"counted": sorted(counted), "role_or_skill_match": relevant} if strict else {}),
            "matched_role": matched_role,
            "skills_matched": skills_matched,
            "skills_missing": skills_missing,
            "domain_matches": domain_hits,
            **seniority_detail,
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
