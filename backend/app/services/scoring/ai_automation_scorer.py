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


def score_ai_automation_path(
    title: str,
    job_skills: list[str],
    job_requirements: list[str],
    job_keywords: list[str],
    job_seniority: str | None,
    profile_skills: list[str],
    profile_work_history: list[dict],
) -> dict:
    """Score a job on the AI Automation path."""
    title_lower = title.lower()
    reasoning = {}

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
    all_job_skills = set()
    for s in job_skills + job_requirements + job_keywords:
        all_job_skills.add(s.lower().strip())

    profile_skills_lower = {s.lower().strip() for s in profile_skills}
    for entry in profile_work_history:
        for s in entry.get("skills", []):
            profile_skills_lower.add(s.lower().strip())

    ai_relevant = all_job_skills & AI_SKILLS
    matched_skills = ai_relevant & profile_skills_lower

    if ai_relevant:
        skill_ratio = len(matched_skills) / len(ai_relevant)
    else:
        general_overlap = all_job_skills & profile_skills_lower
        skill_ratio = min(len(general_overlap) / max(len(all_job_skills), 1), 1.0) if all_job_skills else 0.3

    skill_score = round(skill_ratio * 25, 1)
    reasoning["ai_skills_matched"] = list(matched_skills)[:10]
    reasoning["ai_skills_missing"] = list(ai_relevant - matched_skills)[:10]

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
