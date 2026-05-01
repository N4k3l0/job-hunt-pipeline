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
# and reported as `timeout`. Sources run concurrently via asyncio.gather,
# so the function's total wall time is ~max(per-source) + a few seconds
# of overhead. We pick 50s — the curated source can do real work
# (fetch 65 companies + ingest hundreds of jobs + inline-score across
# users) and still leaves ~10s margin under Vercel's 60s ceiling.
PER_SOURCE_BUDGET_SECONDS = 50


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
    """Curated companies (highest-signal) + Arbeitnow, then a bounded
    quick-score pass for every user.

    Adzuna is temporarily disabled — their API has been returning 400s
    even on `api.adzuna.com/` itself. The runner code is still intact in
    `_run_adzuna_async`; flip it back on once Adzuna is back.
    """
    _verify_cron(authorization)

    from app.workers.discovery_tasks import (
        _run_arbeitnow_async, _run_curated_async, quick_score_all_users,
    )

    results = await _run_all_concurrent([
        ("curated", _run_curated_async),
        ("arbeitnow", _run_arbeitnow_async),
        # ("adzuna", _run_adzuna_async),  # disabled: upstream returning 400s
    ])
    scoring = await quick_score_all_users(per_user_timeout=10)
    return {"status": "complete", "results": results, "scoring": scoring}


@router.get("/discover-remote")
async def cron_discover_remote(authorization: str | None = Header(None)):
    """Run the remote-only sources concurrently with a per-source timeout.
    DailyRemote's Cloudflare-protected scrape is the most likely to stall;
    timing it out individually means the other sources still produce jobs."""
    _verify_cron(authorization)

    from app.workers.discovery_tasks import (
        _run_remoteok_async, _run_himalayas_async,
        _run_remotive_async, _run_weworkremotely_async,
        _run_dailyremote_async, quick_score_all_users,
    )

    # DailyRemote routes through Firecrawl now — Cloudflare blocks direct
    # serverless fetches. Scope is intentionally small (2 categories × 8
    # detail pages = 18 Firecrawl credits/run = ~540/month).
    results = await _run_all_concurrent([
        ("remoteok", _run_remoteok_async),
        ("himalayas", _run_himalayas_async),
        ("remotive", _run_remotive_async),
        ("weworkremotely", _run_weworkremotely_async),
        ("dailyremote", _run_dailyremote_async),
    ])
    scoring = await quick_score_all_users(per_user_timeout=10)
    return {"status": "complete", "results": results, "scoring": scoring}


@router.get("/score-backlog")
async def cron_score_backlog(
    authorization: str | None = Header(None),
    rescore_all: bool = False,
):
    """Score every unscored job for every user.

    Pass `?rescore_all=true` to wipe + recompute every score for every
    user — needed when scoring weights or the skill-overlap algorithm
    change so the inbox sort reflects the new model. Without that flag,
    the batch scorer skips jobs that already have a JobScore row.
    """
    _verify_cron(authorization)

    import asyncio
    from app.workers.scoring_tasks import _batch_score_async
    from app.workers.discovery_tasks import create_worker_session
    from app.models.user import User
    from sqlalchemy import select

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


@router.get("/stats")
async def cron_stats(authorization: str | None = Header(None)):
    """Quick visibility into what's actually in the DB. Used to answer
    'did the new jobs land?' without screen-sharing pgAdmin.

    Uses raw SQL with INTERVAL literals — far less fragile than fighting
    SQLAlchemy's type system to express '6 hours ago'."""
    _verify_cron(authorization)

    from sqlalchemy import select, func, text
    from app.workers.discovery_tasks import create_worker_session, _collect_all_keywords
    from app.models.job import Job
    from app.models.scoring import JobScore
    from app.models.user import User
    from app.models.candidate import CandidateProfile, CandidateSkill

    async with create_worker_session()() as db:
        # Visible jobs total
        total = (await db.execute(
            select(func.count(Job.id)).where(Job.status.notin_(["duplicate", "raw"]))
        )).scalar() or 0

        recent_6h = (await db.execute(text(
            "SELECT count(*) FROM jobs WHERE status NOT IN ('duplicate','raw') "
            "AND discovered_at > now() - interval '6 hours'"
        ))).scalar() or 0

        recent_24h = (await db.execute(text(
            "SELECT count(*) FROM jobs WHERE status NOT IN ('duplicate','raw') "
            "AND discovered_at > now() - interval '24 hours'"
        ))).scalar() or 0

        # Per-source counts in the last 6h
        src_rows = (await db.execute(text(
            "SELECT COALESCE(s.name,'manual') AS source, count(*) AS n "
            "FROM jobs j LEFT JOIN job_sources s ON s.id = j.source_id "
            "WHERE j.status NOT IN ('duplicate','raw') "
            "AND j.discovered_at > now() - interval '6 hours' "
            "GROUP BY 1 ORDER BY n DESC"
        ))).all()

        # Remote-type breakdown across all visible jobs
        remote_rows = (await db.execute(text(
            "SELECT COALESCE(remote_type,'unknown') AS r, count(*) AS n "
            "FROM jobs WHERE status NOT IN ('duplicate','raw') GROUP BY 1 ORDER BY n DESC"
        ))).all()

        # Visa sponsorship coverage — how many jobs in the DB actually have
        # the flag populated, true vs false vs null.
        visa_rows = (await db.execute(text(
            "SELECT CASE WHEN e.sponsorship_available IS TRUE THEN 'true' "
            "WHEN e.sponsorship_available IS FALSE THEN 'false' "
            "ELSE 'unknown' END AS flag, count(*) "
            "FROM jobs j LEFT JOIN job_entities e ON e.job_id = j.id "
            "WHERE j.status NOT IN ('duplicate','raw') GROUP BY 1"
        ))).all()

        # Scoring coverage on recent jobs (6h)
        scored_recent = (await db.execute(text(
            "SELECT count(*) FROM jobs j JOIN job_scores s ON s.job_id = j.id "
            "WHERE j.status NOT IN ('duplicate','raw') "
            "AND j.discovered_at > now() - interval '6 hours'"
        ))).scalar() or 0

        latest_ts = (await db.execute(select(func.max(Job.discovered_at)))).scalar()

        # Each user's target_roles + a sample of recent visible job titles
        # so the caller can spot-check whether the inbox should be showing
        # them or not.
        users_result = await db.execute(
            select(User.id, User.email,
                   CandidateProfile.id.label("profile_id"),
                   CandidateProfile.target_roles,
                   CandidateProfile.blocked_sources,
                   CandidateProfile.search_keywords,
                   CandidateProfile.remote_preference,
                   CandidateProfile.preferred_countries,
                   CandidateProfile.visa_statuses)
            .outerjoin(CandidateProfile, CandidateProfile.user_id == User.id)
        )
        users_info: list[dict] = []
        for (uid, email, profile_id, target_roles, blocked_sources, search_kw,
             remote_pref, pref_countries, visa_statuses) in users_result.all():
            # Pull skills grouped by category so we can see whether the
            # 'technical' / 'tool' filter is actually catching what the
            # user added.
            if profile_id:
                skills_rows = (await db.execute(
                    select(CandidateSkill.skill_name, CandidateSkill.category)
                    .where(CandidateSkill.profile_id == profile_id)
                )).all()
            else:
                skills_rows = []
            by_cat: dict[str, list[str]] = {}
            for name, cat in skills_rows:
                by_cat.setdefault(cat or "uncategorized", []).append(name)
            users_info.append({
                "email": email,
                "target_roles": target_roles or [],
                "blocked_sources": blocked_sources or [],
                "search_keywords": search_kw or [],
                "skills_by_category": by_cat,
                "skill_total": len(skills_rows),
                "remote_preference": remote_pref,
                "preferred_countries": pref_countries or [],
                "visa_statuses": visa_statuses or {},
            })

        # The actual keyword set we hand to discovery (RemoteOK/Himalayas/etc.)
        # — same code path the cron uses, run live so we see exactly what
        # the cron would see.
        try:
            discovery_keywords = await _collect_all_keywords()
        except Exception as e:
            discovery_keywords = [f"(failed: {e})"]

        # Sample of the 10 most recent visible job titles, regardless of user filter
        sample_rows = (await db.execute(text(
            "SELECT COALESCE(s.name,'manual') AS source, j.title, j.company "
            "FROM jobs j LEFT JOIN job_sources s ON s.id = j.source_id "
            "WHERE j.status NOT IN ('duplicate','raw') "
            "ORDER BY j.discovered_at DESC LIMIT 15"
        ))).all()
        sample = [
            {"source": s, "title": t, "company": c}
            for (s, t, c) in sample_rows
        ]

    return {
        "totals": {
            "all_visible": total,
            "discovered_last_6h": recent_6h,
            "discovered_last_24h": recent_24h,
            "scored_in_last_6h": scored_recent,
            "latest_discovered_at": latest_ts.isoformat() if latest_ts else None,
        },
        "by_source_last_6h": {row[0]: row[1] for row in src_rows},
        "by_remote_type": {row[0]: row[1] for row in remote_rows},
        "by_sponsorship_flag": {row[0]: row[1] for row in visa_rows},
        "users": users_info,
        "discovery_keyword_count": len(discovery_keywords) if isinstance(discovery_keywords, list) else 0,
        "discovery_keywords_sample": (
            sorted(discovery_keywords)[:60] if isinstance(discovery_keywords, list) else discovery_keywords
        ),
        "recent_titles_sample": sample,
    }


@router.get("/backfill-visa")
async def cron_backfill_visa(authorization: str | None = Header(None)):
    """Re-set the sponsorship_available flag on already-ingested Arbeitnow
    jobs whose JobEntity was created before we started capturing the
    visa_sponsorship field. Reads job.raw_content (str-repr of the source
    dict) to recover the flag — fragile but cheap and one-shot."""
    _verify_cron(authorization)

    import ast
    from sqlalchemy import select, update
    from app.workers.discovery_tasks import create_worker_session
    from app.models.job import Job, JobEntity, JobSource

    updated = 0
    inspected = 0
    async with create_worker_session()() as db:
        rows = (await db.execute(
            select(Job.id, Job.raw_content)
            .join(JobSource, JobSource.id == Job.source_id)
            .where(JobSource.name == "arbeitnow")
        )).all()
        for job_id, raw in rows:
            inspected += 1
            if not raw:
                continue
            try:
                d = ast.literal_eval(raw)
            except (ValueError, SyntaxError):
                continue
            flag = d.get("visa_sponsorship") if isinstance(d, dict) else None
            if not isinstance(flag, bool):
                continue
            # Upsert: update if entity exists, insert otherwise
            existing = (await db.execute(
                select(JobEntity).where(JobEntity.job_id == job_id)
            )).scalar_one_or_none()
            if existing is None:
                db.add(JobEntity(job_id=job_id, skills=[], requirements=[],
                                 keywords=[], sponsorship_available=flag))
            else:
                existing.sponsorship_available = flag
            updated += 1
        await db.commit()
    return {"inspected": inspected, "updated": updated}


@router.get("/rescue-dead-slugs")
async def cron_rescue_dead_slugs(authorization: str | None = Header(None)):
    """For each entry in curated_companies.json, probe every ATS with the
    declared slug AND a handful of derived slug variants. Reports which
    (ATS, slug) pairs actually return jobs — used to fix wrong guesses
    in the JSON without manually testing each one.

    This is intentionally slow (it makes ~9 probes per company). Don't
    call it from the daily cron — it's a one-shot diagnostic the human
    runs when curating the company list.
    """
    _verify_cron(authorization)

    import asyncio
    import json
    from pathlib import Path
    import re
    import httpx

    json_path = Path(__file__).parents[3] / "app" / "services" / "discovery" / "curated_companies.json"
    data = json.loads(json_path.read_text())
    # Probe entries we haven't verified yet, not the live list. The live
    # list is the cron's source of truth and shouldn't be churned.
    companies = data.get("to_probe") or []

    def slug_variants(name: str, given: str) -> list[str]:
        """Generate 3-4 candidate slugs from a company name + the
        existing slug we tried. Strip common corporate suffixes, try
        lowercase-no-punctuation, keep it tight."""
        out: list[str] = [given]
        n = (name or "").strip().lower()
        n = re.sub(r"\b(inc|llc|ltd|gmbh|co|corp)\.?\b", "", n)
        n = re.sub(r"[^a-z0-9]+", "-", n).strip("-")
        if n and n not in out:
            out.append(n)
        squashed = n.replace("-", "")
        if squashed and squashed not in out:
            out.append(squashed)
        # First-word-only as a fallback (e.g. "y combinator" → "y")
        first = (n.split("-") or [""])[0]
        if first and len(first) >= 3 and first not in out:
            out.append(first)
        return out

    async def probe_one(client: httpx.AsyncClient, ats: str, slug: str) -> int:
        """Return job count if the (ats, slug) is live, else 0."""
        try:
            if ats == "greenhouse":
                r = await client.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
                if r.status_code != 200:
                    return 0
                return len((r.json().get("jobs") or []))
            if ats == "lever":
                r = await client.get(
                    f"https://api.lever.co/v0/postings/{slug}",
                    params={"mode": "json"},
                )
                if r.status_code != 200:
                    return 0
                d = r.json()
                return len(d) if isinstance(d, list) else 0
            if ats == "ashby":
                r = await client.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
                if r.status_code != 200:
                    return 0
                return len((r.json().get("jobs") or []))
        except (httpx.HTTPError, ValueError):
            return 0
        return 0

    sem = asyncio.Semaphore(16)
    headers = {"User-Agent": "JobHuntPipeline/1.0 (rescue)", "Accept": "application/json"}

    async def rescue(client: httpx.AsyncClient, c: dict) -> dict:
        """Try every (ATS, variant) pair; return the best hit (highest
        job count) or None."""
        name = c.get("name") or ""
        given = c.get("slug") or ""
        original_ats = c.get("ats") or ""

        async with sem:
            best: dict | None = None
            for variant in slug_variants(name, given):
                for ats in ("greenhouse", "lever", "ashby"):
                    n = await probe_one(client, ats, variant)
                    if n > 0:
                        if best is None or n > best["jobs"]:
                            best = {"ats": ats, "slug": variant, "jobs": n}
            return {
                "name": name,
                "original": {"ats": original_ats, "slug": given},
                "best_hit": best,  # None if nothing worked
            }

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=3.0, read=5.0, write=3.0, pool=3.0),
        headers=headers,
    ) as client:
        rows = await asyncio.gather(*(rescue(client, c) for c in companies))

    rescued = [r for r in rows if r["best_hit"]]
    truly_dead = [r for r in rows if not r["best_hit"]]
    return {
        "total": len(rows),
        "rescued": len(rescued),
        "truly_dead": len(truly_dead),
        "rescued_companies": rescued,
        "truly_dead_companies": [r["name"] for r in truly_dead],
    }


@router.get("/debug-curated")
async def cron_debug_curated(authorization: str | None = Header(None)):
    """Per-company health probe: which slugs in curated_companies.json are
    live, how many jobs each returned. Used to prune dead slugs and add
    new ones intentionally."""
    _verify_cron(authorization)

    from app.services.discovery.curated_service import probe_companies
    rows = await probe_companies()
    live = [r for r in rows if r.get("jobs_returned", 0) > 0]
    dead = [r for r in rows if "error" in r or r.get("jobs_returned") == 0]
    summary = {
        "total": len(rows),
        "live": len(live),
        "dead": len(dead),
        "total_jobs": sum(r.get("jobs_returned", 0) for r in live),
    }
    # Sort: live first by job count desc, then dead alphabetically.
    live.sort(key=lambda r: r.get("jobs_returned", 0), reverse=True)
    dead.sort(key=lambda r: (r.get("name") or "").lower())
    return {"summary": summary, "live": live, "dead": dead}


@router.get("/debug-firecrawl")
async def cron_debug_firecrawl(authorization: str | None = Header(None)):
    """One Firecrawl scrape against DailyRemote, with the raw response so
    we can see WHY it's failing. The runner reports 'ok' even when every
    underlying call returns empty string, so we have to peek directly."""
    _verify_cron(authorization)

    import httpx
    from app.core.config import get_settings as _get_settings
    s = _get_settings()
    target = "https://dailyremote.com/remote-product-jobs"
    out: dict = {
        "firecrawl_key_present": bool(s.firecrawl_api_key),
        "firecrawl_key_len": len(s.firecrawl_api_key or ""),
        "target": target,
    }
    if not s.firecrawl_api_key:
        out["error"] = "FIRECRAWL_API_KEY env var is empty"
        return out

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            r = await client.post(
                "https://api.firecrawl.dev/v1/scrape",
                headers={
                    "Authorization": f"Bearer {s.firecrawl_api_key}",
                    "Content-Type": "application/json",
                },
                json={"url": target, "formats": ["rawHtml"]},
            )
            out["http_status"] = r.status_code
            out["response_preview"] = (r.text or "")[:600]
            try:
                data = r.json()
                raw = (data.get("data") or {}).get("rawHtml", "") or ""
                out["raw_html_size"] = len(raw)
                out["raw_html_head"] = raw[:300]
            except ValueError:
                out["json_parse_error"] = True
        except httpx.HTTPError as e:
            out["exception"] = f"{type(e).__name__}: {e}"
    return out


@router.get("/debug-dailyremote")
async def cron_debug_dailyremote(authorization: str | None = Header(None)):
    """Trace DailyRemote step by step: did Cloudflare let us in, did
    we extract job URLs, how many detail pages parsed, how many passed
    each filter? Cron secret protected."""
    _verify_cron(authorization)

    import asyncio
    import httpx
    from app.services.discovery import dailyremote_service as dr
    from app.services.discovery.eligibility import is_nigeria_friendly, matches_keywords
    from app.workers.discovery_tasks import _collect_all_keywords

    keywords = await _collect_all_keywords()
    keyword_set = set(keywords) if keywords else None

    headers = {
        "User-Agent": dr.USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }
    per_category: list[dict] = []
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers=headers) as client:
        for path in dr.CATEGORY_PATHS:
            entry: dict = {"category": path}
            try:
                listing = await client.get(f"{dr.BASE}{path}")
                entry["listing_status"] = listing.status_code
                entry["listing_size"] = len(listing.text or "")
            except httpx.HTTPError as e:
                entry["listing_error"] = f"{type(e).__name__}: {e}"
                per_category.append(entry)
                continue

            urls = dr._extract_job_urls(listing.text)[: dr.PER_CATEGORY_LIMIT]
            entry["urls_found"] = len(urls)
            entry["sample_url"] = urls[0] if urls else None

            # Try one detail page so we can see whether the JSON-LD parses
            if urls:
                try:
                    r = await client.get(f"{dr.BASE}{urls[0]}")
                    entry["detail_status"] = r.status_code
                    entry["detail_size"] = len(r.text or "")
                    posting = dr._parse_job_page(r.text, urls[0])
                    entry["parsed"] = bool(posting)
                    if posting:
                        entry["sample_title"] = posting.get("title")
                        entry["sample_company"] = posting.get("company")
                        entry["sample_location"] = posting.get("location")
                        entry["passed_keyword_filter"] = matches_keywords(
                            f"{posting.get('title','')} {posting.get('raw_description','')}",
                            keyword_set,
                        )
                        entry["passed_nigeria_filter"] = is_nigeria_friendly(
                            candidate_required_location=posting.get("location"),
                            description=posting.get("raw_description"),
                        )
                except httpx.HTTPError as e:
                    entry["detail_error"] = f"{type(e).__name__}: {e}"

            # Full pass: count how many of the 25 URLs survive each filter
            if urls:
                kept_keyword = 0
                kept_nigeria = 0
                kept_both = 0
                detail_results = await asyncio.gather(*(
                    client.get(f"{dr.BASE}{u}") for u in urls
                ), return_exceptions=True)
                for u, resp in zip(urls, detail_results):
                    if isinstance(resp, Exception):
                        continue
                    posting = dr._parse_job_page(resp.text, u)
                    if not posting:
                        continue
                    title = posting.get("title", "")
                    desc = posting.get("raw_description", "")
                    loc = posting.get("location", "")
                    pk = matches_keywords(f"{title} {desc}", keyword_set)
                    pn = is_nigeria_friendly(
                        candidate_required_location=loc, description=desc,
                    )
                    if pk: kept_keyword += 1
                    if pn is not False: kept_nigeria += 1
                    if pk and pn is not False: kept_both += 1
                entry["full_pass"] = {
                    "fetched": len(detail_results),
                    "passed_keyword_filter": kept_keyword,
                    "passed_nigeria_filter": kept_nigeria,
                    "passed_both": kept_both,
                }

            per_category.append(entry)

    return {
        "user_agent": dr.USER_AGENT[:60] + "...",
        "keywords_in_use": len(keywords),
        "per_category": per_category,
    }


@router.get("/discover-slow")
async def cron_discover_slow(authorization: str | None = Header(None)):
    """Run the heavier scraper-based sources on their own cron tick.

    Crossover: up to ~30 Firecrawl scrapes per run; can take 30-50s by itself.
    """
    _verify_cron(authorization)

    from app.workers.discovery_tasks import _run_crossover_async
    n, status = await _run_one("crossover", _run_crossover_async)
    return {"status": "complete", "results": {n: status}}
