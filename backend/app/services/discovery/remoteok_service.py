import logging

import httpx

logger = logging.getLogger(__name__)

REMOTEOK_API = "https://remoteok.com/api"

# Keywords to filter by
PM_KEYWORDS = {"product manager", "product lead", "product owner", "pm"}
AI_KEYWORDS = {"ai", "automation", "machine learning", "ml", "llm", "artificial intelligence"}


async def fetch_jobs(keywords: set[str] | None = None) -> list[dict]:
    """Fetch remote jobs from RemoteOK API.

    The API returns all recent jobs; we filter client-side by keywords.

    Returns:
        List of normalized job dicts matching keywords
    """
    keywords = keywords or PM_KEYWORDS | AI_KEYWORDS

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            REMOTEOK_API,
            headers={"User-Agent": "JobHuntPipeline/1.0"},
        )
        response.raise_for_status()
        data = response.json()

    # First element is metadata, skip it
    jobs_raw = data[1:] if isinstance(data, list) and len(data) > 1 else []

    # Filter by keywords
    matched = []
    for item in jobs_raw:
        title = (item.get("position", "") or "").lower()
        company = (item.get("company", "") or "").lower()
        tags = [t.lower() for t in (item.get("tags", []) or [])]
        description = (item.get("description", "") or "").lower()

        searchable = f"{title} {company} {' '.join(tags)} {description}"
        if any(kw in searchable for kw in keywords):
            matched.append(_normalize_remoteok_result(item))

    logger.info("RemoteOK: %d matched jobs out of %d total", len(matched), len(jobs_raw))
    return matched


def _normalize_remoteok_result(item: dict) -> dict:
    """Normalize a RemoteOK API result."""
    salary_min = None
    salary_max = None
    salary_text = item.get("salary", "")

    # RemoteOK sometimes includes salary as a string
    if salary_text:
        # Try to parse "100k-150k" format
        import re
        match = re.findall(r"(\d+)k", salary_text.lower())
        if len(match) >= 2:
            salary_min = int(match[0]) * 1000
            salary_max = int(match[1]) * 1000
        elif len(match) == 1:
            salary_min = int(match[0]) * 1000

    return {
        "external_id": str(item.get("id", "")),
        "source_name": "remoteok",
        "source_type": "api",
        "company": item.get("company", "Unknown"),
        "title": item.get("position", ""),
        "location": item.get("location", "Remote"),
        "country": None,  # RemoteOK doesn't reliably provide country
        "remote_type": "full_remote",
        "job_url": item.get("url", ""),
        "apply_url": item.get("apply_url", ""),
        "salary_text": salary_text or None,
        "salary_min": salary_min,
        "salary_max": salary_max,
        "salary_currency": "USD",
        "raw_description": item.get("description", ""),
        "posted_at": item.get("date"),
        "tags": item.get("tags", []),
    }
