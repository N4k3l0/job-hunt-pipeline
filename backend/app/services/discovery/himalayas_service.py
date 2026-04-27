"""Himalayas (himalayas.app) — public, key-less REST API for remote jobs.

Two endpoints we use:
- GET /jobs/api               — paginated full feed (newest first)
- GET /jobs/api/search?...    — server-side filterable

We use the /search endpoint with `worldwide=true` so the feed itself is biased
toward Nigeria-eligible postings; we still apply our own `is_nigeria_friendly`
heuristic per-row to catch the postings that have a `locationRestrictions`
field even when the worldwide flag was set.
"""

from __future__ import annotations

import logging

import httpx

from app.services.discovery.eligibility import (
    is_nigeria_friendly,
    matches_keywords,
)

logger = logging.getLogger(__name__)

HIMALAYAS_SEARCH_API = "https://himalayas.app/jobs/api/search"
PAGE_SIZE = 100
USER_AGENT = "JobHuntPipeline/1.0 (+https://github.com/anthropics/claude-code)"


async def fetch_jobs(
    keywords: set[str] | None = None,
    max_pages: int = 5,
) -> list[dict]:
    """Pull recent worldwide remote jobs from Himalayas.

    Args:
        keywords: substring keywords to filter title/description on. If None,
            returns the full feed (still post-filtered by the worldwide flag
            and the eligibility heuristic).
        max_pages: cap on pagination to keep cost bounded.
    """
    matched: list[dict] = []
    seen_ids: set[str] = set()

    async with httpx.AsyncClient(
        timeout=30.0,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    ) as client:
        for page in range(1, max_pages + 1):
            params = {
                "worldwide": "true",
                "limit": PAGE_SIZE,
                "offset": (page - 1) * PAGE_SIZE,
            }
            try:
                response = await client.get(HIMALAYAS_SEARCH_API, params=params)
                response.raise_for_status()
                payload = response.json()
            except httpx.HTTPError as e:
                logger.error("Himalayas API error on page %d: %s", page, e)
                break

            jobs_raw = payload.get("jobs") or payload.get("data") or []
            if not jobs_raw:
                break

            page_added = 0
            for item in jobs_raw:
                job_id = str(item.get("id") or item.get("guid") or item.get("slug") or "")
                if not job_id or job_id in seen_ids:
                    continue
                seen_ids.add(job_id)

                title = item.get("title") or ""
                description = item.get("description") or item.get("excerpt") or ""
                if not matches_keywords(f"{title} {description}", keywords):
                    continue

                # Drop postings that *explicitly* exclude Nigeria. Unknown
                # eligibility (`None`) still goes through.
                if is_nigeria_friendly(
                    location_restrictions=item.get("locationRestrictions"),
                    description=description,
                ) is False:
                    continue

                matched.append(_normalize_himalayas(item))
                page_added += 1

            logger.info(
                "Himalayas page %d: %d added (of %d raw)",
                page, page_added, len(jobs_raw),
            )
            if len(jobs_raw) < PAGE_SIZE:
                break  # last page

    logger.info("Himalayas total: %d eligible jobs", len(matched))
    return matched


def _normalize_himalayas(item: dict) -> dict:
    """Map a Himalayas job to our internal raw-job dict shape."""
    company_obj = item.get("company") or {}
    company_name = (
        company_obj.get("name") if isinstance(company_obj, dict)
        else (company_obj or item.get("companyName") or "Unknown")
    )

    job_url = item.get("applicationLink") or item.get("url") or item.get("jobUrl") or ""
    if job_url and not job_url.startswith("http"):
        # Some Himalayas slugs come back as relative paths.
        job_url = f"https://himalayas.app{job_url}"

    salary_min = item.get("minBaseSalary") or item.get("salaryMin")
    salary_max = item.get("maxBaseSalary") or item.get("salaryMax")
    salary_currency = item.get("salaryCurrency") or "USD"

    location_restrictions = item.get("locationRestrictions") or []
    location_text = ", ".join(location_restrictions) if location_restrictions else "Worldwide"

    return {
        "external_id": str(item.get("id") or item.get("guid") or item.get("slug")),
        "source_name": "himalayas",
        "source_type": "api",
        "company": company_name or "Unknown",
        "title": item.get("title") or "",
        "location": location_text,
        "country": None,  # mostly worldwide; let downstream classify
        "remote_type": "full_remote",
        "job_url": job_url,
        "apply_url": item.get("applicationLink") or job_url,
        "salary_text": item.get("salary") or None,
        "salary_min": salary_min,
        "salary_max": salary_max,
        "salary_currency": salary_currency,
        "raw_description": item.get("description") or item.get("excerpt") or "",
        "posted_at": item.get("publishedAt") or item.get("pubDate"),
        "tags": item.get("categories") or item.get("tags") or [],
        "employment_type": item.get("employmentType"),
        "seniority": item.get("seniority"),
    }
