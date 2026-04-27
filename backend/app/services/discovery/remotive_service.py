"""Remotive (remotive.com) — public, key-less JSON API.

Endpoint: GET https://remotive.com/api/remote-jobs
Returns a single JSON payload with the full active list (~1-2k jobs). Each
record has a `candidate_required_location` field we use for Nigeria-eligibility.

NOTE on rate limit: Remotive throttles aggressively. Their docs say >2 calls
per minute will be blocked, and they recommend at most a few polls per day.
This module makes ONE call per discovery run — don't call it inside loops.
"""

from __future__ import annotations

import logging

import httpx

from app.services.discovery.eligibility import (
    is_nigeria_friendly,
    matches_keywords,
)

logger = logging.getLogger(__name__)

REMOTIVE_API = "https://remotive.com/api/remote-jobs"
USER_AGENT = "JobHuntPipeline/1.0 (+contact: hello@example.com)"


async def fetch_jobs(
    keywords: set[str] | None = None,
    category: str | None = None,
    limit: int = 200,
) -> list[dict]:
    """Fetch the active Remotive feed and filter to Nigeria-eligible postings.

    Args:
        keywords: substring keywords to filter title/description on.
        category: optional Remotive category slug (e.g. "software-dev").
        limit: max number of *eligible* jobs to return.
    """
    params: dict[str, str | int] = {}
    if category:
        params["category"] = category
    if limit:
        params["limit"] = max(limit * 5, 200)  # request more, we'll filter

    async with httpx.AsyncClient(
        timeout=30.0,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    ) as client:
        try:
            response = await client.get(REMOTIVE_API, params=params)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as e:
            logger.error("Remotive API error: %s", e)
            return []

    jobs_raw = payload.get("jobs") or []
    matched: list[dict] = []

    for item in jobs_raw:
        title = item.get("title") or ""
        description = item.get("description") or ""
        tags = " ".join(item.get("tags") or [])
        searchable = f"{title} {description} {tags}"

        if not matches_keywords(searchable, keywords):
            continue

        if is_nigeria_friendly(
            candidate_required_location=item.get("candidate_required_location"),
            description=description,
        ) is False:
            continue

        matched.append(_normalize_remotive(item))
        if len(matched) >= limit:
            break

    logger.info("Remotive: %d eligible (of %d raw)", len(matched), len(jobs_raw))
    return matched


def _normalize_remotive(item: dict) -> dict:
    """Map a Remotive job to our internal raw-job dict shape."""
    salary_text = item.get("salary") or None

    return {
        "external_id": str(item.get("id") or item.get("url")),
        "source_name": "remotive",
        "source_type": "api",
        "company": item.get("company_name") or "Unknown",
        "title": item.get("title") or "",
        # Their location field is the candidate location requirement, not a
        # physical office — for our model we treat it as the "location" string
        # since the postings are all remote.
        "location": item.get("candidate_required_location") or "Worldwide",
        "country": None,
        "remote_type": "full_remote",
        "job_url": item.get("url") or "",
        "apply_url": item.get("url") or "",
        "salary_text": salary_text,
        "salary_min": None,  # Remotive salary is free-text only
        "salary_max": None,
        "salary_currency": None,
        "raw_description": item.get("description") or "",
        "posted_at": item.get("publication_date"),
        "tags": item.get("tags") or [],
        "employment_type": item.get("job_type"),
    }
