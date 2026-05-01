"""Curated companies discovery — pulls jobs directly from a hand-picked
list of companies on free public ATSes (Greenhouse, Lever, Ashby).

Why this source matters more than aggregators:
  - Apply URLs are clean ATS links, no signup wall.
  - Listings include full description (Greenhouse `?content=true`, Lever
    inline) so skill scoring works from day one.
  - Volume is bounded and predictable (~10-30 fresh jobs/day across the
    list). High-signal: companies are pre-filtered for being remote-friendly
    and on a free ATS.

The company list lives in `curated_companies.json` next to this file.
Adding/removing a company is a one-line edit + redeploy. The runner
gracefully skips slugs that 404 — no need to verify exhaustively up front.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from html import unescape
from pathlib import Path

import httpx

from app.services.discovery.eligibility import matches_keywords

logger = logging.getLogger(__name__)

USER_AGENT = "JobHuntPipeline/1.0 (curated)"
# Tighter per-request timeout: when fetching 50-100 companies in parallel
# we'd rather skip a slow one than blow the cron's 35s budget. Concurrency
# bumped to 16 — the public ATSes (Greenhouse / Lever / Ashby) handle this
# fine and our wall time goes from ~30s to ~8s for the same list.
TIMEOUT = httpx.Timeout(connect=3.0, read=6.0, write=3.0, pool=3.0)
CONCURRENCY = 16

_COMPANIES_FILE = Path(__file__).parent / "curated_companies.json"


def _load_companies() -> list[dict]:
    with open(_COMPANIES_FILE) as f:
        return (json.load(f) or {}).get("companies") or []


def _strip_html(html: str) -> str:
    """Crude HTML→text. Greenhouse/Lever ship descriptions with markup;
    we want plain text for keyword matching + scoring."""
    if not html:
        return ""
    text = re.sub(r"<[^>]+>", " ", html)
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


# ─── Per-ATS fetchers ───────────────────────────────────────────────────────


async def _fetch_greenhouse(client: httpx.AsyncClient, company: dict) -> list[dict]:
    """Greenhouse public board API. ?content=true ships descriptions inline,
    so one HTTP call gets every job + body for that company."""
    slug = company["slug"]
    try:
        r = await client.get(
            f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
            params={"content": "true"},
        )
        if r.status_code != 200:
            return []
        data = r.json()
    except (httpx.HTTPError, ValueError):
        return []

    out: list[dict] = []
    for j in data.get("jobs") or []:
        title = j.get("title") or ""
        url = j.get("absolute_url") or ""
        loc_obj = j.get("location") or {}
        location = loc_obj.get("name") if isinstance(loc_obj, dict) else None
        desc = _strip_html(j.get("content") or "")
        if not title or not url:
            continue
        out.append({
            "external_id": str(j.get("id") or url),
            "source_name": "curated",
            "source_type": "ats",
            "company": company.get("name") or slug,
            "title": title,
            "location": location,
            "country": None,
            "remote_type": None,  # let classify_remote() decide downstream
            "job_url": url,
            "apply_url": url,  # Greenhouse URLs are signup-free apply pages
            "salary_text": None,
            "salary_min": None,
            "salary_max": None,
            "salary_currency": None,
            "raw_description": desc,
            "posted_at": j.get("updated_at"),
            "tags": [],
            "_curated_ats": "greenhouse",
        })
    return out


async def _fetch_lever(client: httpx.AsyncClient, company: dict) -> list[dict]:
    """Lever public postings. One call returns the full list with body."""
    slug = company["slug"]
    try:
        r = await client.get(
            f"https://api.lever.co/v0/postings/{slug}",
            params={"mode": "json"},
        )
        if r.status_code != 200:
            return []
        data = r.json()
    except (httpx.HTTPError, ValueError):
        return []
    if not isinstance(data, list):
        return []

    out: list[dict] = []
    for j in data:
        title = j.get("text") or ""
        url = j.get("hostedUrl") or j.get("applyUrl") or ""
        cats = j.get("categories") or {}
        location = cats.get("location") if isinstance(cats, dict) else None
        # Lever ships description, additional, and lists separately; merge.
        desc_parts = [
            _strip_html(j.get("description") or ""),
            _strip_html(j.get("additional") or ""),
        ]
        for lst in j.get("lists") or []:
            if isinstance(lst, dict):
                desc_parts.append(
                    f"{lst.get('text','')}: " + _strip_html(lst.get("content") or "")
                )
        desc = " ".join(p for p in desc_parts if p)
        if not title or not url:
            continue
        out.append({
            "external_id": str(j.get("id") or url),
            "source_name": "curated",
            "source_type": "ats",
            "company": company.get("name") or slug,
            "title": title,
            "location": location,
            "country": None,
            "remote_type": None,
            "job_url": url,
            "apply_url": j.get("applyUrl") or url,
            "salary_text": None,
            "salary_min": None,
            "salary_max": None,
            "salary_currency": None,
            "raw_description": desc,
            "posted_at": j.get("createdAt"),
            "tags": (cats.get("commitment") and [cats["commitment"]]) or [],
            "employment_type": cats.get("commitment") if isinstance(cats, dict) else None,
            "_curated_ats": "lever",
        })
    return out


async def _fetch_ashby(client: httpx.AsyncClient, company: dict) -> list[dict]:
    """Ashby public job-board API. The listing endpoint ships titles + URLs
    but NOT descriptions — those live on a per-job endpoint. We fetch the
    listing only here; description is best-effort empty so the scorer
    still has title to work with."""
    slug = company["slug"]
    try:
        r = await client.get(
            f"https://api.ashbyhq.com/posting-api/job-board/{slug}",
            params={"includeCompensation": "true"},
        )
        if r.status_code != 200:
            return []
        data = r.json()
    except (httpx.HTTPError, ValueError):
        return []

    out: list[dict] = []
    for j in data.get("jobs") or []:
        title = j.get("title") or ""
        url = j.get("jobUrl") or j.get("applyUrl") or ""
        location = j.get("locationName")
        # Ashby's `descriptionPlain` and `descriptionHtml` are present on
        # the per-job detail endpoint, not the listing. Take what we have.
        desc = _strip_html(j.get("descriptionHtml") or "")
        if not desc:
            desc = j.get("descriptionPlain") or ""
        if not title or not url:
            continue
        out.append({
            "external_id": str(j.get("id") or url),
            "source_name": "curated",
            "source_type": "ats",
            "company": company.get("name") or slug,
            "title": title,
            "location": location,
            "country": None,
            "remote_type": "full_remote" if j.get("isRemote") else None,
            "job_url": url,
            "apply_url": j.get("applyUrl") or url,
            "salary_text": None,
            "salary_min": None,
            "salary_max": None,
            "salary_currency": None,
            "raw_description": desc,
            "posted_at": j.get("publishedAt"),
            "tags": [],
            "employment_type": j.get("employmentType"),
            "_curated_ats": "ashby",
        })
    return out


_FETCHERS = {
    "greenhouse": _fetch_greenhouse,
    "lever": _fetch_lever,
    "ashby": _fetch_ashby,
}


# ─── Public API ─────────────────────────────────────────────────────────────


async def fetch_jobs(
    keywords: set[str] | None = None,
    limit: int = 500,
) -> list[dict]:
    """Pull every active posting from every curated company, filter by
    user keywords, return normalized for `_ingest_raw_jobs`."""
    companies = _load_companies()
    if not companies:
        return []

    sem = asyncio.Semaphore(CONCURRENCY)

    async def fetch_company(client: httpx.AsyncClient, c: dict) -> list[dict]:
        fetcher = _FETCHERS.get(c.get("ats") or "")
        if not fetcher:
            logger.warning("Curated: no fetcher for ats=%r (%s)", c.get("ats"), c.get("name"))
            return []
        async with sem:
            try:
                return await fetcher(client, c)
            except Exception as e:  # noqa: BLE001
                logger.warning("Curated: %s (%s) failed: %s", c.get("name"), c.get("ats"), e)
                return []

    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    async with httpx.AsyncClient(timeout=TIMEOUT, headers=headers) as client:
        batches = await asyncio.gather(*(fetch_company(client, c) for c in companies))

    all_jobs: list[dict] = [j for batch in batches for j in batch]

    # Apply keyword filter against title + description. Skill-aware scoring
    # later will sort the survivors by fit.
    if keywords:
        kept = []
        for j in all_jobs:
            text = f"{j.get('title','')} {j.get('raw_description','')}"
            if matches_keywords(text, keywords):
                kept.append(j)
        all_jobs = kept

    if limit and len(all_jobs) > limit:
        all_jobs = all_jobs[:limit]

    logger.info("Curated: %d companies → %d jobs after keyword filter",
                len(companies), len(all_jobs))
    return all_jobs


async def probe_companies() -> list[dict]:
    """Per-company health check used by the /debug-curated endpoint.
    Returns one row per company: which ATS it's on, did the API return
    200, how many jobs it surfaced.
    """
    companies = _load_companies()
    sem = asyncio.Semaphore(CONCURRENCY)

    async def probe(client: httpx.AsyncClient, c: dict) -> dict:
        out: dict = {"name": c.get("name"), "ats": c.get("ats"), "slug": c.get("slug")}
        fetcher = _FETCHERS.get(c.get("ats") or "")
        if not fetcher:
            out["error"] = "no fetcher"
            return out
        async with sem:
            try:
                jobs = await fetcher(client, c)
                out["jobs_returned"] = len(jobs)
                out["sample_title"] = jobs[0]["title"] if jobs else None
            except Exception as e:  # noqa: BLE001
                out["error"] = f"{type(e).__name__}: {e}"
        return out

    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    async with httpx.AsyncClient(timeout=TIMEOUT, headers=headers) as client:
        results = await asyncio.gather(*(probe(client, c) for c in companies))
    return results
