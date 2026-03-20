"""Product Management scoring path.

Scoring weights (total from this path: 70 points, geo/remote/visa/salary add 30):
- Title match: 0-20
- Skill overlap: 0-25
- Seniority match: 0-15
- Industry/domain: 0-10
"""

# PM-specific title keywords and their scores
PM_TITLE_SCORES = {
    "product manager": 20,
    "product lead": 18,
    "product owner": 16,
    "head of product": 20,
    "vp of product": 18,
    "director of product": 18,
    "group product manager": 20,
    "senior product manager": 20,
    "staff product manager": 20,
    "principal product manager": 20,
    "technical product manager": 18,
    "ai product manager": 20,
    "product strategist": 14,
    "product analyst": 10,
    "program manager": 8,
    "project manager": 6,
    "business analyst": 5,
    "product marketing": 5,
    "product designer": 4,
}

# PM-relevant skills
PM_SKILLS = {
    # Core PM (high weight)
    "product strategy", "roadmap", "product roadmap", "product management",
    "product development", "product lifecycle", "product vision",
    "user research", "customer discovery", "market research",
    "a/b testing", "experimentation", "data-driven", "metrics",
    "stakeholder management", "cross-functional", "leadership",
    "agile", "scrum", "kanban", "sprint planning",
    "prioritization", "backlog management", "user stories",
    "go-to-market", "gtm", "product launch",
    # Technical PM
    "api", "technical specification", "system design",
    "sql", "data analysis", "analytics",
    "python", "machine learning", "ai",
    # Domain
    "saas", "b2b", "b2c", "marketplace", "platform",
    "fintech", "healthtech", "edtech",
    "mobile", "web", "cloud",
    "growth", "retention", "engagement",
}

# AI/tech industry keywords that boost PM scores
AI_INDUSTRY_KEYWORDS = {
    "ai", "artificial intelligence", "machine learning", "ml",
    "llm", "generative ai", "deep learning", "nlp",
    "automation", "data science", "neural network",
}


def score_pm_path(
    title: str,
    job_skills: list[str],
    job_requirements: list[str],
    job_keywords: list[str],
    job_seniority: str | None,
    profile_skills: list[str],
    profile_work_history: list[dict],
) -> dict:
    """Score a job on the PM path.

    Returns dict with title_score, skill_score, seniority_score, industry_score, reasoning.
    """
    title_lower = title.lower()
    reasoning = {}

    # ── Title Match (0-20) ────────────────────────────────────────────────
    title_score = 0.0
    matched_title = None
    for keyword, score in PM_TITLE_SCORES.items():
        if keyword in title_lower:
            if score > title_score:
                title_score = score
                matched_title = keyword

    reasoning["title_match"] = matched_title or "no PM title match"

    # ── Skill Overlap (0-25) ──────────────────────────────────────────────
    all_job_skills = set()
    for s in job_skills + job_requirements + job_keywords:
        all_job_skills.add(s.lower().strip())

    profile_skills_lower = {s.lower().strip() for s in profile_skills}

    # Also extract skills from work history
    for entry in profile_work_history:
        for s in entry.get("skills", []):
            profile_skills_lower.add(s.lower().strip())

    pm_relevant = all_job_skills & PM_SKILLS
    matched_skills = pm_relevant & profile_skills_lower

    if pm_relevant:
        skill_ratio = len(matched_skills) / len(pm_relevant)
    else:
        # No specific PM skills listed, check general overlap
        general_overlap = all_job_skills & profile_skills_lower
        skill_ratio = min(len(general_overlap) / max(len(all_job_skills), 1), 1.0) if all_job_skills else 0.3

    skill_score = round(skill_ratio * 25, 1)
    reasoning["pm_skills_matched"] = list(matched_skills)[:10]
    reasoning["pm_skills_missing"] = list(pm_relevant - matched_skills)[:10]

    # ── Seniority Match (0-15) ────────────────────────────────────────────
    seniority_score = _score_seniority(job_seniority, title_lower, profile_work_history)

    # ── Industry/Domain (0-10) ────────────────────────────────────────────
    industry_score = 0.0
    searchable = " ".join(all_job_skills).lower() + " " + title_lower
    ai_matches = sum(1 for kw in AI_INDUSTRY_KEYWORDS if kw in searchable)
    if ai_matches >= 3:
        industry_score = 10.0
    elif ai_matches >= 2:
        industry_score = 7.0
    elif ai_matches >= 1:
        industry_score = 4.0
    else:
        # Check for general tech/SaaS
        tech_keywords = {"saas", "platform", "cloud", "api", "software", "tech"}
        tech_matches = sum(1 for kw in tech_keywords if kw in searchable)
        industry_score = min(tech_matches * 2.0, 6.0)

    return {
        "title_score": title_score,
        "skill_score": skill_score,
        "seniority_score": seniority_score,
        "industry_score": industry_score,
        "reasoning": reasoning,
    }


def _score_seniority(
    job_seniority: str | None,
    title: str,
    work_history: list[dict],
) -> float:
    """Score seniority match (0-15 points)."""
    if not job_seniority:
        # Try to infer from title
        if any(kw in title for kw in ["senior", "staff", "principal", "lead"]):
            job_seniority = "senior"
        elif any(kw in title for kw in ["director", "head of", "vp"]):
            job_seniority = "director"
        elif "junior" in title or "associate" in title:
            job_seniority = "entry"
        else:
            job_seniority = "mid"

    # Estimate candidate seniority from work history
    total_years = 0
    for entry in work_history:
        start = entry.get("start_date")
        end = entry.get("end_date")
        if start:
            from datetime import date
            try:
                if isinstance(start, str):
                    start = date.fromisoformat(start)
                if end and isinstance(end, str):
                    end = date.fromisoformat(end)
                end = end or date.today()
                years = (end - start).days / 365.25
                total_years += max(0, years)
            except (ValueError, TypeError):
                pass

    # Map years to seniority level
    if total_years >= 10:
        candidate_level = "director"
    elif total_years >= 6:
        candidate_level = "senior"
    elif total_years >= 3:
        candidate_level = "mid"
    else:
        candidate_level = "entry"

    # Score based on match
    levels = ["entry", "mid", "senior", "lead", "director", "vp", "c_level"]
    try:
        job_idx = levels.index(job_seniority)
        cand_idx = levels.index(candidate_level)
    except ValueError:
        return 8.0  # Unknown, give neutral

    diff = abs(job_idx - cand_idx)
    if diff == 0:
        return 15.0
    elif diff == 1:
        return 10.0
    elif diff == 2:
        return 5.0
    else:
        return 2.0
