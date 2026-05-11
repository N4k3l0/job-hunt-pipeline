"""Use Claude with the web_search server tool to find remote jobs
tailored to a single user's profile.

Complements the existing cron-driven discovery sources (Greenhouse,
Lever, Ashby, RemoteOK, Adzuna, etc.) — those handle base volume;
this is the targeted "find me fresh listings that match MY skills"
path. Costs ~$0.30 per call (5 web_search calls + LLM tokens), so
it runs on-demand per user, never on a cron.

Reuses the same plumbing as the apply-link resolver and the
decision-maker finder. Output shape matches the existing
_ingest_raw_jobs contract so the result flows through dedup + scoring
exactly the same as cron-sourced jobs.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


_RECORD_JOBS_TOOL = {
    "name": "record_jobs",
    "description": (
        "Record a list of remote jobs that match the candidate's profile. "
        "Each job MUST include enough detail for downstream scoring — a "
        "1-sentence summary is not enough. Only call this ONCE at the end "
        "with all matches consolidated."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "jobs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "company": {"type": "string"},
                        "url": {
                            "type": "string",
                            "description": (
                                "Direct posting URL. Prefer company careers / ATS "
                                "(greenhouse, lever, ashby, workable, etc.) over "
                                "aggregator pages."
                            ),
                        },
                        "location": {"type": "string"},
                        "country": {
                            "type": "string",
                            "description": "ISO 3166-1 alpha-2 code (US, GB, DE, etc.) if known.",
                        },
                        "remote_type": {
                            "type": "string",
                            "enum": ["full_remote", "hybrid", "onsite", "unknown"],
                        },
                        "salary_min": {"type": "integer"},
                        "salary_max": {"type": "integer"},
                        "salary_currency": {"type": "string"},
                        "description": {
                            "type": "string",
                            "description": (
                                "Substantive role description — 600–1500 characters. "
                                "Should include what the role does, the team, the "
                                "stack/domain, and notable responsibilities. NOT a "
                                "1-sentence summary. Pulled from the actual posting "
                                "content, not invented."
                            ),
                        },
                        "skills": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Specific skills / tools / technologies the posting "
                                "explicitly mentions. Examples: Python, n8n, LangChain, "
                                "Figma, Jira, Salesforce, Postgres. 5–15 entries."
                            ),
                        },
                        "requirements": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Hard requirements pulled from the JD ('5+ years PM "
                                "experience', 'BS in CS', 'must be US-based', etc.). "
                                "3–10 entries."
                            ),
                        },
                        "keywords": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Domain / function / industry keywords. Examples: "
                                "fintech, B2B SaaS, agentic AI, growth, infra. "
                                "3–10 entries."
                            ),
                        },
                        "seniority": {
                            "type": "string",
                            "enum": ["intern", "junior", "mid", "senior", "lead", "principal", "executive", "unknown"],
                        },
                    },
                    "required": ["title", "company", "url", "description", "skills"],
                },
            },
        },
        "required": ["jobs"],
    },
}


_SYSTEM_PROMPT = (
    "You find remote job postings matching a candidate's profile. "
    "Search the open web — company careers pages, ATS hosts (Greenhouse, "
    "Lever, Ashby, Workable), niche job boards, and recent posts on "
    "LinkedIn / Wellfound / RemoteOK. Prefer direct posting URLs over "
    "aggregator redirects.\n\n"
    "HARD RULES:\n"
    "- Only postings that are CURRENTLY OPEN. Skip closed / expired listings.\n"
    "- Match the candidate's target roles tightly. A PM should not get "
    "  AI Engineer listings; an AI Engineer should not get PM listings.\n"
    "- Each URL must point to a SPECIFIC posting, not a careers landing page.\n"
    "- Aim for 15–25 high-quality matches. Quality > quantity.\n"
    "- NEVER return more than 30 results.\n"
    "- Don't invent salary ranges. If you can't see them on the page, omit them.\n\n"
    "CRITICAL — DATA QUALITY:\n"
    "Each job's `description` must be 600–1500 characters. A 1-line summary "
    "makes the downstream scoring useless because the matcher looks for "
    "skill mentions in the description body. Pull the actual responsibilities "
    "/ team / stack from the posting — don't paraphrase it down to a tagline.\n"
    "Populate `skills` (5–15 specific tools), `requirements` (3–10 hard asks), "
    "`keywords` (3–10 domain/industry terms), and `seniority` from the actual "
    "JD content. These feed the scorer directly — empty arrays = bad scores.\n"
    "If you can't open / read a posting in detail (just have the listing card "
    "from a search result), SKIP it rather than return a thin entry.\n\n"
    "Call record_jobs ONCE with all the matches at the end."
)


async def search_jobs_for_user(
    *,
    target_roles: list[str],
    preferred_countries: list[str] | None = None,
    skills: list[str] | None = None,
    remote_preference: str | None = None,
    max_searches: int = 5,
) -> list[dict[str, Any]]:
    """Run Claude + web_search for one user's profile. Returns
    normalized job dicts in the format the existing
    `_ingest_raw_jobs` pipeline expects.

    Raises on Anthropic API failure so the caller can surface the
    real error to the UI instead of returning an empty list silently.
    """
    if not target_roles:
        return []  # Nothing actionable to search for.

    import anthropic
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    countries_clause = (
        f"\nPreferred locations: {', '.join(preferred_countries)}"
        if preferred_countries else ""
    )
    remote_clause = (
        f"\nRemote preference: {remote_preference}"
        if remote_preference and remote_preference != "any" else ""
    )
    skills_clause = (
        f"\nKey skills: {', '.join(skills[:15])}"
        if skills else ""
    )

    user_prompt = (
        "Find currently-open remote jobs for this candidate:\n\n"
        f"Target roles: {', '.join(target_roles)}"
        f"{countries_clause}{remote_clause}{skills_clause}\n\n"
        f"Run web_search 2–{max_searches} times with different angles "
        "(role + recent post, role + specific ATS, role + small-company variants). "
        "Then call record_jobs with the consolidated list. Aim for variety — "
        "don't return 20 jobs from the same company."
    )

    try:
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=8192,
            system=_SYSTEM_PROMPT,
            tools=[
                {"type": "web_search_20250305", "name": "web_search", "max_uses": max_searches},
                _RECORD_JOBS_TOOL,
            ],
            messages=[{"role": "user", "content": user_prompt}],
        )
    except Exception as e:
        logger.error("Claude job search failed: %s", e)
        raise

    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "record_jobs":
            raw_jobs = (block.input or {}).get("jobs", [])
            normalized: list[dict] = []
            for j in raw_jobs:
                if not _is_valid(j):
                    continue
                normalized.append(_normalize(j))
            logger.info(
                "Claude web_search returned %d jobs (%d valid) for target_roles=%s",
                len(raw_jobs), len(normalized), target_roles,
            )
            return normalized

    logger.warning("Claude web_search returned no record_jobs tool call")
    return []


def _is_valid(j: dict) -> bool:
    """Reject jobs missing critical fields or with obviously-bad URLs."""
    if not (j.get("title") and j.get("company") and j.get("url")):
        return False
    url = str(j.get("url") or "").strip().lower()
    if not (url.startswith("http://") or url.startswith("https://")):
        return False
    return True


def _normalize(j: dict) -> dict[str, Any]:
    """Shape into the dict format _ingest_raw_jobs expects. Mirrors what
    the existing aggregator services (Adzuna, RemoteOK, etc.) produce —
    plus the LLM-extracted skills / requirements / keywords / seniority
    which the normalizer plumbs into the JobEntity row so the scorer
    can match against them."""
    url = str(j.get("url") or "").strip()

    def _clean_list(raw: Any) -> list[str]:
        if not isinstance(raw, list):
            return []
        return [str(item).strip() for item in raw if item and str(item).strip()][:25]

    return {
        "external_id": url,  # URL is unique enough for the source-level dedup
        "source_name": "web_search",
        "source_type": "api",
        "company": str(j.get("company") or "").strip(),
        "title": str(j.get("title") or "").strip(),
        "location": str(j.get("location") or "Remote").strip(),
        "country": (str(j.get("country") or "").strip().upper()[:2] or None),
        "remote_type": j.get("remote_type") or "full_remote",
        "job_url": url,
        "apply_url": url,
        "salary_min": j.get("salary_min"),
        "salary_max": j.get("salary_max"),
        "salary_currency": (str(j.get("salary_currency") or "").upper()[:3] or None),
        "raw_description": str(j.get("description") or "").strip(),
        "posted_at": None,
        "tags": [],
        # The fields below populate JobEntity via the normalizer's plumbing.
        # Without them, skill-overlap scoring runs against an empty haystack
        # and every web-search result lands with a sub-50 score regardless
        # of how good the match actually is.
        "required_skills": _clean_list(j.get("skills")),
        "requirements": _clean_list(j.get("requirements")),
        "keywords": _clean_list(j.get("keywords")),
        "seniority": (str(j.get("seniority") or "").strip().lower() or None),
    }
