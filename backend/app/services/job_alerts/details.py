"""Full postings for jobs added from LinkedIn alerts.

Alert emails give a title, company and location but no description. The
company's own job board often lists the same job: ats_resolver finds the
posting on Greenhouse, Lever, Ashby, SmartRecruiters or Personio from
their free public listings, and Greenhouse, Lever and Ashby also publish
its description. LinkedIn's own pages aren't fetched, and nothing here
calls a paid service."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID

import httpx
from sqlalchemy import func, or_, select

from app.core.database import create_worker_session
from app.models.job import Job
from app.models.job_alert import LinkedInJob
from app.services.auto_apply.ats import detect_ats
from app.services.discovery.ats_resolver import TIMEOUT, USER_AGENT, resolve_ats_url

logger = logging.getLogger(__name__)

# Descriptions shorter than this don't count as having one (enrichment's
# own minimum).
MIN_DESCRIPTION_CHARS = 200


@dataclass
class DetailsResult:
    checked: int = 0
    postings_found: int = 0
    descriptions_found: int = 0
    job_ids: list[UUID] = field(default_factory=list)


async def fetch_description(client: httpx.AsyncClient, url: str) -> str | None:
    """A posting's description HTML from its job board's public API."""
    target = detect_ats(url)
    if target is None or target.board is None:
        return None
    try:
        if target.ats == "greenhouse":
            host = "boards-api.eu.greenhouse.io" if target.eu else "boards-api.greenhouse.io"
            r = await client.get(f"https://{host}/v1/boards/{target.board}/jobs/{target.job_id}")
            return r.json().get("content") if r.status_code == 200 else None
        if target.ats == "lever":
            host = "api.eu.lever.co" if target.eu else "api.lever.co"
            r = await client.get(f"https://{host}/v0/postings/{target.board}/{target.job_id}")
            if r.status_code != 200:
                return None
            data = r.json()
            parts = [data.get("description") or ""]
            for section in data.get("lists") or []:
                parts.append(f"<h3>{section.get('text') or ''}</h3><ul>{section.get('content') or ''}</ul>")
            parts.append(data.get("additional") or "")
            return "".join(parts)
        if target.ats == "ashby":
            r = await client.get(f"https://api.ashbyhq.com/posting-api/job-board/{target.board}")
            if r.status_code != 200:
                return None
            for job in r.json().get("jobs") or []:
                if str(job.get("id", "")).lower() == target.job_id:
                    return job.get("descriptionHtml")
    except (httpx.HTTPError, ValueError, AttributeError) as e:
        logger.info("Couldn't read the posting at %s: %s", url, type(e).__name__)
    return None


async def _lookup(company: str, title: str) -> tuple[str | None, str | None]:
    url = await resolve_ats_url(company, title)
    if not url:
        return None, None
    async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
        return url, await fetch_description(client, url)


async def fill_alert_job_details(
    *, limit: int = 10, concurrency: int = 4, time_budget_seconds: float = 40.0
) -> DetailsResult:
    """Look up postings for alert jobs that have no description yet, newest
    first. Each job is looked up once."""
    started = time.monotonic()
    result = DetailsResult()
    async with create_worker_session()() as db:
        rows = (await db.execute(
            select(LinkedInJob, Job)
            .join(Job, Job.id == LinkedInJob.job_id)
            .where(
                LinkedInJob.details_checked_at.is_(None),
                or_(Job.raw_description.is_(None), func.length(Job.raw_description) < MIN_DESCRIPTION_CHARS),
                Job.status.notin_(["raw", "duplicate", "expired"]),
            )
            .order_by(LinkedInJob.created_at.desc())
            .limit(limit)
        )).all()

        semaphore = asyncio.Semaphore(concurrency)

        async def run(job: Job):
            async with semaphore:
                if time.monotonic() - started > time_budget_seconds:
                    return None
                try:
                    return await asyncio.wait_for(_lookup(job.company, job.title), timeout=25)
                except Exception as e:  # noqa: BLE001
                    logger.info("Posting lookup failed for %s: %s", job.id, type(e).__name__)
                    return (None, None)

        outcomes = await asyncio.gather(*(run(job) for _, job in rows))
        now = datetime.now(timezone.utc)
        for (link, job), outcome in zip(rows, outcomes):
            if outcome is None:
                continue  # out of time; next run
            url, description = outcome
            link.details_checked_at = now
            result.checked += 1
            if url:
                result.postings_found += 1
                job.apply_url = job.apply_url or url
            if description and len(description) >= MIN_DESCRIPTION_CHARS:
                job.raw_description = description
                result.descriptions_found += 1
                result.job_ids.append(job.id)
        await db.commit()
    return result
