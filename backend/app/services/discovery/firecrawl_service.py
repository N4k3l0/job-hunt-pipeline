"""Fetching job board pages.

Pages are fetched directly first, with a user agent that says who we are.
Most boards serve them as they would to anyone. Firecrawl is only the
fallback for a page that doesn't come back, and it's paused for a while
after it says "too many requests": once its credits run out, asking again
for every page just fills the logs and wastes the run.

A site that blocks direct requests or asks visitors to prove they're human
is left to Firecrawl, never worked around here.
"""

import logging
import re
import time
from urllib.parse import urlsplit

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

FIRECRAWL_BASE = "https://api.firecrawl.dev/v1"
USER_AGENT = "Mozilla/5.0 (compatible; JobHuntPipeline/1.0; +job-discovery)"
DIRECT_TIMEOUT = 20.0
# Below this a 200 is an error page or an empty shell, not a job page.
MIN_PAGE_CHARS = 2000
FIRECRAWL_PAUSE_SECONDS = 60 * 60

_firecrawl_paused_until = 0.0

_SCRIPT_OR_STYLE = re.compile(r"<(script|style|noscript|svg)\b[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_ROOT_RELATIVE_HREF = re.compile(r'(\bhref=")(/(?!/)[^"]*)"', re.IGNORECASE)


async def _direct_html(url: str, timeout: float = DIRECT_TIMEOUT) -> str:
    """The page as the site serves it, or "" if it didn't come back."""
    try:
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=True, headers={"User-Agent": USER_AGENT},
        ) as client:
            response = await client.get(url)
    except (httpx.HTTPError, OSError) as e:  # OSError covers a dropped TLS connection
        logger.info("Direct fetch failed for %s: %s", url, type(e).__name__)
        return ""
    if response.status_code != 200 or len(response.text) < MIN_PAGE_CHARS:
        logger.info("Direct fetch of %s answered %s", url, response.status_code)
        return ""
    return response.text


def html_to_markdown(html: str, url: str) -> str:
    """Markdown in the shape the source parsers read: headings as #, links
    as [text](absolute url)."""
    from markdownify import markdownify

    parts = urlsplit(url)
    base = f"{parts.scheme}://{parts.netloc}"
    html = _SCRIPT_OR_STYLE.sub("", html)
    html = _ROOT_RELATIVE_HREF.sub(lambda m: f'{m.group(1)}{base}{m.group(2)}"', html)
    markdown = markdownify(html, heading_style="ATX")
    return re.sub(r"\n{3,}", "\n\n", markdown).strip()


def _firecrawl_available() -> bool:
    return bool(settings.firecrawl_api_key) and time.monotonic() >= _firecrawl_paused_until


def _pause_firecrawl() -> None:
    global _firecrawl_paused_until
    if time.monotonic() >= _firecrawl_paused_until:
        logger.warning("Firecrawl said too many requests: not using it for the next hour")
    _firecrawl_paused_until = time.monotonic() + FIRECRAWL_PAUSE_SECONDS


async def _firecrawl(url: str, fmt: str, timeout: float) -> str:
    """One Firecrawl scrape in `fmt` ("markdown" or "rawHtml"), or ""."""
    if not _firecrawl_available():
        return ""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{FIRECRAWL_BASE}/scrape",
                headers={
                    "Authorization": f"Bearer {settings.firecrawl_api_key}",
                    "Content-Type": "application/json",
                },
                json={"url": url, "formats": [fmt]},
            )
        if response.status_code == 429:
            _pause_firecrawl()
            return ""
        response.raise_for_status()
        return (response.json().get("data") or {}).get(fmt, "") or ""
    except httpx.HTTPError as e:
        logger.warning("Firecrawl failed for %s: %s", url, e)
        return ""


async def scrape_url(url: str) -> str:
    """The page as markdown. Raises ValueError when it can't be fetched."""
    html = await _direct_html(url)
    if html:
        content = html_to_markdown(html, url)
    else:
        content = await _firecrawl(url, "markdown", timeout=60.0)
    if not content:
        raise ValueError(f"No content extracted from {url}")
    logger.info("Scraped %d characters from %s", len(content), url)
    return content


async def scrape_html(url: str, *, timeout: float = 25.0) -> str:
    """The page's raw HTML, for sources whose data lives in structured tags
    (JSON-LD, inline JSON) that markdown would lose. "" on failure, so a
    caller can skip one page without dropping the batch."""
    html = await _direct_html(url, timeout=timeout)
    if html:
        return html
    return await _firecrawl(url, "rawHtml", timeout=timeout)
