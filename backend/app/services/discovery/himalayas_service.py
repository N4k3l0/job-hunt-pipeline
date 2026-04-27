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
# Himalayas caps `limit` at 20 per page in practice — asking for more is
# silently downgraded. The API exposes total via `totalCount` in the response.
PAGE_SIZE = 20
USER_AGENT = "JobHuntPipeline/1.0 (+https://github.com/anthropics/claude-code)"


async def fetch_jobs(
    keywords: set[str] | None = None,
    max_pages: int = 25,
) -> list[dict]:
    """Pull recent worldwide remote jobs from Himalayas.

    Args:
        keywords: substring keywords to filter title/description on. If None,
            returns the full feed (still post-filtered by the worldwide flag
            and the eligibility heuristic).
        max_pages: cap on pagination (20 jobs per page). 25 = up to 500 jobs
            per discovery run.
    """
    matched: list[dict] = []
    seen_ids: set[str] = set()
    total_count: int | None = None

    async with httpx.AsyncClient(
        timeout=30.0,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    ) as client:
        for page in range(max_pages):
            params = {
                "worldwide": "true",
                "limit": PAGE_SIZE,
                "offset": page * PAGE_SIZE,
            }
            try:
                response = await client.get(HIMALAYAS_SEARCH_API, params=params)
                response.raise_for_status()
                payload = response.json()
            except httpx.HTTPError as e:
                logger.error("Himalayas API error on page %d: %s", page, e)
                break

            if total_count is None:
                total_count = payload.get("totalCount")
                logger.info("Himalayas: %s worldwide jobs available", total_count)

            jobs_raw = payload.get("jobs") or []
            if not jobs_raw:
                break

            page_added = 0
            for item in jobs_raw:
                # External id: prefer companySlug+title hash since Himalayas
                # doesn't return an explicit id field.
                slug = item.get("companySlug") or ""
                title_part = (item.get("title") or "")[:80].lower().replace(" ", "-")
                job_id = f"{slug}__{title_part}" if slug else title_part
                if not job_id or job_id in seen_ids:
                    continue
                seen_ids.add(job_id)

                title = item.get("title") or ""
                description = item.get("description") or item.get("excerpt") or ""
                if not matches_keywords(f"{title} {description}", keywords):
                    continue

                # Drop postings that *explicitly* exclude Nigeria.
                # locationRestrictions can come back as a string repr of a list
                # (e.g. "['United States']") — handle both shapes.
                lr_raw = item.get("locationRestrictions")
                if isinstance(lr_raw, str):
                    # API sometimes returns Python-style stringified list. Best-effort parse.
                    import ast
                    try:
                        lr_list = ast.literal_eval(lr_raw) if lr_raw.startswith("[") else [lr_raw]
                    except (ValueError, SyntaxError):
                        lr_list = [lr_raw]
                else:
                    lr_list = lr_raw or []

                if is_nigeria_friendly(
                    location_restrictions=lr_list if lr_list else None,
                    description=description,
                ) is False:
                    continue

                matched.append(_normalize_himalayas(item, lr_list, job_id))
                page_added += 1

            logger.info(
                "Himalayas page %d (offset %d): %d added (of %d raw)",
                page, page * PAGE_SIZE, page_added, len(jobs_raw),
            )
            # Stop when we've fetched everything or got a short page.
            if total_count and (page + 1) * PAGE_SIZE >= total_count:
                break
            if len(jobs_raw) < PAGE_SIZE:
                break

    logger.info("Himalayas total: %d eligible jobs", len(matched))
    return matched


def _normalize_himalayas(item: dict, lr_list: list[str], external_id: str) -> dict:
    """Map a Himalayas job to our internal raw-job dict shape."""
    company_name = item.get("companyName") or "Unknown"
    company_slug = item.get("companySlug")

    # Construct a job URL from the slug since Himalayas doesn't return one.
    title = item.get("title") or ""
    title_slug = title.lower().replace(" ", "-").replace("/", "-")
    job_url = f"https://himalayas.app/companies/{company_slug}/jobs/{title_slug}" if company_slug else "https://himalayas.app/jobs"

    salary_min = item.get("minSalary")
    salary_max = item.get("maxSalary")
    salary_currency = item.get("currency") or "USD"
    salary_text = None
    if salary_min and salary_max:
        salary_text = f"${salary_min // 1000}K — ${salary_max // 1000}K {salary_currency}"
    elif salary_min:
        salary_text = f"${salary_min // 1000}K+ {salary_currency}"

    location_text = ", ".join(lr_list) if lr_list else "Worldwide"

    # categories may also be a stringified list — normalize.
    cats_raw = item.get("categories")
    if isinstance(cats_raw, str):
        import ast
        try:
            cats = ast.literal_eval(cats_raw) if cats_raw.startswith("[") else [cats_raw]
        except (ValueError, SyntaxError):
            cats = []
    else:
        cats = cats_raw or []

    return {
        "external_id": external_id,
        "source_name": "himalayas",
        "source_type": "api",
        "company": company_name,
        "title": title,
        "location": location_text,
        "country": None,
        "remote_type": "full_remote",
        "job_url": job_url,
        "apply_url": job_url,
        "salary_text": salary_text,
        "salary_min": salary_min,
        "salary_max": salary_max,
        "salary_currency": salary_currency,
        "raw_description": item.get("description") or item.get("excerpt") or "",
        "tags": cats,
        "employment_type": item.get("employmentType"),
        "seniority": (item.get("seniority") or [None])[0] if isinstance(item.get("seniority"), list) else item.get("seniority"),
    }
