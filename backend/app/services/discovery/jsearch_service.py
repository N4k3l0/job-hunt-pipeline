import asyncio
import logging

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

JSEARCH_BASE = "https://jsearch.p.rapidapi.com"

DEFAULT_QUERIES = [
    # PM roles
    "product manager",
    "senior product manager",
    "product manager AI",
    "product manager remote",
    "technical product manager",
    "group product manager",
    "product lead",
    "product owner",
    "head of product",
    # AI/Automation roles
    "AI automation engineer",
    "AI product manager",
    "machine learning product manager",
    # Location-specific
    "product manager United States",
    "product manager Canada",
    "product manager United Kingdom",
    "product manager Germany",
]


# A JSearch request takes 7 to 20 seconds. Asked one after another, five
# searches of two pages ran past the discovery source's 50-second budget
# every day and the jobs found were thrown away. Searches now run at the
# same time and whatever has arrived by the deadline is kept, leaving time
# to store the jobs.
REQUEST_TIMEOUT = httpx.Timeout(25.0, connect=5.0)
DEADLINE_SECONDS = 30.0


async def fetch_jobs(
    queries: list[str] | None = None,
    max_pages: int = 1,
    date_posted: str = "3days",
    deadline_seconds: float = DEADLINE_SECONDS,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[dict]:
    """Fetch jobs from JSearch API (via RapidAPI).

    Args:
        queries: Search queries, run at the same time
        max_pages: Max pages per query, asked in order
        date_posted: 'today', '3days', 'week', 'month'
        deadline_seconds: Searches still running then are dropped; what
            the others found is returned

    Returns:
        List of normalized job dicts
    """
    if not settings.jsearch_rapidapi_key:
        logger.warning("JSearch API key not configured")
        return []

    queries = queries or DEFAULT_QUERIES
    headers = {
        "X-RapidAPI-Key": settings.jsearch_rapidapi_key,
        "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
    }

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, transport=transport) as client:
        async def search(query: str) -> list[dict]:
            found: list[dict] = []
            for page in range(1, max_pages + 1):
                try:
                    response = await client.get(
                        f"{JSEARCH_BASE}/search",
                        headers=headers,
                        params={
                            "query": query,
                            "page": str(page),
                            "num_pages": "1",
                            "date_posted": date_posted,
                        },
                    )
                    response.raise_for_status()
                    results = response.json().get("data", [])
                except (httpx.HTTPError, ValueError) as e:
                    logger.error("JSearch API error for '%s': %s", query, e)
                    break
                if not results:
                    break
                found += [_normalize_jsearch_result(item) for item in results]
                logger.info("JSearch page %d: %d results for '%s'", page, len(results), query)
            return found

        tasks = [asyncio.create_task(search(q)) for q in queries]
        done, pending = await asyncio.wait(tasks, timeout=deadline_seconds)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
            logger.warning(
                "JSearch: %d of %d searches didn't finish in %.0fs; keeping what the others found",
                len(pending), len(tasks), deadline_seconds,
            )

    all_jobs = [job for task in done for job in task.result()]
    logger.info("JSearch total: %d jobs", len(all_jobs))
    return all_jobs


def _normalize_jsearch_result(item: dict) -> dict:
    """Normalize a JSearch API result."""
    # Determine remote type
    remote_type = None
    if item.get("job_is_remote"):
        remote_type = "full_remote"

    # Build location string
    city = item.get("job_city", "")
    state = item.get("job_state", "")
    country = item.get("job_country", "")
    location_parts = [p for p in [city, state, country] if p]
    location = ", ".join(location_parts) if location_parts else None

    # Salary
    salary_min = item.get("job_min_salary")
    salary_max = item.get("job_max_salary")
    salary_currency = item.get("job_salary_currency", "USD")

    # Normalize salary period to annual
    period = (item.get("job_salary_period") or "").lower()
    if period == "hourly" and salary_min:
        salary_min = int(salary_min * 2080)
        salary_max = int(salary_max * 2080) if salary_max else None

    salary_text = None
    if salary_min and salary_max:
        salary_text = f"{salary_currency} {salary_min:,} - {salary_max:,}"
    elif salary_min:
        salary_text = f"{salary_currency} {salary_min:,}+"

    return {
        "external_id": item.get("job_id", ""),
        "source_name": "jsearch",
        "source_type": "api",
        "company": item.get("employer_name", "Unknown"),
        "title": item.get("job_title", ""),
        "location": location,
        "country": item.get("job_country", ""),
        "remote_type": remote_type,
        "job_url": item.get("job_apply_link") or item.get("job_google_link", ""),
        "apply_url": item.get("job_apply_link", ""),
        "salary_text": salary_text,
        "salary_min": int(salary_min) if salary_min else None,
        "salary_max": int(salary_max) if salary_max else None,
        "salary_currency": salary_currency,
        "raw_description": item.get("job_description", ""),
        "posted_at": item.get("job_posted_at_datetime_utc"),
        "employment_type": item.get("job_employment_type"),
        "publisher": item.get("job_publisher", ""),
    }
