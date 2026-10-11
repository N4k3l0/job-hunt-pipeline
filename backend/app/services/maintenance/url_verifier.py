"""Probe job apply URLs and mark confirmed-dead postings as expired.

Used by:
  - The admin 'Verify URLs' button (interactive, large batches)
  - The daily cron (small piggyback batch)
  - /cron/expire-stale on the scheduled grading workflow

Conservative on purpose — only flips status to 'expired' on a definitive
HTTP 404 / 410. Any other response (200, 30x, 403, 5xx, timeout, network
error) is treated as 'don't know' and the row is left alone. We never
false-positive a live posting.

Greenhouse, Lever and Ashby jobs are asked through the hiring system
instead (the same request that reads the form, auto_apply/forms.py), which
says for certain whether the job is open: a closed one expires, an open
one counts as listed (`last_seen_at`). A plain link can't tell that:
Greenhouse sends a closed job's link to the company's board, which loads.

Jobs people have worked on that no site has listed for a while are checked
first, at most once a day each: they carry a "may have closed" note
(services/job_freshness.py) until a check settles it.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Literal

import httpx
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job
from app.services.auto_apply.ats import AtsTarget, detect_ats
from app.services.auto_apply.forms import USER_AGENT, FormUnavailable, fetch_form
from app.services.job_freshness import MAYBE_CLOSED_DAYS, anyone_worked_on

logger = logging.getLogger(__name__)

PRE_APPLIED_STATUSES = (
    "raw", "normalized", "deduplicated",
    "enriched", "scored", "discovered", "shortlisted",
)

_PROBE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json",
}

# Hosts that systematically anti-bot or rate-limit our serverless probes.
# Probing them returns 429 / 403 regardless of whether the underlying job
# is alive, so the verdict is meaningless and we burn the budget. We
# return 'skipped' for these — the verify caller can then handle them
# via a different path (source-specific age cleanup, manual review, etc.)
# instead of letting them dominate the 'ambiguous' bucket.
_ANTI_BOT_HOSTS: tuple[str, ...] = (
    "adzuna.com", "www.adzuna.com",
    "linkedin.com", "www.linkedin.com",
    "indeed.com", "www.indeed.com",
    "glassdoor.com", "www.glassdoor.com",
    "ziprecruiter.com", "www.ziprecruiter.com",
    "monster.com", "www.monster.com",
    "wellfound.com", "www.wellfound.com",
)


def _is_anti_bot_host(url: str) -> bool:
    try:
        host = (httpx.URL(url).host or "").lower()
    except Exception:
        return False
    return any(host == h or host.endswith("." + h) for h in _ANTI_BOT_HOSTS)


Verdict = Literal["dead", "alive", "open", "ambiguous", "skipped"]
# How often a job someone worked on is checked while it goes unlisted.
RECHECK_HOURS = 24
# Hiring systems send the whole form, so they get longer than a link check.
HIRING_SYSTEM_TIMEOUT = httpx.Timeout(connect=5.0, read=8.0, write=5.0, pool=5.0)


async def _probe(client: httpx.AsyncClient, url: str, sem: asyncio.Semaphore) -> Verdict:
    """Single-URL probe. HEAD first (cheap); falls back to GET if the
    server doesn't support HEAD."""
    try:
        async with sem:
            r = await client.head(url, headers=_PROBE_HEADERS, follow_redirects=True)
            if r.status_code in (405, 501):
                r = await client.get(url, headers=_PROBE_HEADERS, follow_redirects=True)
            if r.status_code in (404, 410):
                return "dead"
            if 200 <= r.status_code < 400:
                return "alive"
            return "ambiguous"  # 403 / 5xx / 429 — can't tell
    except (
        httpx.TimeoutException,
        httpx.ConnectError,
        httpx.ReadError,
        httpx.RemoteProtocolError,
    ):
        return "ambiguous"
    except Exception:  # noqa: BLE001
        return "ambiguous"


async def _ask_hiring_system(client: httpx.AsyncClient, target: AtsTarget, sem: asyncio.Semaphore) -> Verdict:
    """'open' or 'dead' for certain, from Greenhouse, Lever or Ashby."""
    try:
        async with sem:
            await fetch_form(client, target)
        return "open"
    except FormUnavailable as e:
        return "dead" if e.closed else "ambiguous"
    except Exception:  # noqa: BLE001
        return "ambiguous"


def _hiring_system_job(job: Job) -> AtsTarget | None:
    for url in (job.apply_url, job.job_url):
        target = detect_ats(url)
        if target is not None and target.board:
            return target
    return None


async def verify_batch(
    db: AsyncSession,
    *,
    limit: int = 100,
    age_days_min: int = 0,
    concurrency: int = 8,
    timeout_s: float = 4.0,
) -> dict[str, int | bool]:
    """Probe up to `limit` jobs, least recently checked first, and mark
    confirmed-dead ones as expired. Jobs people have worked on that no
    site has listed for MAYBE_CLOSED_DAYS go first. Every probed job gets
    last_checked_at, so repeated calls work through the whole catalog.
    Returns counters + has_more.
    """
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import func as sa_func, text

    bounded = min(max(int(limit), 1), 250)
    now = datetime.now(timezone.utc)
    checkable = [
        Job.status.in_(PRE_APPLIED_STATUSES),
        (Job.apply_url.is_not(None)) | (Job.job_url.is_not(None)),
    ]
    oldest_first = (Job.last_checked_at.asc().nulls_first(), Job.discovered_at.asc().nulls_first())

    worked_on = (await db.execute(
        select(Job).where(
            *checkable,
            func.coalesce(Job.last_seen_at, Job.discovered_at) < now - timedelta(days=MAYBE_CLOSED_DAYS),
            or_(Job.last_checked_at.is_(None), Job.last_checked_at < now - timedelta(hours=RECHECK_HOURS)),
            anyone_worked_on(Job.id),
        ).order_by(*oldest_first).limit(bounded)
    )).scalars().all()

    q = select(Job).where(*checkable).order_by(*oldest_first).limit(bounded - len(worked_on))
    if worked_on:
        q = q.where(Job.id.notin_([job.id for job in worked_on]))
    if age_days_min > 0:
        q = q.where(Job.discovered_at < sa_func.now() - text(f"interval '{int(age_days_min)} days'"))

    rows = list(worked_on) + (list((await db.execute(q)).scalars().all()) if len(worked_on) < bounded else [])
    if not rows:
        return {"checked": 0, "expired": 0, "alive": 0, "open": 0, "ambiguous": 0, "has_more": False}

    sem = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=3.0, read=timeout_s, write=3.0, pool=3.0),
        follow_redirects=True,
    ) as client, httpx.AsyncClient(
        timeout=HIRING_SYSTEM_TIMEOUT, follow_redirects=True, headers={"User-Agent": USER_AGENT},
    ) as hiring_systems:
        async def check_one(job: Job) -> tuple[Job, Verdict]:
            target = _hiring_system_job(job)
            if target is not None:
                return job, await _ask_hiring_system(hiring_systems, target, sem)
            url = job.apply_url or job.job_url or ""
            if not url:
                return job, "ambiguous"
            if _is_anti_bot_host(url):
                # Systematic 403/429 from these hosts — verdict meaningless.
                return job, "skipped"
            verdict = await _probe(client, url, sem)
            return job, verdict

        results = await asyncio.gather(*(check_one(j) for j in rows))

    expired = 0
    alive = 0
    opened = 0
    ambiguous = 0
    skipped = 0
    for job, verdict in results:
        job.last_checked_at = now
        if verdict == "dead":
            job.status = "expired"
            expired += 1
        elif verdict == "open":
            # The company's own job board lists it: as good as any source.
            job.last_seen_at = now
            opened += 1
        elif verdict == "alive":
            alive += 1
        elif verdict == "skipped":
            skipped += 1
        else:
            ambiguous += 1

    await db.commit()

    if expired:
        logger.info(
            "URL-verify batch: checked=%d expired=%d alive=%d open=%d ambiguous=%d skipped=%d",
            len(rows), expired, alive, opened, ambiguous, skipped,
        )

    return {
        "checked": len(rows),
        "expired": expired,
        "alive": alive,
        "open": opened,
        "ambiguous": ambiguous,
        "skipped": skipped,
        "has_more": len(rows) >= bounded,
    }
