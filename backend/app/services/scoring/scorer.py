import logging
import re

from app.services.scoring.pm_scorer import score_pm_path
from app.services.scoring.ai_automation_scorer import score_ai_automation_path
from app.services.scoring.geo_scorer import score_geography
from app.services.jobs_filter import country_filter_codes

logger = logging.getLogger(__name__)


# Detect which scoring paths the user actually wants, based on their
# target_roles. Without this gate, a PM with Python/ML on her resume
# scores 90 on "AI Engineer" because the AI path sees the title at full
# weight and inflates skill overlap from her stack — even though she
# doesn't want engineering roles.
_PM_INTENT_RE = re.compile(
    r"\b("
    r"product\s+(manager|managers|management|owner|owners|lead|leader|leaders|director|strateg\w*|analyst|analytics)"
    r"|head\s+of\s+product"
    r"|(vp|vice\s+president|chief|svp|evp)\s+of\s+product"
    r"|chief\s+product\s+officer|cpo"
    r"|(senior|sr|principal|staff|lead|associate|junior|jr|group|head|technical|tpm)\s+pm"
    r"|\bpm\b"
    r")",
    re.I,
)

# Engineering/automation roles. Carefully scoped to "<thing> engineer"
# patterns so 'AI Product Manager' and 'Head of AI Product' don't match.
_AI_INTENT_RE = re.compile(
    r"\b("
    r"(ai|ml|data|llm|nlp|machine\s+learning|computer\s+vision|automation|rpa)"
    r"\s+(engineer|developer|scientist|architect|specialist|ops)"
    r"|mlops|llmops|aiops"
    r"|prompt\s+engineer"
    r"|(automation|ai|workflow)\s+(lead|architect)"
    r"|software\s+engineer|backend\s+engineer|full[\s-]?stack\s+engineer"
    r")",
    re.I,
)


def _user_role_intents(target_roles: list[str] | None) -> set[str]:
    """Return the set of scoring paths the user wants — {'pm', 'ai'} or
    a subset. Empty target_roles falls back to {'pm', 'ai'} so existing
    users without auto-suggested roles still get scored on both paths."""
    if not target_roles:
        return {"pm", "ai"}
    intents: set[str] = set()
    for r in target_roles:
        if not r:
            continue
        if _PM_INTENT_RE.search(r):
            intents.add("pm")
        if _AI_INTENT_RE.search(r):
            intents.add("ai")
    # If we couldn't classify any role, run both rather than score nothing.
    return intents or {"pm", "ai"}


def compute_job_score(
    job_data: dict,
    job_entities: dict,
    profile: dict,
) -> dict:
    """Compute overall fit score for a job against a candidate profile.

    Runs the scoring path(s) the user's target_roles imply (PM, AI, or
    both), picking the highest score across the active paths. A pure
    PM user no longer sees AI Engineer roles inflated to 90.

    Args:
        job_data: Normalized job fields (title, company, location, country, remote_type, salary_*, seniority)
        job_entities: Parsed entities (skills, requirements, keywords, visa_notes, sponsorship_available)
        profile: Candidate profile (target_roles, preferred_countries, visa_statuses, remote_preference,
                 salary_min, salary_max, skills list, work_history)

    Returns:
        Dict with all score components, overall_fit, priority, role_path, reasoning
    """
    intents = _user_role_intents(profile.get("target_roles"))
    # Compute geo/visa/remote scores (shared between paths)
    geo = score_geography(
        job_country=job_data.get("country"),
        job_remote_type=job_data.get("remote_type"),
        job_sponsorship=job_entities.get("sponsorship_available"),
        job_visa_notes=job_entities.get("visa_notes"),
        preferred_countries=country_filter_codes(profile.get("preferred_countries")) or [],
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

    pm_scores = None
    ai_scores = None
    pm_total = ai_total = -1.0  # sentinel: only paths actually run can win

    if "pm" in intents:
        pm_scores = score_pm_path(
            title=job_data.get("title", ""),
            job_skills=job_entities.get("skills", []),
            job_requirements=job_entities.get("requirements", []),
            job_keywords=job_entities.get("keywords", []),
            job_seniority=job_data.get("seniority"),
            profile_skills=[s.get("skill_name", "") for s in profile.get("skills", [])],
            profile_work_history=profile.get("work_history", []),
        )
        # geo_score is computed (and stored on the JobScore row for
        # reference) but EXCLUDED from overall_fit — country is now a
        # hard filter at query time (apply_user_filters), so every job
        # that gets here is already in a preferred country or remote.
        # Including geo in the score would just be a constant 12-15 pt
        # bump for every visible job, adding no ranking signal.
        # visa_score + salary_score are likewise computed-but-excluded.
        # Per-path max: title 20 + skill 25 + seniority 15 + industry 10
        # + remote 5 = 75. Semantic mode (below) reaches 100 via the
        # 80-pt cosine band, so a backfilled inbox naturally beats the
        # rule-based fallback.
        pm_total = (
            pm_scores["title_score"]
            + pm_scores["skill_score"]
            + pm_scores["seniority_score"]
            + pm_scores["industry_score"]
            + geo["remote_score"]
        )

    if "ai" in intents:
        # Pass the raw description so the skill-overlap bucket can match
        # user skills mentioned in the JD body even when the source's tag
        # list is sparse.
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
        # geo_score excluded — see pm path above.
        ai_total = (
            ai_scores["title_score"]
            + ai_scores["skill_score"]
            + ai_scores["seniority_score"]
            + ai_scores["industry_score"]
            + geo["remote_score"]
        )

    # Pick the higher-scoring path among those that actually ran.
    if pm_scores is not None and pm_total >= ai_total:
        role_path = "pm"
        path_scores = pm_scores
        rule_overall = pm_total
    else:
        role_path = "ai_automation"
        path_scores = ai_scores  # type: ignore[assignment]
        rule_overall = ai_total

    # Rule-based composition tops out at 75 (title 20 + skill 25 +
    # seniority 15 + industry 10 + remote 5). The semantic path tops at
    # 100. Scale rule-based up by 100/75 = 1.333 so the two modes
    # produce comparable scores — otherwise jobs that miss the semantic
    # path (no embedding yet) get an artificial 25-pt ceiling and look
    # worse than they are, hiding below the inbox min_score threshold.
    if rule_overall > 0:
        rule_overall = rule_overall * (100.0 / 75.0)

    # ── Semantic component ────────────────────────────────────────────
    # Cosine similarity between the profile embedding and the job
    # embedding, scaled to a 0-65 contribution. Falls back to the
    # rule-based path's score if either embedding is missing — keeps
    # the system working during backfill and if Voyage is unconfigured.
    from app.services.scoring.embedder import cosine_similarity
    profile_vec = profile.get("embedding")
    job_vec = job_entities.get("embedding")
    # pgvector returns numpy arrays, which raise on truthiness checks —
    # always compare against None.
    semantic_mode = profile_vec is not None and job_vec is not None
    if semantic_mode:
        cos = cosine_similarity(profile_vec, job_vec)
        # Voyage cosine ranges typically 0.4–0.85 for real pairs. Stretch
        # that into the 0-80 band so the spread between 'unrelated' and
        # 'strong match' translates to a meaningful score delta.
        # Linear remap: 0.30 → 0, 0.85 → 80.
        # (Was 0-65 when geo contributed 15; now that the country hard
        # filter handles geography, those 15 pts go to semantic instead
        # of being a constant 12-15 pt bump on every visible job.)
        stretched = max(0.0, min(1.0, (cos - 0.30) / 0.55))
        semantic_component = stretched * 80.0
        # Compose semantic (80) + remote (5) + seniority (15) = 100.
        seniority = path_scores["seniority_score"] if path_scores else 0.0
        overall_fit = (
            semantic_component
            + geo["remote_score"]
            + seniority
        )
        semantic_score = cos  # store the raw cosine on the row
    else:
        # No embedding yet — use the rule-based total as-is so the inbox
        # still surfaces SOMETHING while backfill runs.
        overall_fit = rule_overall
        semantic_score = 0.0

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
        "title_score": path_scores["title_score"] if path_scores else 0.0,
        "skill_score": path_scores["skill_score"] if path_scores else 0.0,
        "seniority_score": path_scores["seniority_score"] if path_scores else 0.0,
        "industry_score": path_scores["industry_score"] if path_scores else 0.0,
        "geo_score": geo["geo_score"],
        "remote_score": geo["remote_score"],
        "visa_score": geo["visa_score"],
        "salary_score": salary_score,
        "semantic_score": round(semantic_score, 4),
        "overall_fit": round(overall_fit, 1),
        "priority": priority,
        "reasoning": {
            "path_used": role_path,
            "intents": sorted(intents),
            "scoring_mode": "semantic" if semantic_mode else "rule-based",
            "semantic_cosine": round(semantic_score, 4) if semantic_score else None,
            "rule_overall": round(rule_overall, 1) if path_scores else None,
            **(path_scores.get("reasoning", {}) if path_scores else {}),
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
