"""Find a job's real application form behind a job board's Apply button.

Arbeitnow's job pages send applicants on with a plain redirect from
`<job page>/apply` to the company's own hiring system, most often Ashby,
Greenhouse or Lever. Reading that redirect takes one small request and
turns a job board listing into a form Apply for me can fill in. Most jobs
in inboxes come from Arbeitnow, so this is what makes Apply for me reach
them.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import load_only

from app.core.database import create_worker_session
from app.models.job import Job
from app.services.auto_apply.ats import detect_ats
from app.services.auto_apply.forms import http_client
from app.services.enrichment.job_enricher import best_score

_ARBEITNOW_JOB = re.compile(r"^https?://(?:www\.)?arbeitnow\.[a-z.]+/jobs/companies/[^/?#]+/[^/?#]+", re.I)
_ARBEITNOW_HOST = re.compile(r"(?:^|\.)arbeitnow\.[a-z.]+$", re.I)
# The same job pages in SQL, for picking jobs to check in bulk.
ARBEITNOW_JOB_SQL = r"^https?://(www\.)?arbeitnow\.[a-z.]+/jobs/companies/"
HIDDEN_STATUSES = ["duplicate", "raw", "expired", "dismissed"]


def has_apply_redirect(url: str | None) -> bool:
    """Whether this is a job board page whose Apply button redirects to the
    company's form."""
    return bool(url and _ARBEITNOW_JOB.match(url.strip()))


async def find_apply_url(url: str | None, client: httpx.AsyncClient | None = None) -> str | None:
    """The company's own application page for a job board listing, or None
    when the board isn't one this knows or the listing doesn't lead
    anywhere (taken down, say). Raises httpx.HTTPError when the board
    can't be asked right now, so the caller can try again later."""
    if not has_apply_redirect(url):
        return None
    apply_page = _ARBEITNOW_JOB.match(url.strip()).group(0) + "/apply"
    owns_client = client is None
    client = client or http_client()
    try:
        r = await client.get(apply_page, follow_redirects=False)
    finally:
        if owns_client:
            await client.aclose()
    if r.status_code == 429 or r.status_code >= 500:
        r.raise_for_status()
    location = r.headers.get("location") if r.is_redirect else None
    if not location or not location.startswith(("http://", "https://")):
        return None
    if _ARBEITNOW_HOST.search(urlparse(location).hostname or ""):
        return None  # back to the board itself: the job has gone
    # Referral tags stay: the form doesn't mind, and the board gets credit.
    return location


@dataclass
class ApplyLinkResult:
    checked: int = 0
    found: int = 0  # led to the company's own form
    fillable: int = 0  # ...on a system Apply for me fills in
    gone: int = 0  # led nowhere; the listing is kept as the apply link
    errors: int = 0  # the board didn't answer; tried again next run


def _pending_filter(max_age_days: int):
    return (
        Job.apply_url.is_(None),
        Job.job_url.op("~*")(ARBEITNOW_JOB_SQL),
        Job.status.notin_(HIDDEN_STATUSES),
        Job.discovered_at >= datetime.now(timezone.utc) - timedelta(days=max_age_days),
    )


async def resolve_pending_apply_links(
    *,
    limit: int = 100,
    max_age_days: int = 30,
    concurrency: int = 2,
    pause_seconds: float = 0.3,
    time_budget_seconds: float = 30.0,
) -> ApplyLinkResult:
    """Follow the Apply link of up to `limit` job board listings that
    haven't been checked, best match for any user first. Free: one small
    request each, no AI. Two at a time with a pause after each, about six
    a second: the first run asked 100 in 2.5s and the board turned some
    away."""
    started = time.monotonic()
    result = ApplyLinkResult()
    async with create_worker_session()() as db:
        jobs = (await db.execute(
            select(Job)
            .where(*_pending_filter(max_age_days))
            .order_by(best_score().desc().nulls_last(), Job.discovered_at.desc())
            .limit(limit)
            .options(load_only(Job.id, Job.job_url, Job.apply_url))
        )).scalars().all()

        semaphore = asyncio.Semaphore(concurrency)
        async with http_client() as client:
            async def check(job: Job) -> str | bool | None:
                async with semaphore:
                    if time.monotonic() - started > time_budget_seconds:
                        return None  # out of time; next run
                    try:
                        return await find_apply_url(job.job_url, client) or job.job_url
                    except httpx.HTTPError:
                        return False
                    finally:
                        await asyncio.sleep(pause_seconds)

            outcomes = await asyncio.gather(*(check(job) for job in jobs))

        for job, outcome in zip(jobs, outcomes):
            if outcome is None:
                continue
            result.checked += 1
            if outcome is False:
                result.errors += 1
                continue
            job.apply_url = outcome
            if outcome == job.job_url:
                result.gone += 1
            else:
                result.found += 1
                result.fillable += detect_ats(outcome) is not None
        await db.commit()
    return result


async def pending_apply_links(max_age_days: int = 30) -> int:
    async with create_worker_session()() as db:
        return (await db.execute(
            select(func.count(Job.id)).where(*_pending_filter(max_age_days))
        )).scalar() or 0
