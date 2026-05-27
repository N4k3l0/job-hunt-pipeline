"""Undutchables — Netherlands-focused multilingual recruiter.

Undutchables places international (non-Dutch-speaking) candidates into
roles across the Netherlands. They post directly on their own site and
do NOT syndicate to LinkedIn / Indeed under their own brand for most
listings, which is why we scrape them separately rather than relying
on the existing aggregators.

Strategy mirrors `crossover_service.py`:
1. Scrape the listings index in markdown (one Firecrawl credit)
2. Regex-extract (title, URL) pairs from the index
3. Optionally filter by keywords before spending detail credits
4. For each surviving candidate (capped), fetch the detail page and
   parse title / city / description out of the markdown

The actual client company on most Undutchables postings is masked
("our client is a fast-growing fintech in Amsterdam") so we record
the employer as `Undutchables` in the company field — users still see
the role + city + responsibilities, which is enough for scoring.
"""

from __future__ import annotations

import logging
import re

from app.services.discovery.firecrawl_service import scrape_url
from app.services.discovery.eligibility import matches_keywords

logger = logging.getLogger(__name__)

UNDUTCHABLES_LISTING_URL = "https://www.undutchables.nl/job-vacancies/"

# Listing markdown contains links like:
#   [Some Job Title](https://www.undutchables.nl/vacancy/<slug>/)
# We accept both `/vacancy/` and `/job-vacancies/<slug>` shapes since the
# site has used both over time and a future redesign shouldn't silently
# starve the scraper.
JOB_LINK_RE = re.compile(
    r"\[([^\]]+)\]\((https://www\.undutchables\.nl/(?:vacancy|vacatures|job-vacancies)/[a-z0-9\-_/]+)\)",
    re.I,
)

TITLE_HEADING_RE = re.compile(r"^#\s+(.+)$", re.M)

# Dutch cities we expect to see in postings. Used to fish a location out
# of the detail markdown when the page doesn't surface a structured field.
DUTCH_CITY_RE = re.compile(
    r"\b(Amsterdam|Rotterdam|The Hague|Den Haag|Utrecht|Eindhoven|Groningen|"
    r"Tilburg|Almere|Breda|Nijmegen|Apeldoorn|Haarlem|Arnhem|Enschede|"
    r"Amersfoort|Zaanstad|'s-Hertogenbosch|Den Bosch|Maastricht|Leiden|"
    r"Dordrecht|Zoetermeer|Zwolle|Deventer|Delft|Hilversum|Hoofddorp|"
    r"Diemen|Amstelveen|Schiphol)\b",
    re.I,
)


async def fetch_jobs(
    keywords: set[str] | None = None,
    max_detail_fetches: int = 12,
    skip_urls: set[str] | None = None,
) -> list[dict]:
    """Discover Undutchables vacancies and pull detail markdown.

    Args:
        keywords: substring keywords to pre-filter titles. None = take all.
        max_detail_fetches: hard cap on per-job page scrapes per run.
        skip_urls: URLs already in our DB — we skip re-scraping them.
    """
    skip_urls = skip_urls or set()

    try:
        listing_markdown = await scrape_url(UNDUTCHABLES_LISTING_URL)
    except Exception as e:
        logger.error("Undutchables listing scrape failed: %s", e)
        return []

    # Extract unique (title, url) pairs from the listing markdown.
    seen: set[str] = set()
    candidates: list[tuple[str, str]] = []
    for title, url in JOB_LINK_RE.findall(listing_markdown):
        url = url.split("?")[0].split("#")[0].rstrip("/")
        if url in seen or url in skip_urls:
            continue
        if url.rstrip("/") == UNDUTCHABLES_LISTING_URL.rstrip("/"):
            continue
        seen.add(url)
        candidates.append((title.strip(), url))

    logger.info(
        "Undutchables: %d unique candidate listings on landing page",
        len(candidates),
    )
    if not candidates:
        # Diagnostic: log a slice of the markdown so we can see what
        # Firecrawl actually returned when the regex fails to match.
        preview = (listing_markdown or "")[:600].replace("\n", " ")
        logger.warning(
            "Undutchables: regex matched 0 listings (markdown length=%d). Preview: %s",
            len(listing_markdown or ""), preview,
        )

    # Pre-filter by keywords *before* spending Firecrawl credits.
    if keywords:
        candidates = [
            (t, u) for t, u in candidates
            if matches_keywords(t, keywords)
        ]
        logger.info(
            "Undutchables: %d candidates after keyword filter", len(candidates)
        )

    if len(candidates) > max_detail_fetches:
        candidates = candidates[:max_detail_fetches]

    jobs: list[dict] = []
    for title, url in candidates:
        try:
            detail_md = await scrape_url(url)
        except Exception as e:
            logger.warning("Undutchables detail scrape failed for %s: %s", url, e)
            continue
        normalized = _parse_detail(title=title, url=url, markdown=detail_md)
        if normalized:
            jobs.append(normalized)

    logger.info("Undutchables: %d jobs ingested", len(jobs))
    return jobs


def _parse_detail(*, title: str, url: str, markdown: str) -> dict | None:
    """Turn a Firecrawl markdown blob into our raw-job dict."""
    if not markdown or len(markdown) < 200:
        return None

    # Prefer the H1 from the page itself; fall back to the listing-link title.
    heading = TITLE_HEADING_RE.search(markdown)
    page_title = heading.group(1).strip() if heading else title

    # Try to fish a city out of the detail page so the scorer's geo path
    # has something to work with. Default to a generic NL label.
    city = None
    city_match = DUTCH_CITY_RE.search(markdown)
    if city_match:
        city = city_match.group(1)
    location = f"{city}, Netherlands" if city else "Netherlands"

    # Slug = last path segment, used as external_id (URL is also unique
    # enough but the slug is shorter & survives query-string churn).
    slug = url.rstrip("/").split("/")[-1] or url

    return {
        "external_id": slug,
        "source_name": "undutchables",
        "source_type": "scraper",
        # Undutchables masks the underlying employer in most postings.
        # Recording 'Undutchables' makes it obvious in the inbox that
        # this is a recruiter listing, not a direct-hire opening.
        "company": "Undutchables",
        "title": page_title,
        "location": location,
        "country": "NL",
        # Most Undutchables roles are onsite / hybrid in NL. We mark as
        # 'unknown' so the geo scorer treats them as country-bound rather
        # than as remote-anywhere (which would mismatch users targeting
        # remote-only work).
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
