"""Arc.dev (arc.dev/remote-jobs) — JS-rendered listings via Firecrawl.

Arc.dev is a dev/engineering-focused remote job board. Their category
pages (e.g. /remote-jobs/ai, /remote-jobs/agentic-frameworks,
/remote-jobs/automation) map cleanly to the AI Eng user profile this
pipeline exists to serve.

Strategy:
1. For each targeted category, scrape the listing markdown via
   Firecrawl (JS-rendered) — one credit per category.
2. Regex-extract individual job URLs from the markdown.
3. For each (capped), fetch the detail page via Firecrawl and parse
   title / company / location / description.

Per-run cost target: ~5 categories × (1 listing + 6 details) = ~35
Firecrawl credits, roughly $0.10 / run.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

from app.services.discovery.firecrawl_service import scrape_url

logger = logging.getLogger(__name__)

ARC_BASE = "https://arc.dev"

# Categories we target — biased toward AI / automation / engineering
# roles. Each one is one listing-page scrape per run.
ARC_CATEGORIES = (
    "ai",
    "agentic-frameworks",
    "automation",
    "machine-learning",
    "llm",
)

# Arc renders individual job links as /remote-jobs/c/<slug> or
# /remote-jobs/<numeric-id>/<slug>. We accept both.
JOB_LINK_RE = re.compile(
    r"\[([^\]]+)\]\((https://arc\.dev/remote-jobs/(?:c/[\w\-_/]+|\d+/[\w\-_/]+))\)",
    re.I,
)

TITLE_HEADING_RE = re.compile(r"^#\s+(.+)$", re.M)
COMPANY_LABEL_RE = re.compile(
    r"(?:^|\n)\s*(?:Company|Hiring|Employer)\s*[:\-]\s*([^\n]+)",
    re.I,
)


async def fetch_jobs(
    keywords: set[str] | None = None,
    max_detail_fetches: int = 8,
    skip_urls: set[str] | None = None,
) -> list[dict]:
    """Walk the target categories, pull a small batch of detail pages
    per run."""
    skip_urls = skip_urls or set()
    seen: set[str] = set()
    candidates: list[tuple[str, str]] = []

    for category in ARC_CATEGORIES:
        listing_url = f"{ARC_BASE}/remote-jobs/{category}"
        try:
            md = await scrape_url(listing_url)
        except Exception as e:
            logger.warning("Arc.dev listing scrape failed for %s: %s", category, e)
            continue
        for title, url in JOB_LINK_RE.findall(md):
            cleaned = url.split("?")[0].split("#")[0].rstrip("/")
            if cleaned in seen or cleaned in skip_urls:
                continue
            seen.add(cleaned)
            candidates.append((title.strip(), cleaned))

    logger.info("Arc.dev: %d unique candidate listings across %d categories",
                len(candidates), len(ARC_CATEGORIES))

    if len(candidates) > max_detail_fetches:
        candidates = candidates[:max_detail_fetches]

    jobs: list[dict] = []
    for title, url in candidates:
        try:
            detail_md = await scrape_url(url)
        except Exception as e:
            logger.warning("Arc.dev detail scrape failed for %s: %s", url, e)
            continue
        normalized = _parse_detail(title=title, url=url, markdown=detail_md)
        if normalized:
            jobs.append(normalized)

    logger.info("Arc.dev: %d jobs ingested", len(jobs))
    return jobs


def _parse_detail(*, title: str, url: str, markdown: str) -> dict | None:
    if not markdown or len(markdown) < 200:
        return None

    heading = TITLE_HEADING_RE.search(markdown)
    page_title = heading.group(1).strip() if heading else title

    company_match = COMPANY_LABEL_RE.search(markdown)
    company = company_match.group(1).strip(" *_•")[:80] if company_match else "Unknown"

    slug = url.rstrip("/").split("/")[-1] or url

    return {
        "external_id": slug,
        "source_name": "arcdev",
        "source_type": "scraper",
        "company": company,
        "title": page_title,
        "location": "Remote",
        "country": None,
        # Arc.dev curates remote-only listings.
        "remote_type": "full_remote",
        "job_url": url,
        "apply_url": url,
        "salary_text": None,
        "salary_min": None,
        "salary_max": None,
        "salary_currency": None,
        "raw_description": markdown,
        "tags": [],
    }
