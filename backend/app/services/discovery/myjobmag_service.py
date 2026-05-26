"""MyJobMag (myjobmag.com) — second-largest Nigerian job board.

Raw HTML on /jobs is a JS shell — job links don't appear without
client-side rendering. Routes through Firecrawl which renders the
page before returning markdown.

Strategy mirrors arcdev_service / wellfound_service:
1. Scrape a couple of category listing pages (markdown) via Firecrawl
2. Regex-extract /job-vacancy/<slug> links from the markdown
3. Cap at max_detail_fetches detail pages per run
4. Detail pages are also scraped via Firecrawl

Per-run cost: ~10 Firecrawl credits (~$0.03) when active. Skipped
gracefully if FIRECRAWL_API_KEY is missing.
"""

from __future__ import annotations

import logging
import re

from app.services.discovery.firecrawl_service import scrape_url

logger = logging.getLogger(__name__)

MYJOBMAG_BASE = "https://www.myjobmag.com"

# Profession-bucketed listing URLs. MyJobMag has many fields; these two
# cover the most-active categories. Add more here if specific users
# need niche bucket coverage.
MYJOBMAG_LISTING_URLS = (
    "https://www.myjobmag.com/jobs",
    "https://www.myjobmag.com/jobs-by-field/it-telecoms",
)

# Markdown link patterns. MyJobMag uses /job-vacancy/<numeric>/<slug>
# or /jobs/<id> depending on the section.
JOB_LINK_RE = re.compile(
    r"\[([^\]]+)\]\((https://www\.myjobmag\.com/(?:job-vacancy|jobs)/\d+[/\-\w]*)\)",
    re.I,
)

TITLE_HEADING_RE = re.compile(r"^#\s+(.+)$", re.M)
COMPANY_LABEL_RE = re.compile(
    r"(?:^|\n)\s*(?:Company|Employer|Recruiter)\s*[:\-]\s*([^\n]+)",
    re.I,
)
LOCATION_LABEL_RE = re.compile(
    r"(?:^|\n)\s*(?:Location|City|Based in)\s*[:\-]\s*([^\n]+)",
    re.I,
)


async def fetch_jobs(
    keywords: set[str] | None = None,
    max_detail_fetches: int = 10,
    skip_urls: set[str] | None = None,
) -> list[dict]:
    """Walk MyJobMag listing pages via Firecrawl, pull a small batch
    of detail pages. `keywords` accepted for interface parity but the
    whole catalog is Nigeria-local — per-user inbox filter handles
    role matching downstream."""
    skip_urls = skip_urls or set()
    seen: set[str] = set()
    candidates: list[tuple[str, str]] = []

    for listing_url in MYJOBMAG_LISTING_URLS:
        try:
            md = await scrape_url(listing_url)
        except Exception as e:
            logger.warning("MyJobMag listing fetch failed for %s: %s", listing_url, e)
            continue
        for title, url in JOB_LINK_RE.findall(md):
            cleaned = url.split("?")[0].split("#")[0].rstrip("/")
            if cleaned in seen or cleaned in skip_urls:
                continue
            seen.add(cleaned)
            candidates.append((title.strip(), cleaned))

    logger.info("MyJobMag: %d unique candidate listings across %d pages",
                len(candidates), len(MYJOBMAG_LISTING_URLS))

    if len(candidates) > max_detail_fetches:
        candidates = candidates[:max_detail_fetches]

    jobs: list[dict] = []
    for title, url in candidates:
        try:
            detail_md = await scrape_url(url)
        except Exception as e:
            logger.warning("MyJobMag detail fetch failed for %s: %s", url, e)
            continue
        normalized = _parse_detail(title=title, url=url, markdown=detail_md)
        if normalized:
            jobs.append(normalized)

    logger.info("MyJobMag: %d jobs ingested", len(jobs))
    return jobs


def _parse_detail(*, title: str, url: str, markdown: str) -> dict | None:
    if not markdown or len(markdown) < 200:
        return None

    heading_m = TITLE_HEADING_RE.search(markdown)
    page_title = heading_m.group(1).strip() if heading_m else title

    company_m = COMPANY_LABEL_RE.search(markdown)
    company = company_m.group(1).strip(" *_•")[:80] if company_m else "Unknown"

    location_m = LOCATION_LABEL_RE.search(markdown)
    location = location_m.group(1).strip(" *_•")[:120] if location_m else "Nigeria"

    slug = url.rstrip("/").split("/")[-1] or url

    return {
        "external_id": slug,
        "source_name": "myjobmag",
        "source_type": "scraper",
        "company": company,
        "title": page_title,
        "location": location,
        "country": "NG",
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
