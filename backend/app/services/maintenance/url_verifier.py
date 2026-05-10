"""Probe job apply URLs and mark confirmed-dead postings as expired.

Used both by:
  - The admin 'Verify URLs' button (interactive, large batches)
  - The daily cron (small piggyback batch — 25–50 jobs/day so the whole
    catalogue gets a pass within a few weeks without burning a Vercel
    cron slot we don't have)

Conservative on purpose — only flips status to 'expired' on a definitive
HTTP 404 / 410. Any other response (200, 30x, 403, 5xx, timeout, network
error) is treated as 'don't know' and the row is left alone. We never
false-positive a live posting.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Literal

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job

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

Verdict = Literal["dead", "alive", "ambiguous"]


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


async def verify_batch(
    db: AsyncSession,
    *,
    limit: int = 100,
    age_days_min: int = 0,
    concurrency: int = 8,
    timeout_s: float = 4.0,
) -> dict[str, int | bool]:
    """Probe up to `limit` unapplied jobs, oldest first, and mark
    confirmed-dead ones as expired. Returns counters + has_more.

    The cron caller passes a small `limit` (25–50) so the whole pass
    fits inside the leftover budget after discovery/scoring runs.
    """
    from sqlalchemy import func as sa_func, text

    bounded = min(max(int(limit), 1), 250)

    q = (
        select(Job)
        .where(
            Job.status.in_(PRE_APPLIED_STATUSES),
            (Job.apply_url.is_not(None)) | (Job.job_url.is_not(None)),
        )
        .order_by(Job.discovered_at.asc().nulls_first())
        .limit(bounded)
    )
    if age_days_min > 0:
        q = q.where(Job.discovered_at < sa_func.now() - text(f"interval '{int(age_days_min)} days'"))

    rows = (await db.execute(q)).scalars().all()
    if not rows:
        return {"checked": 0, "expired": 0, "alive": 0, "ambiguous": 0, "has_more": False}

    sem = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=3.0, read=timeout_s, write=3.0, pool=3.0),
        follow_redirects=True,
    ) as client:
        async def check_one(job: Job) -> tuple[Job, Verdict]:
            url = job.apply_url or job.job_url or ""
            verdict = await _probe(client, url, sem) if url else "ambiguous"
            return job, verdict

        results = await asyncio.gather(*(check_one(j) for j in rows))

    expired = 0
    alive = 0
    ambiguous = 0
    for job, verdict in results:
        if verdict == "dead":
            job.status = "expired"
            expired += 1
        elif verdict == "alive":
            alive += 1
        else:
            ambiguous += 1

    if expired:
        await db.commit()

    if expired:
        logger.info(
            "URL-verify batch: checked=%d expired=%d alive=%d ambiguous=%d",
            len(rows), expired, alive, ambiguous,
        )

    return {
        "checked": len(rows),
        "expired": expired,
        "alive": alive,
        "ambiguous": ambiguous,
        "has_more": len(rows) >= bounded,
    }
