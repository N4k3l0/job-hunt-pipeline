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

    Steps: normalize → deduplicate → store → queue scoring
    """
    async with create_worker_session()() as db:
        stored = 0
        skipped = 0

        for raw in jobs:
            try:
                company = raw.get("company", "Unknown")
                title = raw.get("title", "")
                location = raw.get("location")
                country = normalize_country(raw.get("country"))
                city = extract_city(location)

                # Compute canonical hash for dedup
                canonical_hash = compute_canonical_hash(company, title, city, country)

                # Check duplicates
                is_dup, _ = await check_duplicate(
                    db, canonical_hash, raw.get("raw_description", ""),
                    title=title, company=company,
                )
                if is_dup:
                    skipped += 1
                    continue

                # Get or create source
                source = await get_or_create_source(
                    db,
                    raw.get("source_name", "unknown"),
                    raw.get("source_type", "api"),
                )

                remote_type = (
                    raw.get("remote_type")
                    or classify_remote(location)
                    or classify_remote(title)
                    or classify_remote(raw.get("raw_description"), is_description=True)
                )

                # Create job
                job = Job(
                    external_id=raw.get("external_id"),
                    source_id=source.id,
                    company=company,
                    title=title,
                    location=location,
                    country=country,
                    remote_type=remote_type,
                    job_url=raw.get("job_url"),
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

                # If we have description content, create basic entities
                desc = raw.get("raw_description", "")
                if desc:
                    entities = JobEntity(
                        job_id=job.id,
                        skills=raw.get("tags", []),
                        requirements=[],
                        keywords=[],
                    )
                    db.add(entities)

                stored += 1

            except Exception as e:
                logger.error("Failed to ingest job '%s': %s", raw.get("title"), e)
                continue

        await db.commit()
        logger.info("Ingestion complete: %d stored, %d duplicates skipped", stored, skipped)

    # Auto-score new jobs for all users
    if stored > 0:
        try:
            from app.models.user import User
            async with create_worker_session()() as db:
                users = await db.execute(select(User.id))
                user_ids = [str(row[0]) for row in users.all()]
            for uid in user_ids:
                from app.workers.scoring_tasks import batch_score_for_user
                batch_score_for_user.delay(uid)
                logger.info("Queued scoring for user %s", uid)
        except Exception as e:
            logger.error("Failed to queue auto-scoring: %s", e)

        # Queue scoring for all active users
        if stored > 0:
            result = await db.execute(select(User))
            users = result.scalars().all()
            for user in users:
                from app.workers.scoring_tasks import batch_score_for_user
                batch_score_for_user.delay(str(user.id))


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

    Combines custom search_keywords + target_roles from all users.
    Returns deduplicated list.
    """
    from app.models.candidate import CandidateProfile

    async with create_worker_session()() as db:
        result = await db.execute(
            select(CandidateProfile.search_keywords, CandidateProfile.target_roles)
        )
        all_keywords = set()
        for search_kw, target_roles in result:
            if search_kw:
                for kw in search_kw:
                    all_keywords.add(kw.strip().lower())
            if target_roles:
                for role in target_roles:
                    all_keywords.add(role.strip().lower())

    keywords = list(all_keywords)
    logger.info("Collected %d unique search keywords from all users: %s", len(keywords), keywords)
    return keywords


# ── Adzuna ───────────────────────────────────────────────────────────────────


@celery_app.task(name="app.workers.discovery_tasks.run_adzuna_discovery")
def run_adzuna_discovery():
    """Run scheduled Adzuna API discovery across all target countries."""
    _run_async(_run_adzuna_async())


async def _run_adzuna_async():
    from app.services.discovery.adzuna_service import fetch_jobs, ADZUNA_COUNTRIES

    keywords = await _collect_all_keywords() or None  # None falls back to defaults
    for iso, code in ADZUNA_COUNTRIES.items():
        try:
            jobs = await fetch_jobs(country_code=code, keywords=keywords)
            if jobs:
                await _ingest_raw_jobs(jobs)
        except Exception as e:
            logger.error("Adzuna discovery failed for %s: %s", iso, e)


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

    try:
        # Fetch both with and without visa sponsorship filter
        jobs = await fetch_jobs(visa_sponsorship=False)
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
