import logging

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

ADZUNA_BASE = "https://api.adzuna.com/v1/api/jobs"

# Countries supported by Adzuna
ADZUNA_COUNTRIES = {
    "US": "us",
    "CA": "ca",
    "GB": "gb",
    "DE": "de",
    "FR": "fr",
    "NL": "nl",
    "AT": "at",
    "AU": "au",
}

# Default search keywords
DEFAULT_KEYWORDS = [
    "product manager",
    "ai product manager",
    "ai automation",
    "automation engineer",
]


async def fetch_jobs(
    country_code: str = "us",
    keywords: list[str] | None = None,
    max_pages: int = 1,
    results_per_page: int = 50,
) -> list[dict]:
    """Fetch jobs from Adzuna API.

    Args:
        country_code: Adzuna country code (us, ca, gb, de, etc.)
        keywords: Search keywords
        max_pages: Max pages to fetch
        results_per_page: Results per page

    Returns:
        List of normalized job dicts
    """
    if not settings.adzuna_app_id or not settings.adzuna_app_key:
        logger.warning("Adzuna API credentials not configured")
        return []

    keywords = keywords or DEFAULT_KEYWORDS
    all_jobs = []

    # Tight per-request timeout: when Adzuna rate-limits us under concurrent
    # country fan-out, individual calls can hang for tens of seconds. We'd
    # rather skip a slow country than blow the cron's 35s per-source budget.
    import asyncio
    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=4.0, read=8.0, write=4.0, pool=4.0)) as client:
        for keyword in keywords:
            for page in range(1, max_pages + 1):
                # Up to 2 retries on 429 with exponential backoff. Adzuna's
                # free tier limits ~25/min — under bursty cron load we
                # sometimes hit it even with the per-runner semaphore.
                # Backoff gives them a moment to refill our bucket.
                attempts = 0
                while True:
                    attempts += 1
                    try:
                        response = await client.get(
                            f"{ADZUNA_BASE}/{country_code}/search/{page}",
                            params={
                                "app_id": settings.adzuna_app_id,
                                "app_key": settings.adzuna_app_key,
                                "results_per_page": results_per_page,
                                "what": keyword,
                                "content-type": "application/json",
                            },
                        )
                        if response.status_code == 429 and attempts <= 2:
                            # Honour Retry-After if present, otherwise back
                            # off 2s then 5s. Keeps us within the cron's
                            # per-source budget (~35s) on worst case.
                            ra = response.headers.get("Retry-After")
                            wait = float(ra) if ra and ra.replace(".", "").isdigit() else (2.0 if attempts == 1 else 5.0)
                            logger.info(
                                "Adzuna 429 on %s/%s — retrying in %.1fs (attempt %d)",
                                country_code, keyword, wait, attempts,
                            )
                            await asyncio.sleep(wait)
                            continue
                        response.raise_for_status()
                        data = response.json()
                        break  # success — exit retry loop
                    except httpx.HTTPError as e:
                        logger.error("Adzuna API error (%s/%s): %s", country_code, keyword, e)
                        data = None
                        break

                if not data:
                    break  # exit page loop on hard failure

                results = data.get("results", [])
                if not results:
                    break

                for item in results:
                    job = _normalize_adzuna_result(item, country_code.upper())
                    all_jobs.append(job)

                logger.info(
                    "Adzuna %s page %d: %d results for '%s'",
                    country_code,
                    page,
                    len(results),
                    keyword,
                )

    logger.info("Adzuna total: %d jobs from %s", len(all_jobs), country_code)
    return all_jobs


def _normalize_adzuna_result(item: dict, country: str) -> dict:
    """Normalize an Adzuna API result to our standard format."""
    location = item.get("location", {}).get("display_name", "")
    salary_min = item.get("salary_min")
    salary_max = item.get("salary_max")

    return {
        "external_id": str(item.get("id", "")),
        "source_name": "adzuna",
        "source_type": "api",
        "company": item.get("company", {}).get("display_name", "Unknown"),
        "title": item.get("title", ""),
        "location": location,
        "country": country,
        "job_url": item.get("redirect_url", ""),
        "salary_min": int(salary_min) if salary_min else None,
        "salary_max": int(salary_max) if salary_max else None,
        "salary_currency": _country_currency(country),
        "raw_description": item.get("description", ""),
        "posted_at": item.get("created"),
        "category": item.get("category", {}).get("label", ""),
    }


def _country_currency(country: str) -> str:
    currencies = {
        "US": "USD", "CA": "CAD", "GB": "GBP",
        "DE": "EUR", "FR": "EUR", "NL": "EUR",
        "AT": "EUR", "AU": "AUD",
    }
    return currencies.get(country, "USD")
