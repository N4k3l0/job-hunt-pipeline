"""DailyRemote (dailyremote.com) — public job board, no API.

DailyRemote does not publish a JSON or RSS feed. They DO embed
schema.org/JobPosting JSON-LD on every individual job page, which is the
canonical, machine-readable contract Google Jobs uses. We exploit that:

1. Fetch a small set of category listing pages (eg /remote-product-jobs)
2. Extract the unique /remote-job/<slug> URLs
3. Fetch each job page concurrently and parse the embedded JobPosting JSON-LD
4. Filter to Nigeria-eligible postings using the same heuristic as Remotive
5. Normalize into our internal raw-job dict shape

Cloudflare gates the site against generic curl/python clients, but lets a
plausible browser User-Agent through. We send one, and we don't need to
solve the JS challenge because the listing/detail pages are server-rendered.

Latency budget: we cap at ~4 categories × 25 jobs = 100 page fetches,
issued in waves of 10 — comfortably inside the 60s Vercel limit.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from html import unescape
from typing import Iterable

import httpx

from app.services.discovery.eligibility import (
    is_nigeria_friendly,
    matches_keywords,
)

logger = logging.getLogger(__name__)

BASE = "https://dailyremote.com"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Categories the AI/PM users care about. Keep this list short so we stay
# inside the Vercel function timeout.
CATEGORY_PATHS: tuple[str, ...] = (
    "/remote-product-jobs",
    "/remote-data-science-jobs",
    "/remote-software-development-jobs",
    "/remote-design-jobs",
)

# Per-category cap. The listing page returns ~30 unique job URLs, and we'd
# rather pull the most recent slice from many categories than exhaust one.
PER_CATEGORY_LIMIT = 25
CONCURRENCY = 10  # max simultaneous job-detail fetches

# Anchor regex: matches /remote-job/<slug> hrefs in the listing HTML. The
# trailing ID lets us dedupe duplicates that the page renders for accessibility
# (one card has both a thumbnail link and a title link to the same job).
_JOB_LINK_RE = re.compile(r'href="(/remote-job/[a-z0-9\-]+)"', re.I)
_LDJSON_RE = re.compile(
    r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
    re.DOTALL,
)


async def fetch_jobs(
    keywords: set[str] | None = None,
    limit: int = 200,
) -> list[dict]:
    """Return up to `limit` Nigeria-eligible jobs across the configured
    categories, normalized for `_ingest_raw_jobs`.
    """
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }
    out: list[dict] = []
    seen_urls: set[str] = set()

    async with httpx.AsyncClient(
        timeout=20.0, follow_redirects=True, headers=headers
    ) as client:
        for path in CATEGORY_PATHS:
            try:
                listing = await client.get(f"{BASE}{path}")
                listing.raise_for_status()
            except httpx.HTTPError as e:
                logger.warning("DailyRemote listing %s failed: %s", path, e)
                continue

            urls = _extract_job_urls(listing.text)[:PER_CATEGORY_LIMIT]
            urls = [u for u in urls if u not in seen_urls]
            seen_urls.update(urls)

            sem = asyncio.Semaphore(CONCURRENCY)

            async def fetch_one(rel_url: str) -> dict | None:
                async with sem:
                    try:
                        r = await client.get(f"{BASE}{rel_url}")
                        r.raise_for_status()
                    except httpx.HTTPError as e:
                        logger.debug("DailyRemote job %s failed: %s", rel_url, e)
                        return None
                    return _parse_job_page(r.text, rel_url)

            results = await asyncio.gather(*(fetch_one(u) for u in urls))
            for posting in results:
                if not posting:
                    continue
                if not _passes_filters(posting, keywords):
                    continue
                out.append(posting)
                if len(out) >= limit:
                    break

            if len(out) >= limit:
                break

    logger.info("DailyRemote: %d eligible jobs across %d categories",
                len(out), len(CATEGORY_PATHS))
    return out


# ─── HTML helpers ───────────────────────────────────────────────────────────

def _extract_job_urls(html: str) -> list[str]:
    """Pull unique /remote-job/<slug> hrefs from a category listing page."""
    seen: set[str] = set()
    ordered: list[str] = []
    for match in _JOB_LINK_RE.finditer(html):
        url = match.group(1)
        if url not in seen:
            seen.add(url)
            ordered.append(url)
    return ordered


def _parse_job_page(html: str, rel_url: str) -> dict | None:
    """Extract the JobPosting JSON-LD block from a detail page and normalize."""
    for raw in _LDJSON_RE.findall(html):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("@type") == "JobPosting":
            return _normalize_jobposting(data, rel_url)
    return None


def _normalize_jobposting(data: dict, rel_url: str) -> dict:
    """Convert schema.org JobPosting → our internal raw-job dict shape."""
    org = data.get("hiringOrganization") or {}
    company = (
        org.get("name") if isinstance(org, dict) else None
    ) or "Unknown"

    # Description is HTML-encoded inside the JSON-LD. Unescape so downstream
    # parsing/dedup sees real characters, not "&lt;p&gt;".
    description = unescape(data.get("description") or "")

    base_salary = data.get("baseSalary") or {}
    salary_min = salary_max = salary_currency = salary_text = None
    if isinstance(base_salary, dict):
        amount = base_salary.get("value") or {}
        if isinstance(amount, dict):
            salary_min = _safe_int(amount.get("minValue"))
            salary_max = _safe_int(amount.get("maxValue"))
        else:
            salary_min = _safe_int(base_salary.get("minValue"))
            salary_max = _safe_int(base_salary.get("maxValue"))
        salary_currency = base_salary.get("currency")
        if salary_min and salary_max and salary_min == salary_max == 0:
            salary_min = salary_max = None  # the site uses 0/0 to mean "unset"
        if salary_min and salary_max:
            salary_text = f"{salary_currency or '$'}{salary_min:,}-{salary_max:,}"

    job_url = data.get("url") or f"{BASE}{rel_url}"
    apply_url = data.get("hiringOrganization", {}).get("sameAs") or job_url

    # Location field — flatten applicantLocationRequirements (list of countries)
    # or jobLocation (specific cities). DailyRemote remote-only postings tend to
    # have applicantLocationRequirements set.
    location = _extract_location(data)

    identifier = data.get("identifier") or {}
    external_id = (
        identifier.get("value") if isinstance(identifier, dict) else None
    ) or rel_url.rsplit("-", 1)[-1]

    return {
        "external_id": str(external_id),
        "source_name": "dailyremote",
        "source_type": "scraped",
        "company": company,
        "title": data.get("title") or "",
        "location": location,
        "country": None,
        "remote_type": "full_remote",  # DailyRemote is a remote-only board
        "job_url": job_url,
        "apply_url": apply_url,
        "salary_text": salary_text,
        "salary_min": salary_min,
        "salary_max": salary_max,
        "salary_currency": salary_currency,
        "raw_description": description,
        "posted_at": data.get("datePosted"),
        "tags": [],
        "employment_type": _normalize_employment_type(data.get("employmentType")),
    }


def _extract_location(data: dict) -> str:
    reqs = data.get("applicantLocationRequirements")
    if isinstance(reqs, list) and reqs:
        names = [r.get("name") for r in reqs if isinstance(r, dict) and r.get("name")]
        if names:
            return ", ".join(names[:5]) + ("…" if len(names) > 5 else "")
    if isinstance(reqs, dict) and reqs.get("name"):
        return reqs["name"]
    loc = data.get("jobLocation")
    if isinstance(loc, list) and loc:
        loc = loc[0]
    if isinstance(loc, dict):
        addr = loc.get("address") or {}
        if isinstance(addr, dict):
            parts = [
                addr.get("addressLocality"),
                addr.get("addressRegion"),
                addr.get("addressCountry"),
            ]
            joined = ", ".join(p for p in parts if p)
            if joined:
                return joined
    return "Remote"


def _safe_int(v) -> int | None:
    try:
        n = int(float(v))
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def _normalize_employment_type(raw) -> str | None:
    if not raw:
        return None
    if isinstance(raw, list):
        raw = raw[0] if raw else None
    if not isinstance(raw, str):
        return None
    mapping = {
        "FULL_TIME": "full_time",
        "PART_TIME": "part_time",
        "CONTRACTOR": "contract",
        "TEMPORARY": "contract",
        "INTERN": "internship",
        "VOLUNTEER": "volunteer",
    }
    return mapping.get(raw.upper(), raw.lower())


def _passes_filters(posting: dict, keywords: Iterable[str] | None) -> bool:
    """User-keyword + Nigeria-eligibility gate."""
    title = posting.get("title") or ""
    desc = posting.get("raw_description") or ""
    location = posting.get("location") or ""
    if not matches_keywords(f"{title} {desc}", keywords):
        return False
    # `location` doubles as the candidate-required-location field for
    # remote-only boards. Pass it through the same heuristic as Remotive.
    if is_nigeria_friendly(
        candidate_required_location=location, description=desc
    ) is False:
        return False
    return True
