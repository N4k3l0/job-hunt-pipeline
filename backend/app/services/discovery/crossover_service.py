"""Crossover (crossover.com) — full-time remote placement firm.

Crossover is itself the employer; their catalog is small (dozens of roles, not
thousands) and explicitly hires from 130+ countries including Nigeria, with
USD pay. No public API or RSS — we scrape via Firecrawl.

Strategy:
1. Scrape the listing page once → extract job URLs from the markdown
2. For each URL, scrape the detail page → parse title / description / salary
3. Cap per-run cost: skip jobs already in our DB so we don't re-scrape every run

This intentionally pulls a small batch per run (max ~30 detail fetches) so a
single discovery run stays under ~$0.05 in Firecrawl credits.
"""

from __future__ import annotations

import logging
import re

from app.services.discovery.firecrawl_service import scrape_url
from app.services.discovery.eligibility import matches_keywords

logger = logging.getLogger(__name__)

CROSSOVER_LISTING_URL = "https://www.crossover.com/jobs"
USD_PER_HOUR_RE = re.compile(r"\$?(\d{2,3})(?:\.\d+)?\s*/?\s*(?:per\s+)?(?:hour|hr)", re.I)
TITLE_HEADING_RE = re.compile(r"^#\s+(.+)$", re.M)
# Listing page markdown will contain links like [Title](https://www.crossover.com/jobs/<slug>).
JOB_LINK_RE = re.compile(
    r"\[([^\]]+)\]\((https://www\.crossover\.com/jobs/[a-z0-9\-_/]+)\)",
    re.I,
)


async def fetch_jobs(
    keywords: set[str] | None = None,
    max_detail_fetches: int = 30,
    skip_urls: set[str] | None = None,
) -> list[dict]:
    """Discover Crossover roles and pull detail for the most relevant ones.

    Args:
        keywords: substring keywords to filter titles on. If None, returns all.
        max_detail_fetches: hard cap on per-job page scrapes per run.
        skip_urls: URLs already in our DB — we skip re-scraping them.
    """
    skip_urls = skip_urls or set()

    try:
        listing_markdown = await scrape_url(CROSSOVER_LISTING_URL)
    except Exception as e:
        logger.error("Crossover listing scrape failed: %s", e)
        return []

    # Extract unique (title, url) pairs from the listing markdown.
    seen: set[str] = set()
    candidates: list[tuple[str, str]] = []
    for title, url in JOB_LINK_RE.findall(listing_markdown):
        url = url.split("?")[0].split("#")[0].rstrip("/")
        if url in seen or url in skip_urls:
            continue
        # Skip the listing page itself + obvious non-job links.
        if url == CROSSOVER_LISTING_URL.rstrip("/"):
            continue
        seen.add(url)
        candidates.append((title.strip(), url))

    logger.info("Crossover: %d unique candidate listings on landing page", len(candidates))

    # Pre-filter by keywords *before* spending credits on detail fetches.
    if keywords:
        candidates = [
            (t, u) for t, u in candidates
            if matches_keywords(t, keywords)
        ]
        logger.info("Crossover: %d candidates after keyword filter", len(candidates))

    # Cap detail fetches.
    if len(candidates) > max_detail_fetches:
        candidates = candidates[:max_detail_fetches]

    jobs: list[dict] = []
    for title, url in candidates:
        try:
            detail_md = await scrape_url(url)
        except Exception as e:
            logger.warning("Crossover detail scrape failed for %s: %s", url, e)
            continue
        normalized = _parse_detail(title=title, url=url, markdown=detail_md)
        if normalized:
            jobs.append(normalized)

    logger.info("Crossover: %d jobs ingested", len(jobs))
    return jobs


def _parse_detail(*, title: str, url: str, markdown: str) -> dict | None:
    """Turn a Firecrawl markdown blob into our raw-job dict."""
    if not markdown or len(markdown) < 200:
        return None

    # Prefer the H1 from the page itself; fall back to the listing-link title.
    heading = TITLE_HEADING_RE.search(markdown)
    page_title = heading.group(1).strip() if heading else title

    # Salary heuristic: Crossover always quotes USD/hour rates. Convert to
    # annual ranges using a 40h * 52w = 2080 multiplier.
    salary_min = salary_max = None
    rates = USD_PER_HOUR_RE.findall(markdown)
    if rates:
        ints = sorted({int(r) for r in rates})
        if len(ints) >= 2:
            salary_min = ints[0] * 2080
            salary_max = ints[-1] * 2080
        elif ints:
            salary_min = salary_max = ints[0] * 2080

    salary_text = None
    if salary_min and salary_max:
        if salary_min == salary_max:
            salary_text = f"${salary_min // 1000}K USD/yr"
        else:
            salary_text = f"${salary_min // 1000}K — ${salary_max // 1000}K USD/yr"

    # Slug = last path segment, used as external_id.
    slug = url.rstrip("/").split("/")[-1] or url

    return {
        "external_id": slug,
        "source_name": "crossover",
        "source_type": "scraper",
        "company": "Crossover",
        "title": page_title,
        "location": "Worldwide",
        "country": None,
        "remote_type": "full_remote",
        "job_url": url,
        "apply_url": url,
        "salary_text": salary_text,
        "salary_min": salary_min,
        "salary_max": salary_max,
        "salary_currency": "USD" if salary_min else None,
        "raw_description": markdown,
        "tags": [],
    }
