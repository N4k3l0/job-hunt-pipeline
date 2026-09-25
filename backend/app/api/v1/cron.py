"""Scheduled work, called by the Railway scheduler (scripts/scheduled_tasks.py):
discovery, reading jobs with Claude, expiring closed jobs, LinkedIn alert
postings and top-match reviews.

Auth: callers send `Authorization: Bearer <CRON_SECRET>`. Without
CRON_SECRET every request is rejected, so a new deployment never exposes
these endpoints.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import os
import time

from fastapi import APIRouter, Header, HTTPException

router = APIRouter()
logger = logging.getLogger(__name__)

# Per-source budget: ANY single source taking longer than this is killed
# and reported as `timeout`. Sources run concurrently via asyncio.gather,
# so the function's total wall time is ~max(per-source) + a few seconds
# of overhead. We pick 50s — the curated source can do real work
# (fetch 65 companies + ingest hundreds of jobs + inline-score across
# users) and still leaves ~10s margin under Vercel's 60s ceiling.
PER_SOURCE_BUDGET_SECONDS = 50


def _verify_cron(authorization: str | None) -> None:
    """Reject any request that doesn't carry our cron secret."""
    expected = os.environ.get("CRON_SECRET")
    if not expected:
        raise HTTPException(status_code=503, detail="CRON_SECRET is not configured")
    if not authorization or not hmac.compare_digest(
        authorization.encode(), f"Bearer {expected}".encode()
    ):
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
    """Curated companies (highest-signal) + Arbeitnow + JSearch, then a
    bounded quick-score pass for every user. All runners are awaited
    concurrently — slow / failing sources can't starve fast ones, and each
    runner wraps its own try/except so one failing source doesn't kill the
    whole cron tick.
    """
    _verify_cron(authorization)

    from app.workers.discovery_tasks import (
        _run_arbeitnow_async, _run_curated_async,
        _run_jsearch_async, quick_score_all_users,
    )

    # JSearch wired in — RapidAPI host responds 401 with proper error
    # message (API alive), works if JSEARCH_RAPIDAPI_KEY env var is set.
    results = await _run_all_concurrent([
        ("curated", _run_curated_async),
        ("arbeitnow", _run_arbeitnow_async),
        ("jsearch", _run_jsearch_async),
    ])
    scoring = await quick_score_all_users(per_user_timeout=10)

    # Piggyback URL verification on the daily cron — Vercel Hobby caps
    # at 2 cron slots and both are used for discovery. Probing 30 jobs/
    # day (oldest first) lets the whole catalogue get a pass within
    # ~6 weeks while costing only ~5–10 s of leftover budget. Wrapped
    # in a 15 s asyncio timeout + try/except so a slow probe can't take
    # the cron run down. Same logic the admin 'Verify URLs' button uses.
    verify: dict[str, object] = {"status": "skipped"}
    try:
        from app.services.maintenance.url_verifier import verify_batch
        from app.workers.discovery_tasks import create_worker_session
        async def _do_verify():
            async with create_worker_session()() as v_db:
                return await verify_batch(v_db, limit=30, timeout_s=3.0)
        result = await asyncio.wait_for(_do_verify(), timeout=15)
        verify = {"status": "ok", **result}
    except asyncio.TimeoutError:
        verify = {"status": "timeout after 15s"}
    except Exception as e:  # noqa: BLE001
        logger.warning("URL-verify piggyback failed: %s", e)
        verify = {"status": f"error: {type(e).__name__}: {e}"}

    return {"status": "complete", "results": results, "scoring": scoring, "verify": verify}


@router.get("/discover-remote")
async def cron_discover_remote(authorization: str | None = Header(None)):
    """Run the remote-only sources concurrently with a per-source timeout.
    DailyRemote's Cloudflare-protected scrape is the most likely to stall;
    timing it out individually means the other sources still produce jobs."""
    _verify_cron(authorization)

    from app.workers.discovery_tasks import (
        _run_remoteok_async, _run_himalayas_async,
        _run_remotive_async, _run_weworkremotely_async,
        _run_undutchables_async,
        _run_workingnomads_async,
        _run_wellfound_async, _run_jobberman_async,
        _run_myjobmag_async, quick_score_all_users,
    )

    # DailyRemote is off: since 2026-09 its job pages hide the company
    # ("[Hidden Company]") and no longer carry the JobPosting data the
    # parser reads, so every run fetched pages and found nothing.
    # Undutchables adds NL-specialist recruiter supply.
    results = await _run_all_concurrent([
        ("remoteok", _run_remoteok_async),
        ("himalayas", _run_himalayas_async),
        ("remotive", _run_remotive_async),
        ("weworkremotely", _run_weworkremotely_async),
        ("undutchables", _run_undutchables_async),
        ("workingnomads", _run_workingnomads_async),
        # arc.dev removed 2026-05 — JS-only job details, see auth.py
        # source-health comment. Lives in /discover-slow as manual.
        ("wellfound", _run_wellfound_async),
        ("jobberman", _run_jobberman_async),
        ("myjobmag", _run_myjobmag_async),
    ])
    scoring = await quick_score_all_users(per_user_timeout=10)
    return {"status": "complete", "results": results, "scoring": scoring}


@router.get("/score-backlog")
async def cron_score_backlog(
    authorization: str | None = Header(None),
    rescore_all: bool = False,
    user_id: str | None = None,
):
    """Score every unscored job for every user, or just `user_id`.

    Pass `?rescore_all=true` to wipe + recompute every score — needed when
    scoring weights or the algorithm change so the inbox sort reflects the
    new model. A full rescore of one user takes most of the 60s function
    limit, so call it once per user with `user_id`. Without the flag, the
    batch scorer skips jobs that already have a JobScore row.
    """
    _verify_cron(authorization)

    import asyncio
    from app.workers.scoring_tasks import _batch_score_async
    from app.workers.discovery_tasks import create_worker_session
    from app.models.user import User
    from sqlalchemy import select

    if user_id:
        user_ids = [user_id]
    else:
        async with create_worker_session()() as db:
            users_result = await db.execute(select(User.id))
            user_ids = [str(row[0]) for row in users_result.all()]

    results: dict[str, str] = {}
    for uid in user_ids:
        import time
        started = time.monotonic()
        try:
            await asyncio.wait_for(
                _batch_score_async(uid, rescore_all=rescore_all),
                timeout=45,
            )
            results[uid] = f"ok ({time.monotonic() - started:.1f}s)"
        except asyncio.TimeoutError:
            results[uid] = f"timeout after {time.monotonic() - started:.0f}s"
        except Exception as e:  # noqa: BLE001
            results[uid] = f"error: {type(e).__name__}: {e}"
    return {"status": "complete", "results": results, "rescore_all": rescore_all}


@router.get("/enrich")
async def cron_enrich(
    authorization: str | None = Header(None),
    limit: int = 25,
    max_age_days: int = 30,
):
    """Read up to `limit` recent jobs with the extraction model, then
    rescore them for every user. Meant to be called on a schedule until
    `pending` reaches 0; each call stays inside the 60s function limit.

    Cost: roughly $0.004 per job read (Claude Haiku 4.5)."""
    _verify_cron(authorization)

    from datetime import datetime, timedelta, timezone
    from sqlalchemy import func, or_, select
    from app.core.database import create_worker_session
    from app.models.job import Job, JobEntity
    from app.services.enrichment.job_enricher import enrich_pending_jobs
    from app.workers.scoring_tasks import rescore_jobs_for_all_users

    limit = max(1, min(limit, 60))
    result = await enrich_pending_jobs(limit=limit, max_age_days=max_age_days, time_budget_seconds=35)
    rescored = await rescore_jobs_for_all_users(result.job_ids)

    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    async with create_worker_session()() as db:
        pending = (await db.execute(
            select(func.count(Job.id))
            .outerjoin(JobEntity, JobEntity.job_id == Job.id)
            .where(
                Job.status.notin_(["duplicate", "raw", "expired", "dismissed"]),
                Job.discovered_at >= cutoff,
                or_(JobEntity.id.is_(None), JobEntity.enriched_at.is_(None)),
            )
        )).scalar() or 0

    return {
        "selected": result.selected,
        "enriched": result.enriched,
        "skipped_short": result.skipped_short,
        "failed": result.failed,
        "errors": result.errors[:5],
        "scores_updated": rescored,
        "pending": pending,
    }


@router.get("/expire-stale")
async def cron_expire_stale(
    authorization: str | None = Header(None),
    dry_run: bool = False,
    verify_limit: int = 40,
):
    """Expire closed jobs: ones gone from full company boards, ones that
    are old and no longer listed anywhere, and (unless dry_run) a batch of
    links that now return 404/410. `dry_run=true` only reports counts."""
    _verify_cron(authorization)

    from app.core.database import create_worker_session
    from app.services.maintenance.job_expiry import expire_stale_jobs
    from app.services.maintenance.url_verifier import verify_batch

    async with create_worker_session()() as db:
        outcome = await expire_stale_jobs(db, dry_run=dry_run)

    if not dry_run and verify_limit > 0:
        try:
            async with create_worker_session()() as db:
                outcome["link_check"] = await asyncio.wait_for(
                    verify_batch(db, limit=min(verify_limit, 100), timeout_s=4.0), timeout=35
                )
        except asyncio.TimeoutError:
            outcome["link_check"] = "timeout"
    return outcome


@router.get("/job-alert-details")
async def cron_job_alert_details(
    authorization: str | None = Header(None),
    limit: int = 10,
):
    """Find full postings for jobs added from LinkedIn alert emails on the
    companies' own job boards, then rescore the ones that got a
    description. Free: public job board listings only."""
    _verify_cron(authorization)

    from app.services.job_alerts.details import fill_alert_job_details
    from app.workers.scoring_tasks import rescore_jobs_for_all_users

    result = await fill_alert_job_details(limit=max(1, min(limit, 30)))
    rescored = await rescore_jobs_for_all_users(result.job_ids)
    return {
        "checked": result.checked,
        "postings_found": result.postings_found,
        "descriptions_found": result.descriptions_found,
        "scores_updated": rescored,
    }


@router.get("/send-digests")
async def cron_send_digests(authorization: str | None = Header(None)):
    """Send the daily email to everyone who wants it and hasn't had today's.
    Does nothing before DIGEST_HOUR_UTC or while email isn't set up, so it's
    safe on every scheduler run."""
    _verify_cron(authorization)

    from app.services.notifications.digest import send_due_digests

    outcome = await send_due_digests()
    outcome["errors"] = outcome["errors"][:5]
    return outcome


@router.get("/review-top-matches")
async def cron_review_top_matches(
    authorization: str | None = Header(None),
    per_user_daily: int = 3,
    min_score: float = 70.0,
):
    """Run the AI review on each user's best new matches, up to
    `per_user_daily` a day per user. Cost: roughly $0.04 per review
    (Claude Sonnet 5)."""
    _verify_cron(authorization)

    from app.services.scoring.top_match_review import review_top_matches

    outcome = await review_top_matches(
        per_user_daily=max(0, min(per_user_daily, 10)),
        min_score=min_score,
    )
    outcome["errors"] = outcome["errors"][:5]
    return outcome
