import logging

import httpx

logger = logging.getLogger(__name__)

ARBEITNOW_API = "https://www.arbeitnow.com/api/job-board-api"

async def fetch_jobs(
    visa_sponsorship: bool = False,
    max_pages: int = 3,
    keywords: set[str] | None = None,
) -> list[dict]:
    """Fetch European jobs from Arbeitnow API.

    Args:
        visa_sponsorship: If True, only return jobs with visa sponsorship
        max_pages: Max pages to fetch

    Returns:
        List of normalized job dicts
    """
    all_jobs = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        for page in range(1, max_pages + 1):
            params = {"page": page}
            if visa_sponsorship:
                params["visa_sponsorship"] = "true"

            try:
                response = await client.get(ARBEITNOW_API, params=params)
                response.raise_for_status()
                data = response.json()

                jobs_raw = data.get("data", [])
                if not jobs_raw:
                    break

                for item in jobs_raw:
                    # Filter by keywords
                    title = (item.get("title", "") or "").lower()
                    description = (item.get("description", "") or "").lower()
                    tags = " ".join(t.lower() for t in (item.get("tags", []) or []))
                    searchable = f"{title} {description} {tags}"

                    filter_kw = keywords or {"product manager", "ai automation", "automation engineer"}
                    if any(kw in searchable for kw in filter_kw):
                        all_jobs.append(_normalize_arbeitnow_result(item))

                logger.info("Arbeitnow page %d: %d raw results", page, len(jobs_raw))

                # Check if there are more pages
                if not data.get("links", {}).get("next"):
                    break

            except httpx.HTTPError as e:
                logger.error("Arbeitnow API error: %s", e)
                break

    logger.info("Arbeitnow total: %d matched jobs", len(all_jobs))
    return all_jobs


def _normalize_arbeitnow_result(item: dict) -> dict:
    """Normalize an Arbeitnow API result."""
    location = item.get("location", "")

    # Arbeitnow is Europe-focused, try to determine country
    country = None
    if location:
        location_lower = location.lower()
        country_hints = {
            "germany": "DE", "berlin": "DE", "munich": "DE", "hamburg": "DE",
            "france": "FR", "paris": "FR",
            "netherlands": "NL", "amsterdam": "NL",
            "austria": "AT", "vienna": "AT",
            "switzerland": "CH", "zurich": "CH",
            "uk": "GB", "london": "GB",
            "ireland": "IE", "dublin": "IE",
            "spain": "ES", "barcelona": "ES", "madrid": "ES",
            "sweden": "SE", "stockholm": "SE",
            "denmark": "DK", "copenhagen": "DK",
        }
        for hint, code in country_hints.items():
            if hint in location_lower:
                country = code
                break

    remote_type = None
    if item.get("remote", False):
        remote_type = "full_remote"

    return {
        "external_id": str(item.get("slug", "")),
        "source_name": "arbeitnow",
        "source_type": "api",
        "company": item.get("company_name", "Unknown"),
        "title": item.get("title", ""),
        "location": location,
        "country": country,
        "remote_type": remote_type,
        "job_url": item.get("url", ""),
        "raw_description": item.get("description", ""),
        "posted_at": item.get("created_at"),
        "tags": item.get("tags", []),
        "visa_sponsorship": item.get("visa_sponsorship", False),
    }
