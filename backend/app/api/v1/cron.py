"""Vercel Cron entry points for scheduled job discovery.

Split into two endpoints because Vercel Hobby caps function execution at
60 seconds. The "fast" sources (API / RSS) run in one tick; Crossover (which
does many Firecrawl scrapes) runs in its own tick.

Auth: Vercel sends `Authorization: Bearer <CRON_SECRET>` if you set the
CRON_SECRET env var in the Vercel project settings. We require it whenever
the env var is set.
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Header, HTTPException

router = APIRouter()
logger = logging.getLogger(__name__)


def _verify_cron(authorization: str | None) -> None:
    """Reject any request that doesn't carry our cron secret. Skipped in dev
    if no secret is configured."""
    expected = os.environ.get("CRON_SECRET")
    if not expected:
        return  # local dev — no auth required
    if not authorization or authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="Invalid cron secret")


async def _run_one(name: str, runner) -> tuple[str, str]:
    try:
        await runner()
        return name, "ok"
    except Exception as e:  # noqa: BLE001 — log + continue, never let one source kill the rest
        logger.error("Cron discovery '%s' failed: %s", name, e)
        return name, f"error: {type(e).__name__}: {e}"


@router.get("/discover-fast")
async def cron_discover_fast(authorization: str | None = Header(None)):
    """Run the heavy paginated sources (Adzuna across many countries +
    Arbeitnow with pagination). These two alone can approach the 60s limit."""
    _verify_cron(authorization)

    from app.workers.discovery_tasks import _run_adzuna_async, _run_arbeitnow_async

    results = {}
    for name, runner in [("adzuna", _run_adzuna_async), ("arbeitnow", _run_arbeitnow_async)]:
        n, status = await _run_one(name, runner)
        results[n] = status
    return {"status": "complete", "results": results}


@router.get("/discover-remote")
async def cron_discover_remote(authorization: str | None = Header(None)):
    """Run the remote-only single-call sources. Fast enough to fit together."""
    _verify_cron(authorization)

    from app.workers.discovery_tasks import (
        _run_remoteok_async, _run_himalayas_async,
        _run_remotive_async, _run_weworkremotely_async,
        _run_dailyremote_async,
    )

    runners = [
        ("remoteok", _run_remoteok_async),
        ("himalayas", _run_himalayas_async),
        ("remotive", _run_remotive_async),
        ("weworkremotely", _run_weworkremotely_async),
        ("dailyremote", _run_dailyremote_async),
    ]
    results = {}
    for name, runner in runners:
        n, status = await _run_one(name, runner)
        results[n] = status
    return {"status": "complete", "results": results}


@router.get("/discover-slow")
async def cron_discover_slow(authorization: str | None = Header(None)):
    """Run the heavier scraper-based sources on their own cron tick.

    Crossover: up to ~30 Firecrawl scrapes per run; can take 30-50s by itself.
    """
    _verify_cron(authorization)

    from app.workers.discovery_tasks import _run_crossover_async
    n, status = await _run_one("crossover", _run_crossover_async)
    return {"status": "complete", "results": {n: status}}
