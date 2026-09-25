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

from app.services.discovery.firecrawl_service import html_to_markdown, scrape_html, scrape_url
from app.services.discovery.jobposting import job_posting

logger = logging.getLogger(__name__)

WELLFOUND_BASE = "https://wellfound.com"

# Wellfound's URL structure for filtered discovery is /role/r/<slug>.
# This is the set of slugs we've verified Wellfound actually serves.
# Add more here when Wellfound's role index expands. Intentionally
# broad across professions so the scraper isn't biased toward tech.
WELLFOUND_KNOWN_ROLES: set[str] = {
    # Engineering
    "ai-engineer", "machine-learning-engineer", "software-engineer",
    "backend-engineer", "frontend-engineer", "full-stack-engineer",
    "mobile-engineer", "devops-engineer", "data-engineer", "data-scientist",
    "qa-engineer", "security-engineer", "infrastructure-engineer",
    # Design / product
    "product-designer", "ui-designer", "ux-designer", "graphic-designer",
    "product-manager", "technical-product-manager",
    # Business / growth
    "marketing-manager", "growth-marketer", "content-marketer",
    "sales-representative", "account-executive", "customer-success-manager",
    "business-development", "operations-manager", "finance-manager",
    "people-operations", "recruiter",
}

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


def roles_for_user(user_roles: list[str]) -> list[str]:
    """Map free-text user target_roles to Wellfound role slugs.
    Slugifies and intersects with WELLFOUND_KNOWN_ROLES.

    Examples:
        ["Senior AI Engineer"]    → ["ai-engineer"]
        ["Brand Designer"]        → ["graphic-designer"] (closest match)
        ["Marketing Manager"]     → ["marketing-manager"]
        ["Veterinarian"]          → []  (no match — skip)
    """
    if not user_roles:
        return []
    slugs: set[str] = set()
    seniority_strip = {"senior", "sr", "junior", "jr", "lead", "principal",
                       "staff", "head", "of", "the"}
    for raw in user_roles:
        role = (raw or "").lower().strip()
        if not role:
            continue
        tokens = [t for t in re.split(r"[^a-z0-9]+", role) if t and t not in seniority_strip]
        if not tokens:
            continue
        # Try full slug first, then progressively shorter ones until a match.
        for n in range(len(tokens), 0, -1):
            for start in range(len(tokens) - n + 1):
                candidate = "-".join(tokens[start:start + n])
                if candidate in WELLFOUND_KNOWN_ROLES:
                    slugs.add(candidate)
                    break
            if slugs:
                break
    return sorted(slugs)


async def fetch_jobs(
    user_roles: list[str] | None = None,
    keywords: set[str] | None = None,
    max_detail_fetches: int = 6,
    skip_urls: set[str] | None = None,
) -> list[dict]:
    """Walk Wellfound role pages driven by user roles. Skip entirely
    when none of the user roles map to a known Wellfound slug."""
    skip_urls = skip_urls or set()
    seen: set[str] = set()
    candidates: list[tuple[str, str]] = []

    roles_to_visit = roles_for_user(user_roles or [])
    if not roles_to_visit:
        logger.info(
            "Wellfound: skipping — no user roles map to any known Wellfound "
            "slug. user_roles=%s",
            user_roles,
        )
        return []

    for role in roles_to_visit:
        listing_url = f"{WELLFOUND_BASE}/role/r/{role}"
        try:
            md = await scrape_url(listing_url)
        except Exception as e:
            logger.warning("Wellfound listing scrape failed for %s: %s", role, e)
            continue
        matches_before = len(candidates)
        for title, url in JOB_LINK_RE.findall(md):
            cleaned = url.split("?")[0].split("#")[0].rstrip("/")
            if cleaned in seen or cleaned in skip_urls:
                continue
            seen.add(cleaned)
            candidates.append((title.strip(), cleaned))
        if len(candidates) == matches_before:
            # Diagnostic when the regex finds nothing — log a markdown
            # preview so we can see what the page rendered.
            preview = (md or "")[:600].replace("\n", " ")
            logger.warning(
                "Wellfound: 0 candidates from /role/r/%s (markdown length=%d). Preview: %s",
                role, len(md or ""), preview,
            )

    logger.info("Wellfound: %d unique candidate listings across %d roles (%s)",
                len(candidates), len(roles_to_visit), roles_to_visit)

    if len(candidates) > max_detail_fetches:
        candidates = candidates[:max_detail_fetches]

    jobs: list[dict] = []
    for title, url in candidates:
        html = await scrape_html(url)
        if not html:
            logger.warning("Wellfound detail page didn't load: %s", url)
            continue
        normalized = _parse_detail(title=title, url=url, markdown=html_to_markdown(html, url))
        if not normalized:
            continue
        # The page's JobPosting names the company and place as the employer
        # entered them; the page text often doesn't label them at all.
        posting = job_posting(html)
        if posting:
            normalized["company"] = posting["company"] or normalized["company"]
            normalized["location"] = posting["location"] or normalized["location"]
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
