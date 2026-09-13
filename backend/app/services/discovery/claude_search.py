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

logger = logging.getLogger(__name__)


_RECORD_JOBS_TOOL = {
    "name": "record_jobs",
    "description": (
        "Record a list of remote jobs that match the candidate's profile. "
        "Capture as much detail as the listing actually provides — title, "
        "company, and URL are mandatory; everything else is strongly "
        "encouraged but optional. Call this ONCE at the end with all "
        "matches consolidated."
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
                                "Role description — pull as much actual posting "
                                "content as you can see (responsibilities, team, "
                                "stack, domain). Longer is better for scoring; "
                                "even 1-2 sentences is fine if that's all the "
                                "listing card shows. Never invent content."
                            ),
                        },
                        "skills": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Specific skills / tools the posting explicitly "
                                "mentions (Python, n8n, LangChain, Figma, Jira, "
                                "etc.). Include any you see; empty array is fine "
                                "if the listing doesn't mention specifics."
                            ),
                        },
                        "requirements": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Hard requirements ('5+ years PM experience', "
                                "'BS in CS', 'must be US-based'). Optional — "
                                "empty array if not stated."
                            ),
                        },
                        "keywords": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Domain / function / industry keywords (fintech, "
                                "B2B SaaS, agentic AI, growth, infra). Optional."
                            ),
                        },
                        "seniority": {
                            "type": "string",
                            "enum": ["intern", "junior", "mid", "senior", "lead", "principal", "executive", "unknown"],
                        },
                    },
                    "required": ["title", "company", "url"],
                },
            },
        },
        "required": ["jobs"],
    },
}


_SYSTEM_PROMPT = (
    "You find currently-open job postings matching a candidate's profile. "
    "Search the open web — company careers pages, ATS hosts (Greenhouse, "
    "Lever, Ashby, Workable), niche job boards, and recent posts on "
    "LinkedIn / Wellfound / RemoteOK. Prefer direct posting URLs over "
    "aggregator redirects.\n\n"
    "HARD RULES:\n"
    "- Only postings that are CURRENTLY OPEN. Skip closed / expired listings.\n"
    "- Respect the candidate's stated remote_preference and location "
    "  filters in the user message. If they accept 'any', return remote / "
    "  hybrid / onsite freely. If they ask for 'full_remote', skip onsite "
    "  postings.\n"
    "- Only return jobs in the candidate's preferred countries (or remote "
    "  jobs that explicitly allow those countries). Do NOT return jobs in "
    "  countries the candidate didn't list.\n"
    "- Match the candidate's target roles tightly. The candidate could be "
    "  in any profession — engineering, product, design, marketing, sales, "
    "  finance, operations, HR, customer success, healthcare, education, "
    "  legal, etc. Stay inside the family of roles they've stated. Do NOT "
    "  surface adjacent-but-different professions (a marketer should not "
    "  get sales jobs; a designer should not get engineering jobs).\n"
    "- Each URL must point to a SPECIFIC posting, not a careers landing page.\n"
    "- Aim for 15–25 matches. Don't return more than 30.\n"
    "- Don't invent salary ranges. Omit if not visible.\n\n"
    "DATA QUALITY (capture what you can see — never invent):\n"
    "- `description`: pull as much real posting content as you can — "
    "  responsibilities, team, stack, domain. Longer helps scoring, but a "
    "  short snippet from the listing card is still useful. Empty is "
    "  acceptable if the listing card has nothing.\n"
    "- `skills`: specific tools / technologies the posting mentions. "
    "  Empty array if nothing specific is stated.\n"
    "- `requirements` and `keywords`: optional, populate when stated.\n"
    "- `seniority`: optional, only when clearly indicated.\n\n"
    "Title + company + URL are the only mandatory fields. Better to return "
    "20 partially-detailed matches than 0 'perfect' ones — the downstream "
    "scorer can rank from title alone if needed.\n\n"
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

    from app.llm.client import llm_client, model_for, effort_for

    # Country list is a HARD constraint — Claude should not return jobs
    # outside it. Phrasing matters: 'preferred' was getting interpreted
    # as 'nice to have' and the model would return US roles even for a
    # NL/DE/UK-only user.
    countries_clause = (
        f"\nAllowed countries (HARD FILTER — only these, or fully remote): "
        f"{', '.join(preferred_countries)}"
        if preferred_countries else ""
    )
    # Always state the remote preference, even when 'any', so the model
    # knows it shouldn't restrict itself to remote-only.
    if remote_preference == "any" or not remote_preference:
        remote_clause = (
            "\nRemote preference: any — remote, hybrid, AND onsite are all "
            "acceptable. Do NOT restrict the search to remote-only."
        )
    else:
        remote_clause = f"\nRemote preference: {remote_preference}"
    skills_clause = (
        f"\nKey skills: {', '.join(skills[:15])}"
        if skills else ""
    )

    user_prompt = (
        "Find currently-open jobs for this candidate:\n\n"
        f"Target roles: {', '.join(target_roles)}"
        f"{countries_clause}{remote_clause}{skills_clause}\n\n"
        f"Run web_search 2–{max_searches} times with different angles "
        "(role + recent post, role + specific ATS, role + small-company variants). "
        "Then call record_jobs with the consolidated list. Aim for variety — "
        "don't return 20 jobs from the same company."
    )

    try:
        response = await llm_client.client.messages.create(
            model=model_for("search"),
            max_tokens=12000,
            output_config={"effort": effort_for("search")},
            system=_SYSTEM_PROMPT,
            tools=[
                {"type": "web_search_20260209", "name": "web_search", "max_uses": max_searches},
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
