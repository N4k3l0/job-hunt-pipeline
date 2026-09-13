"""WeWorkRemotely (weworkremotely.com) — public RSS feed.

Endpoint: GET https://weworkremotely.com/remote-jobs.rss
Returns the most recent ~150 jobs as an RSS 2.0 document. Each `<item>` has:
  - title              "Company: Job Title"
  - link               full job URL
  - description        HTML — includes a "Region:" line we use for eligibility
  - pubDate            RFC-822 timestamp

We parse with the stdlib ElementTree. The feed is from a trusted source we
control via constant URL, so XXE risk is acceptable; if we ever start parsing
arbitrary user-provided RSS we should switch to defusedxml.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET

import httpx

from app.services.discovery.eligibility import (
    eligible_countries_from_text,
    matches_keywords,
)

logger = logging.getLogger(__name__)

WWR_RSS_URL = "https://weworkremotely.com/remote-jobs.rss"
USER_AGENT = "JobHuntPipeline/1.0 (+contact: hello@example.com)"

# WWR titles are formatted "Company: Job Title".
_TITLE_SPLIT = re.compile(r"^\s*([^:]+):\s*(.+)\s*$")
# WWR descriptions include "<strong>Region:</strong> Worldwide" or similar.
_REGION_RE = re.compile(r"region\s*:\s*</strong>\s*([^<]+)", re.I)
_REGION_FALLBACK_RE = re.compile(r"region\s*:\s*([^\n<]+)", re.I)
_HTML_TAG_RE = re.compile(r"<[^>]+>")


async def fetch_jobs(keywords: set[str] | None = None) -> list[dict]:
    """Pull the WWR RSS feed and return postings matching the keywords."""
    async with httpx.AsyncClient(
        timeout=30.0,
        headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml"},
    ) as client:
        try:
            response = await client.get(WWR_RSS_URL)
            response.raise_for_status()
        except httpx.HTTPError as e:
            logger.error("WWR RSS fetch failed: %s", e)
            return []

    try:
        root = ET.fromstring(response.text)
    except ET.ParseError as e:
        logger.error("WWR RSS parse failed: %s", e)
        return []

    matched: list[dict] = []
    items = root.findall(".//item")
    for item in items:
        normalized = _parse_item(item)
        if not normalized:
            continue

        searchable = f"{normalized['title']} {normalized['raw_description']}"
        if not matches_keywords(searchable, keywords):
            continue

        # Restricted postings are kept and tagged; each user's inbox
        # filters them by home country.
        normalized["eligible_countries"] = eligible_countries_from_text(
            region_text=normalized.get("_region"),
            description=normalized["raw_description"],
        )
        normalized.pop("_region", None)
        matched.append(normalized)

    logger.info("WeWorkRemotely: %d eligible (of %d raw)", len(matched), len(items))
    return matched


def _parse_item(item: ET.Element) -> dict | None:
    """Convert one <item> to our raw-job dict shape, or None if unparseable."""
    raw_title = (item.findtext("title") or "").strip()
    link = (item.findtext("link") or "").strip()
    raw_description = (item.findtext("description") or "").strip()
    guid = (item.findtext("guid") or link or raw_title).strip()
    pub_date = (item.findtext("pubDate") or "").strip()
    if not raw_title or not link:
        return None

    company = "Unknown"
    title = raw_title
    m = _TITLE_SPLIT.match(raw_title)
    if m:
        company = m.group(1).strip()
        title = m.group(2).strip()

    region_match = _REGION_RE.search(raw_description) or _REGION_FALLBACK_RE.search(raw_description)
    region = region_match.group(1).strip() if region_match else None

    # Strip HTML tags for the stored description so the LLM doesn't get noise.
    plain_description = _HTML_TAG_RE.sub("", raw_description).strip()

    return {
        "external_id": guid,
        "source_name": "weworkremotely",
        "source_type": "rss",
        "company": company,
        "title": title,
        "location": region or "Worldwide",
        "country": None,
        "remote_type": "full_remote",
        "job_url": link,
        "apply_url": link,
        "salary_text": None,
        "salary_min": None,
        "salary_max": None,
        "salary_currency": None,
        "raw_description": plain_description,
        "posted_at": pub_date or None,
        "tags": [],
        # Internal-only field passed back so the eligibility filter can use it
        # without re-parsing — popped before returning to the worker.
        "_region": region,
    }
