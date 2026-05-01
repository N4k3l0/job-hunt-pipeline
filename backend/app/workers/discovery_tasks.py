import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.workers.celery_app import celery_app
from app.core.database import create_worker_session
from app.models.job import Job, JobEntity, JobSource
from app.models.user import User
from app.services.parsing.normalizer import (
    compute_canonical_hash,
    extract_city,
    normalize_country,
    classify_remote,
    get_or_create_source,
    normalize_url,
)
from app.services.deduplication.dedup_service import check_duplicate

logger = logging.getLogger(__name__)


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _ingest_raw_jobs(jobs: list[dict]):
    """Process a batch of raw job dicts through the pipeline.

    Pipeline: bulk pre-filter → per-job dedup → normalize → store.
    Scoring is NOT done here — the cron handler calls _quick_score after
    all sources finish so this function stays cheap and bounded.
    """
    if not jobs:
        return

    # Bulk pre-filter: load every existing canonical_hash + job_url in
    # one query, then short-circuit duplicates in memory before the
    # expensive per-row check_duplicate (4-5 DB queries each). With the
    # curated source landing 1000+ candidates per run, this turns a
    # 30-50s loop into ~2s.
    async with create_worker_session()() as db:
        seen_rows = await db.execute(
            select(Job.canonical_hash, Job.job_url).where(
                Job.status.notin_(["raw"])
            )
        )
        existing_hashes: set[str] = set()
        existing_urls: set[str] = set()
        for h, u in seen_rows.all():
            if h:
                existing_hashes.add(h)
            if u:
                existing_urls.add(u)

    pre_filtered: list[dict] = []
    pre_skipped = 0
    for raw in jobs:
        # Compute the same fingerprint we'd compute downstream.
        company = raw.get("company", "Unknown")
        title = raw.get("title", "")
        location = raw.get("location")
        country = normalize_country(raw.get("country"))
        city = extract_city(location)
        canonical_hash = compute_canonical_hash(company, title, city, country)
        normalized_url = normalize_url(raw.get("job_url"))
        if canonical_hash in existing_hashes or (
            normalized_url and normalized_url in existing_urls
        ):
            pre_skipped += 1
            continue
        # Stash the precomputed values so we don't recompute them.
        raw["_canonical_hash"] = canonical_hash
        raw["_normalized_url"] = normalized_url
        pre_filtered.append(raw)

    logger.info(
        "Bulk pre-filter: %d candidates → %d to ingest (%d known dups skipped)",
        len(jobs), len(pre_filtered), pre_skipped,
    )

    async with create_worker_session()() as db:
        stored = 0
        skipped = 0

        for raw in pre_filtered:
            try:
                company = raw.get("company", "Unknown")
                title = raw.get("title", "")
                location = raw.get("location")
                country = normalize_country(raw.get("country"))
                city = extract_city(location)
                external_id = raw.get("external_id")

                # Resolve source first so we can dedup on (source, external_id).
                source = await get_or_create_source(
                    db,
                    raw.get("source_name", "unknown"),
                    raw.get("source_type", "api"),
                )

                # Reuse the values we already computed in pre-filter rather
                # than recomputing the canonical hash and URL.
                normalized_url = raw.get("_normalized_url")
                canonical_hash = raw.get("_canonical_hash")

                # Bulk pre-filter already cleared canonical_hash + URL
                # collisions in O(1). Skipping the per-row `check_duplicate`
                # call (which fires 4-5 extra DB queries for source/external
                # ID matches and description similarity) keeps the cron
                # under budget — at the cost of slightly looser dedup on
                # the (source_id, external_id) and Jaccard-similarity axes.
                # In practice ATS sources have stable external_ids so this
                # is safe; if cross-source near-duplicates start sneaking
                # in we can re-enable for the affected sources.

                remote_type = (
                    raw.get("remote_type")
                    or classify_remote(location)
                    or classify_remote(title)
                    or classify_remote(raw.get("raw_description"), is_description=True)
                )

                # Create job
                job = Job(
                    external_id=external_id,
                    source_id=source.id,
                    company=company,
                    title=title,
                    location=location,
                    country=country,
                    remote_type=remote_type,
                    job_url=normalized_url,
                    apply_url=raw.get("apply_url"),
                    salary_text=raw.get("salary_text"),
                    salary_min=raw.get("salary_min"),
                    salary_max=raw.get("salary_max"),
                    salary_currency=raw.get("salary_currency"),
                    raw_description=raw.get("raw_description"),
                    raw_content=str(raw),
                    employment_type=raw.get("employment_type"),
                    seniority=raw.get("seniority"),
                    canonical_hash=canonical_hash,
                    status="enriched",
                    parsed_at=datetime.now(timezone.utc),
                )
                db.add(job)
                await db.flush()

                # If we have description content, create basic entities.
                # Capture the visa-sponsorship flag too — Arbeitnow is the
                # only source that explicitly exposes it today, but if other
                # sources start returning it we want it without another
                # plumbing change.
                desc = raw.get("raw_description", "")
                visa_flag = raw.get("visa_sponsorship")
                if desc or visa_flag is not None:
                    entities = JobEntity(
                        job_id=job.id,
                        skills=raw.get("tags", []),
                        requirements=[],
                        keywords=[],
                        sponsorship_available=visa_flag if isinstance(visa_flag, bool) else None,
                    )
                    db.add(entities)

                stored += 1

            except Exception as e:
                logger.error("Failed to ingest job '%s': %s", raw.get("title"), e)
                continue

        await db.commit()
        logger.info("Ingestion complete: %d stored, %d duplicates skipped", stored, skipped)


async def quick_score_all_users(per_user_timeout: int = 12) -> dict[str, str]:
    """Run a single bounded scoring pass for every user, in parallel.

    Called by cron handlers AFTER their sources finish, so ingest stays
    cheap and scoring is its own budget. Each user's pass is capped by
    the batch scorer (limit 300 newest unscored), and the wait_for here
    caps wall time per user — together they keep a misbehaving user from
    starving the others.
    """
    import asyncio
    import time
    from app.workers.scoring_tasks import _batch_score_async
    from app.models.user import User

    async with create_worker_session()() as db:
        users_result = await db.execute(select(User.id))
        user_ids = [str(row[0]) for row in users_result.all()]

    async def score_one(uid: str) -> tuple[str, str]:
        started = time.monotonic()
        try:
            await asyncio.wait_for(
                _batch_score_async(uid, rescore_all=False),
                timeout=per_user_timeout,
            )
            return uid, f"ok ({time.monotonic() - started:.1f}s)"
        except asyncio.TimeoutError:
            return uid, f"timeout after {time.monotonic() - started:.0f}s"
        except Exception as e:  # noqa: BLE001
            return uid, f"error: {type(e).__name__}: {e}"

    results = await asyncio.gather(*(score_one(uid) for uid in user_ids))
    return dict(results)


# ── Apify ────────────────────────────────────────────────────────────────────


@celery_app.task(
    name="app.workers.discovery_tasks.process_apify_results",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def process_apify_results(self, actor_run_id: str, actor_type: str = "linkedin"):
    """Fetch results from an Apify actor run and process them."""
    try:
        _run_async(_process_apify_async(actor_run_id, actor_type))
    except Exception as exc:
        logger.error("Apify processing failed for run %s: %s", actor_run_id, exc)
        raise self.retry(exc=exc)


async def _process_apify_async(actor_run_id: str, actor_type: str):
    from app.services.discovery.apify_service import fetch_dataset_items, ACTOR_NORMALIZERS

    items = await fetch_dataset_items(actor_run_id)
    if not items:
        logger.warning("No items found for Apify run %s", actor_run_id)
        return

    normalizer = ACTOR_NORMALIZERS.get(actor_type)
    if not normalizer:
        logger.error("Unknown actor type: %s", actor_type)
        return

    normalized = [normalizer(item) for item in items]
    await _ingest_raw_jobs(normalized)


# ── Keyword Collection ────────────────────────────────────────────────────────


async def _collect_all_keywords() -> list[str]:
    """Collect search keywords from all users' profiles.

    Combines:
      - custom `search_keywords` (free-text user input)
      - `target_roles` (e.g. "AI Engineer")
      - `candidate_skills` rows where category is `technical` or `tool`
        (e.g. "Python", "LangChain", "Figma") — the strongest signal for
        whether a posting is actually a fit for this user

    Skills are short, concrete, and the same words employers put in their
    job descriptions, which makes them the most reliable expansion of the
    search beyond the role title alone.
    """
    from app.models.candidate import CandidateProfile, CandidateSkill

    async with create_worker_session()() as db:
        # Profiles: search_keywords + target_roles
        prof_result = await db.execute(
            select(CandidateProfile.search_keywords, CandidateProfile.target_roles)
        )
        all_keywords: set[str] = set()
        for search_kw, target_roles in prof_result:
            if search_kw:
                for kw in search_kw:
                    all_keywords.add(kw.strip().lower())
            if target_roles:
                for role in target_roles:
                    all_keywords.add(role.strip().lower())

        # Skills: pull technical + tool entries across every profile
        skill_result = await db.execute(
            select(CandidateSkill.skill_name).where(
                CandidateSkill.category.in_(("technical", "tool"))
            )
        )
        for (skill_name,) in skill_result:
            if skill_name:
                cleaned = skill_name.strip().lower()
                # Single letters / pure punctuation slip in if a user types
                # "C" or "+"; both would explode aggregator queries with noise.
                if len(cleaned) >= 2:
                    all_keywords.add(cleaned)

    keywords = list(all_keywords)
    logger.info(
        "Collected %d unique search keywords (roles + skills) from all users: %s",
        len(keywords), keywords,
    )
    return keywords


# ── Adzuna ───────────────────────────────────────────────────────────────────


@celery_app.task(name="app.workers.discovery_tasks.run_adzuna_discovery")
def run_adzuna_discovery():
    """Run scheduled Adzuna API discovery across all target countries."""
    _run_async(_run_adzuna_async())


async def _run_adzuna_async():
    """Adzuna's free tier rate-limits aggressively (~25 req/min). With
    8 countries × N keywords × concurrent fan-out we'd hit that limit
    instantly and start eating timeouts.

    Constraints we enforce here:
      - Fixed set of 3 broad keywords (matches what aggregator full-text
        search actually rewards). Per-user filtering happens at the
        scoring/inbox layer, not by fanning out the discovery query.
      - Concurrent country fan-out throttled with a semaphore to 3 at
        a time → at most 9 in-flight Adzuna calls. Stays inside their
        rate limit, total wall time roughly ceil(8/3) × per_country.
    """
    import asyncio
    from app.services.discovery.adzuna_service import fetch_jobs, ADZUNA_COUNTRIES

    # Fixed keyword set — broad enough to surface roles for both AI and PM
    # users. Skills/role-specific filtering is applied later in the pipeline,
    # not at the Adzuna query layer.
    ADZUNA_KEYWORDS = ["product manager", "ai engineer", "automation"]
    sem = asyncio.Semaphore(3)

    async def run_country(iso: str, code: str) -> list[dict]:
        async with sem:
            try:
                return await fetch_jobs(country_code=code, keywords=ADZUNA_KEYWORDS)
            except Exception as e:
                logger.error("Adzuna discovery failed for %s: %s", iso, e)
                return []

    batches = await asyncio.gather(*[
        run_country(iso, code) for iso, code in ADZUNA_COUNTRIES.items()
    ])
    all_jobs = [j for batch in batches for j in batch]
    if all_jobs:
        await _ingest_raw_jobs(all_jobs)


# ── RemoteOK ─────────────────────────────────────────────────────────────────


@celery_app.task(name="app.workers.discovery_tasks.run_remoteok_discovery")
def run_remoteok_discovery():
    """Run scheduled RemoteOK API discovery."""
    _run_async(_run_remoteok_async())


async def _run_remoteok_async():
    from app.services.discovery.remoteok_service import fetch_jobs

    keywords = await _collect_all_keywords()
    try:
        jobs = await fetch_jobs(keywords=set(keywords) if keywords else None)
        if jobs:
            await _ingest_raw_jobs(jobs)
    except Exception as e:
        logger.error("RemoteOK discovery failed: %s", e)


# ── Arbeitnow ────────────────────────────────────────────────────────────────


@celery_app.task(name="app.workers.discovery_tasks.run_arbeitnow_discovery")
def run_arbeitnow_discovery():
    """Run scheduled Arbeitnow API discovery."""
    _run_async(_run_arbeitnow_async())


async def _run_arbeitnow_async():
    from app.services.discovery.arbeitnow_service import fetch_jobs

    keywords = await _collect_all_keywords()
    try:
        jobs = await fetch_jobs(
            visa_sponsorship=False,
            keywords=set(keywords) if keywords else None,
        )
        if jobs:
            await _ingest_raw_jobs(jobs)
    except Exception as e:
        logger.error("Arbeitnow discovery failed: %s", e)


# ── JSearch ──────────────────────────────────────────────────────────────────


@celery_app.task(name="app.workers.discovery_tasks.run_jsearch_discovery")
def run_jsearch_discovery():
    """Run scheduled JSearch API discovery."""
    _run_async(_run_jsearch_async())


async def _run_jsearch_async():
    from app.services.discovery.jsearch_service import fetch_jobs

    keywords = await _collect_all_keywords()
    try:
        jobs = await fetch_jobs(queries=keywords if keywords else None)
        if jobs:
            await _ingest_raw_jobs(jobs)
    except Exception as e:
        logger.error("JSearch discovery failed: %s", e)


# ── Himalayas (Nigeria-friendly remote board) ────────────────────────────────


@celery_app.task(name="app.workers.discovery_tasks.run_himalayas_discovery")
def run_himalayas_discovery():
    """Run scheduled Himalayas API discovery — biased toward Nigeria-eligible roles."""
    _run_async(_run_himalayas_async())


async def _run_himalayas_async():
    from app.services.discovery.himalayas_service import fetch_jobs

    keywords = await _collect_all_keywords()
    try:
        jobs = await fetch_jobs(keywords=set(keywords) if keywords else None)
        if jobs:
            await _ingest_raw_jobs(jobs)
    except Exception as e:
        logger.error("Himalayas discovery failed: %s", e)


# ── Remotive (Nigeria-friendly remote board) ─────────────────────────────────


@celery_app.task(name="app.workers.discovery_tasks.run_remotive_discovery")
def run_remotive_discovery():
    """Run scheduled Remotive API discovery — filters to candidate-location-friendly roles."""
    _run_async(_run_remotive_async())


async def _run_remotive_async():
    from app.services.discovery.remotive_service import fetch_jobs

    keywords = await _collect_all_keywords()
    try:
        jobs = await fetch_jobs(keywords=set(keywords) if keywords else None)
        if jobs:
            await _ingest_raw_jobs(jobs)
    except Exception as e:
        logger.error("Remotive discovery failed: %s", e)


# ── WeWorkRemotely (RSS) ─────────────────────────────────────────────────────


@celery_app.task(name="app.workers.discovery_tasks.run_weworkremotely_discovery")
def run_weworkremotely_discovery():
    """Run scheduled WeWorkRemotely RSS discovery."""
    _run_async(_run_weworkremotely_async())


async def _run_weworkremotely_async():
    from app.services.discovery.weworkremotely_service import fetch_jobs

    keywords = await _collect_all_keywords()
    try:
        jobs = await fetch_jobs(keywords=set(keywords) if keywords else None)
        if jobs:
            await _ingest_raw_jobs(jobs)
    except Exception as e:
        logger.error("WeWorkRemotely discovery failed: %s", e)


# ── Crossover (Firecrawl scrape; small, Nigeria-friendly catalog) ────────────


@celery_app.task(name="app.workers.discovery_tasks.run_crossover_discovery")
def run_crossover_discovery():
    """Run scheduled Crossover discovery via Firecrawl scraping."""
    _run_async(_run_crossover_async())


async def _run_crossover_async():
    from app.services.discovery.crossover_service import fetch_jobs
    from app.services.parsing.normalizer import normalize_url

    keywords = await _collect_all_keywords()

    # Pull URLs we already have for Crossover and skip them — saves Firecrawl
    # credits since the catalog moves slowly.
    skip_urls: set[str] = set()
    async with create_worker_session()() as db:
        result = await db.execute(
            select(Job.job_url).join(JobSource, Job.source_id == JobSource.id)
            .where(JobSource.name == "crossover", Job.job_url.is_not(None))
        )
        for row in result.all():
            normalized = normalize_url(row[0])
            if normalized:
                skip_urls.add(normalized)

    try:
        jobs = await fetch_jobs(
            keywords=set(keywords) if keywords else None,
            skip_urls=skip_urls,
        )
        if jobs:
            await _ingest_raw_jobs(jobs)
    except Exception as e:
        logger.error("Crossover discovery failed: %s", e)


# ── Curated companies (Greenhouse / Lever / Ashby direct) ───────────────────


async def _run_curated_async():
    """Highest-signal source: poll a hand-picked list of remote-friendly
    companies on free public ATSes. Apply URLs are clean by construction
    (boards.greenhouse.io / jobs.lever.co / jobs.ashbyhq.com), so
    swipe-to-apply works end-to-end without redirect resolution."""
    from app.services.discovery.curated_service import fetch_jobs

    keywords = await _collect_all_keywords()
    try:
        jobs = await fetch_jobs(keywords=set(keywords) if keywords else None)
        if jobs:
            await _ingest_raw_jobs(jobs)
    except Exception as e:
        logger.error("Curated discovery failed: %s", e)


# ── DailyRemote (Cloudflare-gated remote board, ld+json scraping) ────────────


@celery_app.task(name="app.workers.discovery_tasks.run_dailyremote_discovery")
def run_dailyremote_discovery():
    """Run scheduled DailyRemote discovery — scrapes JobPosting JSON-LD."""
    _run_async(_run_dailyremote_async())


async def _run_dailyremote_async():
    from app.services.discovery.dailyremote_service import fetch_jobs

    keywords = await _collect_all_keywords()
    try:
        jobs = await fetch_jobs(keywords=set(keywords) if keywords else None)
        if jobs:
            await _ingest_raw_jobs(jobs)
    except Exception as e:
        logger.error("DailyRemote discovery failed: %s", e)
