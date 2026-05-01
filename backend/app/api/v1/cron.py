"""Vercel Cron entry points for scheduled job discovery.

Split into two endpoints because Vercel Hobby caps function execution at
60 seconds. The "fast" sources (API / RSS) run in one tick; Crossover (which
does many Firecrawl scrapes) runs in its own tick.

Auth: Vercel sends `Authorization: Bearer <CRON_SECRET>` if you set the
CRON_SECRET env var in the Vercel project settings. We require it whenever
the env var is set.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

from fastapi import APIRouter, Header, HTTPException

router = APIRouter()
logger = logging.getLogger(__name__)

# Per-source budget: ANY single source taking longer than this is killed
# and reported as `timeout`. Picked so the SLOWEST source still leaves
# room for the rest under Vercel's 60s function ceiling. With concurrent
# execution (asyncio.gather) the total wall time is ~max(per-source
# duration), but we keep a hard cap as a safety net in case one source
# falls into a redirect loop or rate-limit backoff.
PER_SOURCE_BUDGET_SECONDS = 35


def _verify_cron(authorization: str | None) -> None:
    """Reject any request that doesn't carry our cron secret. Skipped in dev
    if no secret is configured."""
    expected = os.environ.get("CRON_SECRET")
    if not expected:
        return  # local dev — no auth required
    if not authorization or authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="Invalid cron secret")


async def _run_one(name: str, runner) -> tuple[str, str]:
    """Run a single source under a per-source timeout, capturing the outcome
    so the caller can see exactly which sources hung vs errored vs succeeded.
    Failures (errors AND timeouts) never propagate — one bad source must not
    take the whole cron run down."""
    started = time.monotonic()
    try:
        await asyncio.wait_for(runner(), timeout=PER_SOURCE_BUDGET_SECONDS)
        elapsed = time.monotonic() - started
        logger.info("Cron source '%s' ok in %.1fs", name, elapsed)
        return name, f"ok ({elapsed:.1f}s)"
    except asyncio.TimeoutError:
        elapsed = time.monotonic() - started
        logger.error("Cron source '%s' TIMED OUT after %.1fs", name, elapsed)
        return name, f"timeout after {elapsed:.0f}s"
    except Exception as e:  # noqa: BLE001
        elapsed = time.monotonic() - started
        logger.error("Cron source '%s' failed in %.1fs: %s", name, elapsed, e)
        return name, f"error in {elapsed:.0f}s: {type(e).__name__}: {e}"


async def _run_all_concurrent(runners: list[tuple[str, callable]]) -> dict[str, str]:
    """Run every source concurrently. Total wall time becomes
    ~max(per-source duration), and one slow source can't starve the others.
    """
    coros = [_run_one(name, runner) for name, runner in runners]
    pairs = await asyncio.gather(*coros)
    return dict(pairs)


@router.get("/discover-fast")
async def cron_discover_fast(authorization: str | None = Header(None)):
    """Adzuna + Arbeitnow run concurrently. Each is capped at the per-source
    budget so neither can starve the other — and Adzuna itself parallelises
    its country fan-out internally."""
    _verify_cron(authorization)

    from app.workers.discovery_tasks import _run_adzuna_async, _run_arbeitnow_async

    results = await _run_all_concurrent([
        ("adzuna", _run_adzuna_async),
        ("arbeitnow", _run_arbeitnow_async),
    ])
    return {"status": "complete", "results": results}


@router.get("/discover-remote")
async def cron_discover_remote(authorization: str | None = Header(None)):
    """Run the remote-only sources concurrently with a per-source timeout.
    DailyRemote's Cloudflare-protected scrape is the most likely to stall;
    timing it out individually means the other sources still produce jobs."""
    _verify_cron(authorization)

    from app.workers.discovery_tasks import (
        _run_remoteok_async, _run_himalayas_async,
        _run_remotive_async, _run_weworkremotely_async,
        _run_dailyremote_async,
    )

    results = await _run_all_concurrent([
        ("remoteok", _run_remoteok_async),
        ("himalayas", _run_himalayas_async),
        ("remotive", _run_remotive_async),
        ("weworkremotely", _run_weworkremotely_async),
        ("dailyremote", _run_dailyremote_async),
    ])
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
