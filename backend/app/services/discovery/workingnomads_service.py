"""Working Nomads (workingnomads.com) — public JSON feed, no auth.

Endpoint: GET https://www.workingnomads.com/api/exposed_jobs/
Returns the active feed as a single JSON array (~40-80 rows on most
polls, including title / company_name / location / category_name /
tags / description / pub_date / url).

Categories the feed exposes include: Development, Design, Marketing,
Sales, Finance, Customer Success. In a sample run 24/37 = 65% were
Development — meaningful supply for AI Eng / ML / Automation users.

Rate-limit posture: public endpoint, no auth, no documented limit but
we cap to one call per discovery run.
"""

from __future__ import annotations

import logging
import re
from html import unescape
from typing import Any

import httpx

from app.services.discovery.eligibility import matches_keywords

logger = logging.getLogger(__name__)

WN_API = "https://www.workingnomads.com/api/exposed_jobs/"
USER_AGENT = "JobHuntPipeline/1.0 (+contact: hello@example.com)"

# Working Nomads category names that map to roles our users care about.
# Everything else (Finance, Sales, Customer Success, etc.) we still
# accept if it matches a keyword — the per-user inbox filter has the
# final say.
_RELEVANT_CATEGORIES = {
    "Development", "DevOps and Sysadmin", "Design", "Product",
    "Management and Finance", "Education", "Marketing",
}

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str | None) -> str:
    """Working Nomads ships descriptions as HTML. We strip tags + unescape
    entities so the raw_description column has plain text the scorer can
    use directly."""
    if not text:
        return ""
    return unescape(_HTML_TAG_RE.sub(" ", text)).strip()


def _split_tags(tags: Any) -> list[str]:
    """Tags field is a comma-separated string in the API response."""
    if not tags:
        return []
    if isinstance(tags, list):
        return [str(t).strip() for t in tags if t]
    return [t.strip() for t in str(tags).split(",") if t.strip()]


def _infer_country(location: str | None) -> str | None:
    """Working Nomads' location field is free-form (e.g. 'Europe only',
    'USA, Canada', 'Worldwide', 'Germany'). We make a best-effort ISO
    code guess; the inbox filter handles the rest at query time.

    Returns None for region / multi-country / 'Worldwide' strings —
    those are kept by the country filter via the IS NULL bypass and
    matched against the location-text second-pass.
    """
    if not location:
        return None
    loc = location.strip().lower()
    # Short ISO-ish tokens are accepted as-is.
    if len(loc) == 2 and loc.isalpha():
        return loc.upper()
    # Common single-country phrasings.
    from app.services.parsing.normalizer import COUNTRY_MAP
    for name, code in COUNTRY_MAP.items():
        if loc == name or loc.startswith(name + ",") or loc.endswith(", " + name):
            return code
    return None


async def fetch_jobs(
    keywords: set[str] | None = None,
    limit: int = 200,
) -> list[dict]:
    """Fetch the active Working Nomads feed, filter to relevant
    categories OR keyword matches, normalize to our raw-job dict shape.
    """
    async with httpx.AsyncClient(
        timeout=20.0,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    ) as client:
        try:
            response = await client.get(WN_API)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as e:
            logger.error("Working Nomads API error: %s", e)
            return []

    if not isinstance(payload, list):
        logger.warning("Working Nomads returned non-list payload: %s", type(payload))
        return []

    matched: list[dict] = []
    for j in payload:
        if not isinstance(j, dict):
            continue
        title = (j.get("title") or "").strip()
        url = (j.get("url") or "").strip()
        if not (title and url):
            continue

        # Filter: category-of-interest OR keyword match on title+tags.
        category = (j.get("category_name") or "").strip()
        tag_list = _split_tags(j.get("tags"))
        haystack = " ".join([title, category, " ".join(tag_list)]).lower()
        if keywords and not matches_keywords(haystack, keywords):
            # Allow through if category is in our relevant set even
            # without a keyword hit — that's how we catch "Senior
            # Engineer" titles that don't include the tech stack inline.
            if category not in _RELEVANT_CATEGORIES:
                continue

        location = (j.get("location") or "").strip() or "Remote"
        country = _infer_country(location)

        normalized = {
            "external_id": str(j.get("url") or j.get("title") or "")[:200],
            "source_name": "workingnomads",
            "source_type": "api",
            "company": (j.get("company_name") or "Unknown").strip(),
            "title": title,
            "location": location,
            "country": country,
            "remote_type": "full_remote",
            "job_url": url,
            "apply_url": url,
            "salary_text": None,
            "salary_min": None,
            "salary_max": None,
            "salary_currency": None,
            "raw_description": _strip_html(j.get("description")),
            "posted_at": j.get("pub_date"),
            "tags": tag_list,
        }
        matched.append(normalized)
        if len(matched) >= limit:
            break

    logger.info("Working Nomads: %d jobs ingested", len(matched))
    return matched
