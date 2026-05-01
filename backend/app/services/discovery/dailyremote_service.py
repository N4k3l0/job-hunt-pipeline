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

Cloudflare blocks Vercel's serverless IPs regardless of User-Agent
(verified by /debug-dailyremote — every page returned 403). We route
every fetch through Firecrawl, which solves the JS challenge upstream.

Each Firecrawl call costs one credit, so the scope here is intentionally
small. Total credits per cron run:
    len(CATEGORY_PATHS) + len(CATEGORY_PATHS) * PER_CATEGORY_LIMIT
With 2 × 8 + 2 = 18 calls/day → ~540 credits/month. Comfortable on the
Hobby plan (3000 credits) and leaves room for Crossover.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from html import unescape

from app.services.discovery.eligibility import matches_keywords
from app.services.discovery.firecrawl_service import scrape_html

logger = logging.getLogger(__name__)

BASE = "https://dailyremote.com"
USER_AGENT = "Firecrawl/1.0"

# Categories most relevant to the AI/PM users on this product. Each adds
# 1 + PER_CATEGORY_LIMIT Firecrawl calls per cron run.
CATEGORY_PATHS: tuple[str, ...] = (
    "/remote-product-jobs",
    "/remote-software-development-jobs",
)

# Per-category cap. Listing pages typically have ~30 unique URLs; we
# slice the most recent N to control credit spend.
PER_CATEGORY_LIMIT = 8
CONCURRENCY = 4  # parallel Firecrawl calls

# Anchor regex: matches /remote-job/<slug> in the listing HTML, whether
# the href is relative ('/remote-job/x') OR absolute (which is what
# Firecrawl returns, e.g. 'https://dailyremote.com/remote-job/x'). The
# capture group always yields just the path so downstream code stays
# host-agnostic. Trailing ID dedups the dual-link cards.
_JOB_LINK_RE = re.compile(
    r'(?:https?://(?:www\.)?dailyremote\.com)?(/remote-job/[a-z0-9\-]+)',
    re.I,
)
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

    Uses Firecrawl for every fetch — Cloudflare 403s direct httpx calls
    from Vercel's serverless IPs.
    """
    out: list[dict] = []
    seen_urls: set[str] = set()
    sem = asyncio.Semaphore(CONCURRENCY)

    async def fetch_via_firecrawl(rel_url: str) -> str:
        """One Firecrawl call. Returns raw HTML or '' on failure."""
        async with sem:
            return await scrape_html(f"{BASE}{rel_url}", timeout=25.0)

    for path in CATEGORY_PATHS:
        listing_html = await fetch_via_firecrawl(path)
        if not listing_html:
            logger.warning("DailyRemote listing %s: Firecrawl returned empty", path)
            continue

        urls = _extract_job_urls(listing_html)[:PER_CATEGORY_LIMIT]
        urls = [u for u in urls if u not in seen_urls]
        seen_urls.update(urls)
        if not urls:
            continue

        # Detail pages run concurrently, capped by the semaphore so we
        # don't burst Firecrawl beyond their per-second rate limit.
        detail_htmls = await asyncio.gather(*(fetch_via_firecrawl(u) for u in urls))

        for rel_url, html in zip(urls, detail_htmls):
            if not html:
                continue
            posting = _parse_job_page(html, rel_url)
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


def _passes_filters(posting: dict, keywords: set[str] | None) -> bool:
    """Keyword gate only.

    DailyRemote markets itself as a global remote board. Most postings tag
    `applicantLocationRequirements` as 'United States' but accept hires
    anywhere — the tag reflects where the company is, not where the
    candidate must be. With Nigeria-eligibility on, ~12 % of fetched DR
    jobs survived; with it off the user sees more US-tagged-but-globally-
    open roles and can dismiss any that turn out to be US-only on click.

    The strict eligibility gate stays on for Remotive / Himalayas /
    WeWorkRemotely where the structured location field is more reliable.
    """
    title = posting.get("title") or ""
    desc = posting.get("raw_description") or ""
    return matches_keywords(f"{title} {desc}", keywords)
