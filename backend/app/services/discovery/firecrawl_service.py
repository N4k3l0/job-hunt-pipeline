import logging

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

FIRECRAWL_BASE = "https://api.firecrawl.dev/v1"


async def scrape_url(url: str) -> str:
    """Scrape a URL using Firecrawl and return clean markdown content.

    Args:
        url: The URL to scrape

    Returns:
        Clean markdown text of the page content
    """
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
