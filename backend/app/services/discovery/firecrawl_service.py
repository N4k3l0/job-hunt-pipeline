import logging

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

FIRECRAWL_BASE = "https://api.firecrawl.dev/v1"


async def scrape_url(url: str) -> str:
    """Scrape a URL using Firecrawl and return clean markdown content."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{FIRECRAWL_BASE}/scrape",
            headers={
                "Authorization": f"Bearer {settings.firecrawl_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "url": url,
                "formats": ["markdown"],
            },
        )
        response.raise_for_status()
        data = response.json()

    content = data.get("data", {}).get("markdown", "")
    if not content:
        raise ValueError(f"No content extracted from {url}")

    logger.info("Scraped %d characters from %s", len(content), url)
    return content


async def scrape_html(url: str, *, timeout: float = 25.0) -> str:
    """Same as scrape_url but returns raw HTML instead of markdown.

    Used for sources whose data lives in structured tags (JSON-LD,
    inline JSON state, microdata) rather than visible text — converting
    to markdown destroys those. DailyRemote's JobPosting JSON-LD is the
    main caller.

    Returns the empty string on any failure so callers can gracefully
    skip the page rather than tear down the whole batch.
    """
    if not settings.firecrawl_api_key:
        logger.warning("Firecrawl key not configured")
        return ""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{FIRECRAWL_BASE}/scrape",
                headers={
                    "Authorization": f"Bearer {settings.firecrawl_api_key}",
                    "Content-Type": "application/json",
                },
                json={"url": url, "formats": ["rawHtml"]},
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as e:
        logger.warning("Firecrawl scrape_html failed for %s: %s", url, e)
        return ""
    return (data.get("data") or {}).get("rawHtml", "") or ""
