"""Wellfound (wellfound.com, formerly AngelList) — startup job board.

Wellfound serves startup and growth-stage company roles, often with
direct apply (no middleman). Their site 403s plain HTTP fetches (anti-
bot) so we route through Firecrawl which handles the JS render +
fingerprint.

Strategy:
1. Scrape the discover page for our target role themes (engineering,
   ML, AI). Each role is a separate listing-page scrape per run.
2. Regex-extract individual job-detail URLs from the rendered markdown.
3. For each (capped), scrape detail and parse the page.

Per-run cost target: ~3 role queries × (1 listing + 5 details) =
~18 Firecrawl credits / run, roughly $0.05.
"""

from __future__ import annotations

import logging
import re

from app.services.discovery.firecrawl_service import scrape_url

logger = logging.getLogger(__name__)

WELLFOUND_BASE = "https://wellfound.com"

# Discover-page role themes. Wellfound's URL structure for filtered
# discovery is /role/r/<role-slug>.
WELLFOUND_ROLES = (
    "ai-engineer",
    "machine-learning-engineer",
    "software-engineer",
)

# Individual job postings live at /jobs/<numeric-id>-<slug>.
JOB_LINK_RE = re.compile(
    r"\[([^\]]+)\]\((https://wellfound\.com/jobs/\d+[-\w]*)\)",
    re.I,
)

TITLE_HEADING_RE = re.compile(r"^#\s+(.+)$", re.M)
COMPANY_LABEL_RE = re.compile(
    r"(?:^|\n)\s*(?:Company|Hiring|Employer|at)\s*[:\-]\s*\[?([^\n\]]+)",
    re.I,
)
LOCATION_LABEL_RE = re.compile(
    r"(?:^|\n)\s*(?:Location|Office|Where|Based in)\s*[:\-]\s*([^\n]+)",
    re.I,
)


async def fetch_jobs(
    keywords: set[str] | None = None,
    max_detail_fetches: int = 6,
    skip_urls: set[str] | None = None,
) -> list[dict]:
    """Walk a few role themes, pull a small batch of detail pages."""
    skip_urls = skip_urls or set()
    seen: set[str] = set()
    candidates: list[tuple[str, str]] = []

    for role in WELLFOUND_ROLES:
        listing_url = f"{WELLFOUND_BASE}/role/r/{role}"
        try:
            md = await scrape_url(listing_url)
        except Exception as e:
            logger.warning("Wellfound listing scrape failed for %s: %s", role, e)
            continue
        for title, url in JOB_LINK_RE.findall(md):
            cleaned = url.split("?")[0].split("#")[0].rstrip("/")
            if cleaned in seen or cleaned in skip_urls:
                continue
            seen.add(cleaned)
            candidates.append((title.strip(), cleaned))

    logger.info("Wellfound: %d unique candidate listings across %d roles",
                len(candidates), len(WELLFOUND_ROLES))

    if len(candidates) > max_detail_fetches:
        candidates = candidates[:max_detail_fetches]

    jobs: list[dict] = []
    for title, url in candidates:
        try:
            detail_md = await scrape_url(url)
        except Exception as e:
            logger.warning("Wellfound detail scrape failed for %s: %s", url, e)
            continue
        normalized = _parse_detail(title=title, url=url, markdown=detail_md)
        if normalized:
            jobs.append(normalized)

    logger.info("Wellfound: %d jobs ingested", len(jobs))
    return jobs


def _parse_detail(*, title: str, url: str, markdown: str) -> dict | None:
    if not markdown or len(markdown) < 200:
        return None

    heading = TITLE_HEADING_RE.search(markdown)
    page_title = heading.group(1).strip() if heading else title

    company_match = COMPANY_LABEL_RE.search(markdown)
    company = "Unknown"
    if company_match:
        company = company_match.group(1).strip(" *_•[]")[:80] or "Unknown"

    location_match = LOCATION_LABEL_RE.search(markdown)
    location = "Remote"
    if location_match:
        location = location_match.group(1).strip(" *_•")[:120] or "Remote"

    slug_parts = url.rstrip("/").split("/")
    slug = slug_parts[-1] if slug_parts else url

    return {
        "external_id": slug,
        "source_name": "wellfound",
        "source_type": "scraper",
        "company": company,
        "title": page_title,
        "location": location,
        "country": None,
        # Wellfound mixes remote / hybrid / onsite — let the normalizer
        # downstream classify from the location string.
        "remote_type": "unknown",
        "job_url": url,
        "apply_url": url,
        "salary_text": None,
        "salary_min": None,
        "salary_max": None,
        "salary_currency": None,
        "raw_description": markdown,
        "tags": [],
    }
