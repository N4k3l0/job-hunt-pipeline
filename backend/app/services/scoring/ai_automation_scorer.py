"""AI Automation scoring path.

Scoring weights (total from this path: 70 points, geo/remote/visa/salary add 30):
- Title match: 0-20
- Skill overlap: 0-25
- Seniority match: 0-15
- Industry/domain: 0-10
"""

AI_TITLE_SCORES = {
    "ai automation": 20,
    "ai engineer": 18,
    "automation engineer": 18,
    "ml engineer": 16,
    "machine learning engineer": 16,
    "ai product manager": 20,
    "ai platform": 18,
    "automation lead": 20,
    "automation architect": 20,
    "ai ops": 16,
    "mlops": 16,
    "ai developer": 16,
    "llm engineer": 18,
    "prompt engineer": 14,
    "ai solutions": 16,
    "workflow automation": 18,
    "process automation": 16,
    "rpa developer": 14,
    "integration engineer": 12,
    "data engineer": 10,
    "data scientist": 10,
    "backend engineer": 6,
    "software engineer": 5,
    "devops": 8,
}

AI_SKILLS = {
    # Core AI/ML
    "python", "machine learning", "deep learning", "nlp",
    "llm", "large language models", "gpt", "claude",
    "langchain", "llamaindex", "rag", "retrieval augmented generation",
    "prompt engineering", "fine-tuning", "embeddings",
    "tensorflow", "pytorch", "scikit-learn",
    "computer vision", "transformers", "neural networks",
    # Automation
    "workflow automation", "process automation", "rpa",
    "n8n", "make", "zapier", "power automate",
    "airflow", "prefect", "dagster", "temporal",
    "api integration", "webhooks", "etl",
    "selenium", "playwright", "puppeteer",
    # Infrastructure
    "docker", "kubernetes", "aws", "gcp", "azure",
    "ci/cd", "github actions", "terraform",
    "fastapi", "flask", "django",
    "postgresql", "redis", "mongodb",
    "vector database", "pinecone", "weaviate", "chromadb",
    # General
    "rest api", "graphql", "microservices",
    "sql", "nosql", "data pipelines",
    "git", "linux", "bash",
}

AI_INDUSTRY_KEYWORDS = {
    "ai", "artificial intelligence", "machine learning", "ml",
    "automation", "llm", "generative ai", "deep learning",
    "nlp", "computer vision", "data science",
    "agent", "agentic", "copilot",
}


import re as _re


def _expand_profile_skills(profile_skills: list[str]) -> set[str]:
    """Normalise a user's skill list for substring matching against job text.

    Splits parenthetical aliases ('Workflow Automation (n8n)' →
    {'workflow automation', 'n8n'}). Drops 1-2 char tokens and well-known
    false-friends ('go', 'r', 'c', 'ai', 'ml') that would match unrelated
    titles like 'Go-to-Market Manager'.
    """
    bad_short = {"c", "r", "go", "ai", "ml", "ui", "ux", "qa", "it"}
    out: set[str] = set()
    for raw in profile_skills or []:
        if not raw:
            continue
        s = raw.strip().lower()
        # Pull anything inside parens out as its own skill
        for alias in _re.findall(r"\(([^)]+)\)", s):
            alias = alias.strip().lower()
            if len(alias) >= 2 and alias not in bad_short:
                out.add(alias)
        s = _re.sub(r"\s*\(.*?\)\s*", "", s).strip()
        if len(s) >= 3 and s not in bad_short:
            out.add(s)
    return out


def score_ai_automation_path(
    title: str,
    job_skills: list[str],
    job_requirements: list[str],
    job_keywords: list[str],
    job_seniority: str | None,
    profile_skills: list[str],
    profile_work_history: list[dict],
    job_description: str = "",
) -> dict:
    """Score a job on the AI Automation path."""
    title_lower = title.lower()
    reasoning: dict = {}

    # ── Title Match (0-20) ────────────────────────────────────────────────
    title_score = 0.0
    matched_title = None
    for keyword, score in AI_TITLE_SCORES.items():
        if keyword in title_lower:
            if score > title_score:
                title_score = score
                matched_title = keyword

    reasoning["title_match"] = matched_title or "no AI title match"

    # ── Skill Overlap (0-25) ──────────────────────────────────────────────
    # Old logic gated on a hardcoded AI_SKILLS reference set, so user
    # skills that weren't in it (VAPI, Airtable, GoHighLevel, ...) didn't
    # contribute. New logic: count how many of the USER'S skills actually
    # appear anywhere in the job text — title, description, source-tagged
    # skills, requirements, keywords. Their list IS the reference.
    expanded_user_skills = _expand_profile_skills(profile_skills)
    for entry in profile_work_history or []:
        for s in entry.get("skills", []) or []:
            cleaned = (s or "").strip().lower()
            if len(cleaned) >= 3:
                expanded_user_skills.add(cleaned)

    haystack = " ".join([
        title_lower,
        (job_description or "").lower(),
        " ".join(s for s in (job_skills or []) if s).lower(),
        " ".join(s for s in (job_requirements or []) if s).lower(),
        " ".join(s for s in (job_keywords or []) if s).lower(),
    ])

    matched_skills = {sk for sk in expanded_user_skills if sk in haystack}
    match_count = len(matched_skills)

    # Score curve: every match counts, with diminishing returns past 6.
    #   0  → 0
    #   1  → 6
    #   2  → 11
    #   3  → 15
    #   4  → 18
    #   5  → 21
    #   6+ → 25
    if match_count == 0:
        skill_score = 0.0
    elif match_count == 1:
        skill_score = 6.0
    elif match_count == 2:
        skill_score = 11.0
    elif match_count == 3:
        skill_score = 15.0
    elif match_count == 4:
        skill_score = 18.0
    elif match_count == 5:
        skill_score = 21.0
    else:
        skill_score = 25.0

    reasoning["user_skills_matched"] = sorted(matched_skills)[:15]
    reasoning["user_skills_total"] = len(expanded_user_skills)

    # ── Seniority Match (0-15) ────────────────────────────────────────────
    seniority_score = _score_seniority(job_seniority, title_lower, profile_work_history)

    # ── Industry/Domain (0-10) ────────────────────────────────────────────
    # Industry keywords now also include the user's skills — so a job
    # whose JD lists "n8n + Zapier + RAG" gets credit even if the title
    # is something generic like 'Senior Engineer'.
    industry_searchable = haystack
    ai_matches = sum(1 for kw in AI_INDUSTRY_KEYWORDS if kw in industry_searchable)
    if ai_matches >= 3:
        industry_score = 10.0
    elif ai_matches >= 2:
        industry_score = 7.0
    elif ai_matches >= 1:
        industry_score = 4.0
    else:
        industry_score = 0.0

    return {
        "title_score": title_score,
        "skill_score": skill_score,
        "seniority_score": seniority_score,
        "industry_score": industry_score,
        "reasoning": reasoning,
    }


def _score_seniority(job_seniority, title, work_history):
    """Reuse PM scorer's seniority logic."""
    from app.services.scoring.pm_scorer import _score_seniority as pm_seniority
    return pm_seniority(job_seniority, title, work_history)
