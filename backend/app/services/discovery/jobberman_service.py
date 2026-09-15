"""Jobberman (jobberman.com) — Nigeria's largest job board.

Plain httpx scrape — Jobberman's listing pages serve job links in raw
HTML (no JS rendering required). Each /jobs page lists ~16 jobs with
direct anchors to /listings/<slug-id>. We scrape a small batch of
listing pages, regex-extract URLs, then fetch detail pages for the
ones we haven't seen.

Per-run cost: ~3 listing pages + ~12 detail fetches = 15 HTTP calls.
No external API key required (no Firecrawl, no LLM at fetch time).
LLM parsing happens downstream via the normalizer if credits exist;
heuristic parser handles the fallback.
"""

from __future__ import annotations

import logging
import re

import httpx

logger = logging.getLogger(__name__)

JOBBERMAN_BASE = "https://www.jobberman.com"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# Listing pages we walk. Jobberman has many filter views; these three
# cover most professions and update frequently. /jobs is the catch-all,
# /jobs-by-field is profession-bucketed but the fields list is long;
# we stick to /jobs and let pagination expose the variety.
JOBBERMAN_LISTING_URLS = (
    "https://www.jobberman.com/jobs",
    "https://www.jobberman.com/jobs?page=2",
    "https://www.jobberman.com/jobs?page=3",
)

# Anchors look like href="https://www.jobberman.com/listings/<slug>".
JOB_LINK_RE = re.compile(
    r'href="(https://www\.jobberman\.com/listings/[a-z0-9\-_]+)"',
    re.I,
)

TITLE_HEADING_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.I | re.S)
COMPANY_RE = re.compile(
    r'<(?:a|span)[^>]*itemprop="hiringOrganization"[^>]*>(.*?)</(?:a|span)>',
    re.I | re.S,
)
LOCATION_RE = re.compile(
    r'<(?:span|div)[^>]*itemprop="addressLocality"[^>]*>(.*?)</(?:span|div)>',
    re.I | re.S,
)


def _strip_html(text: str) -> str:
    """Strip tags + collapse whitespace. Used for parsed labels only;
    raw_description keeps the full markdown."""
    s = re.sub(r"<[^>]+>", " ", text or "")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


async def fetch_jobs(
    keywords: set[str] | None = None,
    max_detail_fetches: int = 12,
    skip_urls: set[str] | None = None,
) -> list[dict]:
    """Walk Jobberman's listing pages, drop already-known URLs, fetch
    a small batch of detail pages, return normalised dicts.

    `keywords` is accepted for interface parity with other scrapers
    but Jobberman's whole catalog is Nigeria-local — the per-user
    inbox filter handles role matching downstream.
    """
    skip_urls = skip_urls or set()
    seen: set[str] = set()
    candidates: list[str] = []

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=4.0, read=12.0, write=4.0, pool=4.0),
        headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
        follow_redirects=True,
    ) as client:
        for listing_url in JOBBERMAN_LISTING_URLS:
            try:
                r = await client.get(listing_url)
                r.raise_for_status()
                body = r.text
            except httpx.HTTPError as e:
                logger.warning("Jobberman listing fetch failed for %s: %s", listing_url, e)
                continue
            for match in JOB_LINK_RE.findall(body):
                url = match.split("?")[0].split("#")[0].rstrip("/")
                if url in seen or url in skip_urls:
                    continue
                seen.add(url)
                candidates.append(url)

        logger.info("Jobberman: %d unique candidate listings across %d pages",
                    len(candidates), len(JOBBERMAN_LISTING_URLS))

        if len(candidates) > max_detail_fetches:
            candidates = candidates[:max_detail_fetches]

        jobs: list[dict] = []
        for url in candidates:
            try:
                r = await client.get(url)
                r.raise_for_status()
                body = r.text
            except httpx.HTTPError as e:
                logger.warning("Jobberman detail fetch failed for %s: %s", url, e)
                continue
            normalized = _parse_detail(url=url, body=body)
            if normalized:
                jobs.append(normalized)

    logger.info("Jobberman: %d jobs ingested", len(jobs))
    return jobs


def _parse_detail(*, url: str, body: str) -> dict | None:
    """Extract title / company / location from a Jobberman detail page.
    Falls back to URL slug if structured fields are absent."""
    if not body or len(body) < 500:
        return None

    title_m = TITLE_HEADING_RE.search(body)
    title = _strip_html(title_m.group(1)) if title_m else None
    if not title:
        # URL slug fallback: /listings/senior-engineer-abc123 → "Senior Engineer"
        slug_part = url.rstrip("/").split("/")[-1]
        slug_part = re.sub(r"-[a-z0-9]{4,}$", "", slug_part)  # strip trailing id
        title = slug_part.replace("-", " ").title() or "Untitled role"

    company_m = COMPANY_RE.search(body)
    company = _strip_html(company_m.group(1)) if company_m else "Unknown"

    location_m = LOCATION_RE.search(body)
    location = _strip_html(location_m.group(1)) if location_m else "Nigeria"

    slug = url.rstrip("/").split("/")[-1] or url

    return {
        "external_id": slug,
        "source_name": "jobberman",
        "source_type": "scraper",
        "company": company,
        "title": title,
        "location": location,
        "country": "NG",
        # Jobberman's catalog is mostly Lagos / Abuja onsite + some hybrid.
        # 'unknown' lets the normalizer classify from location string.
        "remote_type": "unknown",
        "job_url": url,
        "apply_url": url,
        "salary_text": None,
        "salary_min": None,
        "salary_max": None,
        "salary_currency": None,
        # Keep the full HTML so the downstream LLM parser (or heuristic
        # fallback) has the JD body to extract requirements / skills from.
        "raw_description": body[:8000],
        "tags": [],
    }
