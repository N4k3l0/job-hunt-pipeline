import logging

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

APIFY_BASE = "https://api.apify.com/v2"


async def fetch_dataset_items(actor_run_id: str) -> list[dict]:
    """Fetch results from a completed Apify actor run.

    Args:
        actor_run_id: The Apify actor run ID

    Returns:
        List of raw items from the dataset
    """
    if not settings.apify_api_token:
        logger.warning("Apify API token not configured")
        return []

    async with httpx.AsyncClient(timeout=60.0) as client:
        # Get dataset ID from the run
        response = await client.get(
            f"{APIFY_BASE}/actor-runs/{actor_run_id}",
            params={"token": settings.apify_api_token},
        )
        response.raise_for_status()
        run_data = response.json().get("data", {})
        dataset_id = run_data.get("defaultDatasetId")

        if not dataset_id:
            logger.error("No dataset found for run %s", actor_run_id)
            return []

        # Fetch all items from the dataset
        response = await client.get(
            f"{APIFY_BASE}/datasets/{dataset_id}/items",
            params={
                "token": settings.apify_api_token,
                "format": "json",
            },
        )
        response.raise_for_status()
        items = response.json()

    logger.info("Fetched %d items from Apify run %s", len(items), actor_run_id)
    return items


def normalize_linkedin_job(item: dict) -> dict:
    """Normalize a LinkedIn Jobs Scraper result."""
    location = item.get("location", "")
    company = item.get("companyName", "") or item.get("company", "Unknown")

    return {
        "external_id": str(item.get("id", item.get("jobId", ""))),
        "source_name": "linkedin",
        "source_type": "apify",
        "company": company,
        "title": item.get("title", ""),
        "location": location,
        "country": _guess_country(location),
        "remote_type": _detect_remote(item),
        "job_url": item.get("url", item.get("link", "")),
        "apply_url": item.get("applyUrl", ""),
        "salary_text": item.get("salary", item.get("salaryInfo", "")),
        "raw_description": item.get("description", item.get("descriptionHtml", "")),
        "posted_at": item.get("postedAt", item.get("publishedAt")),
        "seniority": item.get("seniorityLevel"),
        "employment_type": item.get("employmentType"),
    }


def normalize_indeed_job(item: dict) -> dict:
    """Normalize an Indeed Scraper result."""
    location = item.get("location", "")

    salary_text = item.get("salary", "")
    salary_min = None
    salary_max = None
    if item.get("salaryMin"):
        salary_min = int(item["salaryMin"])
    if item.get("salaryMax"):
        salary_max = int(item["salaryMax"])

    return {
        "external_id": str(item.get("id", item.get("positionId", ""))),
        "source_name": "indeed",
        "source_type": "apify",
        "company": item.get("company", "Unknown"),
        "title": item.get("positionName", item.get("title", "")),
        "location": location,
        "country": _guess_country(location),
        "remote_type": _detect_remote(item),
        "job_url": item.get("url", item.get("externalUrl", "")),
        "salary_text": salary_text or None,
        "salary_min": salary_min,
        "salary_max": salary_max,
        "raw_description": item.get("description", ""),
        "posted_at": item.get("postedAt", item.get("scrapedAt")),
    }


def normalize_google_jobs(item: dict) -> dict:
    """Normalize a Google Jobs Scraper result."""
    location = item.get("location", "")

    return {
        "external_id": str(item.get("job_id", item.get("id", ""))),
        "source_name": "google_jobs",
        "source_type": "apify",
        "company": item.get("company_name", item.get("company", "Unknown")),
        "title": item.get("title", ""),
        "location": location,
        "country": _guess_country(location),
        "remote_type": _detect_remote(item),
        "job_url": item.get("apply_link", item.get("share_link", "")),
        "apply_url": item.get("apply_link", ""),
        "salary_text": item.get("salary", ""),
        "raw_description": item.get("description", ""),
        "posted_at": item.get("date_posted"),
        "employment_type": item.get("schedule_type"),
    }


# Mapping from Apify actor names to normalizer functions
ACTOR_NORMALIZERS = {
    "linkedin": normalize_linkedin_job,
    "indeed": normalize_indeed_job,
    "google": normalize_google_jobs,
}


def _guess_country(location: str) -> str | None:
    """Guess country code from location string."""
    if not location:
        return None
    loc = location.lower()
    # US states
    us_indicators = [", ca", ", ny", ", tx", ", wa", ", ma", "united states", ", usa"]
    if any(ind in loc for ind in us_indicators):
        return "US"
    if "canada" in loc or ", on" in loc or ", bc" in loc:
        return "CA"
    if "uk" in loc or "united kingdom" in loc or "london" in loc:
        return "GB"
    if "germany" in loc or "berlin" in loc or "munich" in loc:
        return "DE"
    if "france" in loc or "paris" in loc:
        return "FR"
    if "netherlands" in loc or "amsterdam" in loc:
        return "NL"
    return None


def _detect_remote(item: dict) -> str | None:
    """Detect remote type from an Apify result."""
    # Check various field names used by different actors
    for field in ["workType", "workplaceType", "jobType", "remote"]:
        val = str(item.get(field, "")).lower()
        if "remote" in val:
            return "full_remote"
        if "hybrid" in val:
            return "hybrid"
        if "on-site" in val or "onsite" in val:
            return "onsite"

    # Check title/location for hints
    title = (item.get("title", "") or "").lower()
    location = (item.get("location", "") or "").lower()
    if "remote" in title or "remote" in location:
        return "full_remote"

    return None
